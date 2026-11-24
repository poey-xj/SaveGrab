"""
SaveGrab —— 核心逻辑

基于开源项目 Legendary (GPL-3.0, https://github.com/legendary-gl/legendary)
的 Python API 实现，不使用它的命令行入口（避免多进程日志队列），
因此可以直接嵌进 GUI / 打包成 exe。

功能：
  1. 用 Epic 授权码登录，并把会话保存在本地（下次免登录）
  2. 列出账号里「支持云存档」的游戏，以及每个游戏在云端的存档快照
  3. 分析快照（文件数 / 体积 / 存档槽），多线程下载并还原成原始文件
  4. 一键还原到本机存档目录（自动备份），并支持 Steam/其他账号的目录
"""
from __future__ import annotations

import json
import os
import re
import shutil
import sys
import threading
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime

APP_NAME = "SaveGrab"
DEFAULT_WORKERS = 4
MAX_WORKERS = 8


# ---------------------------------------------------------------- 环境准备

_DATA_DIR: str | None = None


def _data_dir_candidates() -> list[str]:
    override = os.environ.get("SAVEGRAB_HOME")
    if override:
        return [override]
    local = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    roaming = os.environ.get("APPDATA") or os.path.expanduser("~")
    temp = os.environ.get("TEMP") or os.environ.get("TMP") or os.path.expanduser("~")
    home = os.path.expanduser("~")
    here = os.path.dirname(os.path.abspath(sys.executable if getattr(sys, "frozen", False) else __file__))
    return [
        os.path.join(local, APP_NAME),
        os.path.join(roaming, APP_NAME),
        os.path.join(home, f".{APP_NAME.lower()}"),
        os.path.join(temp, APP_NAME),
        os.path.join(here, f"{APP_NAME}-data"),
    ]


def app_data_dir() -> str:
    """找一个能写的数据目录。

    有些机器上安全软件会拦程序往 %LOCALAPPDATA% 写东西（报 WinError 5），
    所以这里按顺序尝试多个位置，实在不行才报错。
    """
    global _DATA_DIR
    if _DATA_DIR:
        return _DATA_DIR
    errors: list[str] = []
    for path in _data_dir_candidates():
        try:
            os.makedirs(path, exist_ok=True)
            probe = os.path.join(path, ".write-test")
            with open(probe, "w", encoding="utf-8") as fh:
                fh.write("ok")
            os.remove(probe)
            _DATA_DIR = path
            return path
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{path}  ->  {exc}")
    raise RuntimeError(
        "没有可写的数据目录，尝试过：\n" + "\n".join(errors)
        + "\n\n可以把程序换个目录运行，或设置环境变量 SAVEGRAB_HOME 指向一个可写文件夹。"
    )


def _bootstrap() -> None:
    """给 legendary 在用户目录里安个家；源码运行时再把它加进 sys.path。"""
    here = os.path.dirname(os.path.abspath(__file__))
    vendor = os.path.join(here, "vendor")
    # 打包成 exe 后 legendary 已经被 PyInstaller 编进去了，不再走 vendor 目录，
    # 否则会绕过打包的依赖解析（缺标准库模块）。
    if not getattr(sys, "frozen", False):
        if os.path.isdir(vendor) and vendor not in sys.path:
            sys.path.insert(0, vendor)

    cfg = os.path.join(app_data_dir(), "legendary")
    os.makedirs(cfg, exist_ok=True)
    os.environ["LEGENDARY_CONFIG_PATH"] = cfg

    cfg_file = os.path.join(cfg, "config.ini")
    if not os.path.exists(cfg_file):
        work = os.path.join(app_data_dir(), "work")
        os.makedirs(work, exist_ok=True)
        with open(cfg_file, "w", encoding="utf-8") as fh:
            fh.write(
                "[Legendary]\n"
                f"install_dir = {work}\n"
                "disable_update_check = true\n"
                "disable_update_notice = true\n"
            )


_bootstrap()

from legendary.core import LegendaryCore  # noqa: E402
from legendary.models.chunk import Chunk  # noqa: E402


# ---------------------------------------------------------------- 数据结构

@dataclass
class GameEntry:
    app_name: str
    title: str
    namespace: str
    save_folder: str

    @property
    def has_save_folder(self) -> bool:
        return bool(self.save_folder)


@dataclass
class Snapshot:
    manifest: str
    when: datetime
    file_count: int | None = None
    size: int | None = None
    slots: str = ""
    analysed: bool = False

    @property
    def stamp(self) -> str:
        return self.manifest[:-len(".manifest")] if self.manifest.endswith(".manifest") else self.manifest

    @property
    def size_text(self) -> str:
        if self.size is None:
            return "—"
        value = float(self.size)
        for unit in ("B", "KB", "MB", "GB"):
            if value < 1024 or unit == "GB":
                return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
            value /= 1024
        return f"{value:.1f} GB"


@dataclass
class SaveLocation:
    path: str
    kind: str

    @property
    def label(self) -> str:
        return f"[{self.kind}] {self.path}"


@dataclass
class ExportResult:
    path: str
    files: int
    bytes_written: int = 0
    backup: str = ""
    extra: dict = field(default_factory=dict)


# ---------------------------------------------------------------- 异常

class CloudSaverError(Exception):
    pass


class NotLoggedIn(CloudSaverError):
    pass


# ---------------------------------------------------------------- 主体

class CloudSaver:
    """对 Legendary API 的一层薄封装，所有耗时操作都是阻塞的（由 GUI 放到线程里跑）。"""

    def __init__(self, log=None):
        self._log = log or (lambda *_: None)
        self.core = LegendaryCore()
        # 国内访问 Epic 接口偶尔很慢 / 被重置，放宽超时
        self.core.egs.request_timeout = 90
        self._patch_timeout(self.core.egs.session)
        self._patch_timeout(self.core.egs.unauth_session)
        self._local = threading.local()
        self._snapshot_cache: dict[tuple[str, str], Snapshot] = {}
        os.makedirs(self.backup_dir, exist_ok=True)

    # ------------------------------------------------------------ 基础

    @property
    def backup_dir(self) -> str:
        return os.path.join(app_data_dir(), "backups")

    @property
    def cache_dir(self) -> str:
        return os.path.join(app_data_dir(), "cache")

    @staticmethod
    def _patch_timeout(session, timeout=90):
        orig = session.get

        def get(url, **kwargs):
            kwargs.setdefault("timeout", timeout)
            return orig(url, **kwargs)

        session.get = get

    def _thread_session(self):
        """给下载线程用的独立 session（requests.Session 不是线程安全的）。"""
        import requests

        session = getattr(self._local, "session", None)
        if session is None:
            session = requests.Session()
            session.headers.update({"User-Agent": f"{APP_NAME}/0.3"})
            self._local.session = session
        return session

    def log(self, msg: str) -> None:
        self._log(msg)

    # ------------------------------------------------------------ 登录

    @property
    def user(self) -> dict:
        return self.core.lgd.userdata or {}

    @property
    def is_logged_in(self) -> bool:
        return bool(self.user.get("access_token"))

    @property
    def display_name(self) -> str:
        return self.user.get("displayName") or ""

    @property
    def account_id(self) -> str:
        return self.user.get("account_id") or ""

    def resume_session(self) -> bool:
        """尝试用本地保存的会话登录（token 过期时会自动刷新）。"""
        try:
            ok = self.core.login()
        except Exception as exc:  # noqa: BLE001
            self.log(f"恢复登录失败：{exc!r}")
            return False
        if ok:
            self.log(f"已登录：{self.display_name}")
        return bool(ok)

    def login_urls(self) -> list[tuple[str, str]]:
        """返回可用的登录入口（官方页优先，第三方页兜底）。"""
        from urllib.parse import quote

        auth = getattr(self.core.egs, "_oauth_basic", None)
        client_id = getattr(auth, "username", "") or ""
        urls: list[tuple[str, str]] = []
        if client_id:
            redirect = (
                "https://www.epicgames.com/id/api/redirect"
                f"?clientId={client_id}&responseType=code"
            )
            urls.append(
                (
                    "① 打开 Epic 官方登录页",
                    "https://www.epicgames.com/id/login?redirectUrl=" + quote(redirect, safe=""),
                )
            )
        urls.append(("备用登录页（legendary.gl）", "https://legendary.gl/epiclogin"))
        return urls

    def parse_auth_input(self, text: str) -> str:
        """授权码输入框可以贴整段 JSON、带 code= 的地址，或者光秃秃的码。"""
        text = (text or "").strip()
        if not text:
            raise CloudSaverError("授权码是空的")
        if text.startswith("{"):
            try:
                data = json.loads(text)
            except json.JSONDecodeError as exc:
                raise CloudSaverError(f"这段 JSON 解析失败：{exc}") from exc
            code = data.get("authorizationCode") or data.get("code")
            if not code:
                raise CloudSaverError("JSON 里没有 authorizationCode 字段")
            return code
        # 常见情况：整段 JSON 少复制了开头/结尾的括号，用正则兜一下
        match = re.search(r'"authorizationCode"\s*:\s*"([^"]+)"', text)
        if match:
            return match.group(1)
        if "code=" in text:
            tail = text.split("code=", 1)[1]
            return tail.split("&")[0].strip().strip('"').strip()
        return text.strip('"').strip()

    def login_with_code(self, raw: str) -> None:
        code = self.parse_auth_input(raw)
        self.log("正在用授权码换取会话…")
        try:
            session = self.core.egs.start_session(authorization_code=code)
        except Exception as exc:  # noqa: BLE001
            raise CloudSaverError(f"登录失败：{exc}") from exc
        with self.core.lgd.userdata_lock as lock:
            lock.data = session
        self.log(f"登录成功：{self.display_name}")

    def logout(self) -> None:
        self.core.lgd.invalidate_userdata()
        self.log("已退出登录")

    # ------------------------------------------------------------ 游戏库

    def list_games(self) -> list[GameEntry]:
        if not self.is_logged_in:
            raise NotLoggedIn("还没登录")
        self.log("正在读取游戏库…")
        raw = self.core.get_game_list()
        self.log(f"账号内共 {len(raw)} 个条目，正在筛选支持云存档的…")
        out: list[GameEntry] = []
        for game in raw:
            try:
                if not game.supports_cloud_saves:
                    continue
                folder = game.metadata.get("customAttributes", {}).get("CloudSaveFolder", {}).get("value", "")
                out.append(GameEntry(game.app_name, game.app_title, game.namespace, folder))
            except Exception:  # noqa: BLE001
                continue
        out.sort(key=lambda g: g.title.lower())
        self.log(f"其中 {len(out)} 个游戏支持云存档")
        return out

    # ------------------------------------------------------------ 快照

    def list_snapshots(self, app_name: str) -> list[Snapshot]:
        if not self.is_logged_in:
            raise NotLoggedIn("还没登录")
        raw = self._with_retry(lambda: self.core.get_save_games(app_name), "读取快照列表")
        snaps = []
        for s in raw:
            cached = self._snapshot_cache.get((app_name, s.manifest_name))
            if cached:
                cached.when = s.datetime
                snaps.append(cached)
            else:
                snaps.append(Snapshot(s.manifest_name, s.datetime))
        snaps.sort(key=lambda s: s.when, reverse=True)
        return snaps

    def analyse_snapshot(self, app_name: str, snap: Snapshot) -> Snapshot:
        """下载 manifest（只有几 KB），算出文件数、体积、存档槽摘要。"""
        if snap.analysed:
            return snap
        _, _, man = self._load_manifest(app_name, snap.manifest)
        files = list(man.file_manifest_list.elements)
        snap.file_count = len(files)
        snap.size = sum(fm.file_size for fm in files)
        snap.slots = self._summarise_slots(files)
        snap.analysed = True
        self._snapshot_cache[(app_name, snap.manifest)] = snap
        return snap

    @staticmethod
    def _summarise_slots(files) -> str:
        groups: dict[str, set[str]] = {"manual": set(), "auto": set(), "quick": set()}
        for fm in files:
            top = fm.filename.replace("\\", "/").split("/")[0].lower()
            for key in groups:
                if top.startswith(key):
                    groups[key].add(top)
        parts = []
        for key, label in (("manual", "手动"), ("auto", "自动"), ("quick", "快速")):
            if groups[key]:
                parts.append(f"{label}{len(groups[key])}")
        return " · ".join(parts) or f"{len(files)} 个文件"

    # ------------------------------------------------------------ 下载

    def _with_retry(self, func, what: str, tries: int = 3):
        last: Exception | None = None
        for i in range(1, tries + 1):
            try:
                return func()
            except Exception as exc:  # noqa: BLE001
                last = exc
                self.log(f"{what}失败（第 {i}/{tries} 次）：{type(exc).__name__}")
                time.sleep(2 * i)
        raise CloudSaverError(f"{what}失败：{last}") from last

    def _get_bytes(self, url: str, what: str = "下载") -> bytes:
        def once():
            resp = self.core.egs.unauth_session.get(url, timeout=120)
            if resp.status_code != 200:
                raise CloudSaverError(f"HTTP {resp.status_code}")
            if not resp.content:
                raise CloudSaverError("返回内容为空")
            return resp.content

        return self._with_retry(once, what)

    def _fetch_chunk(self, url: str, label: str) -> bytes:
        def once():
            resp = self._thread_session().get(url, timeout=120)
            if resp.status_code != 200:
                raise CloudSaverError(f"HTTP {resp.status_code}")
            if not resp.content:
                raise CloudSaverError("返回内容为空")
            return resp.content

        return self._with_retry(once, f"下载分块 {label}")

    def _load_manifest(self, app_name: str, manifest: str):
        listing = self._with_retry(
            lambda: self.core.egs.get_user_cloud_saves(app_name), "读取云端文件清单"
        )
        files = listing.get("files") or {}
        target = next(
            (key for key in files if key.endswith("/" + manifest) or key == manifest), None
        )
        if target is None:
            raise CloudSaverError(f"云端找不到快照 {manifest}")
        raw = self._get_bytes(files[target]["readLink"], "下载 manifest")
        return files, target, self.core.load_manifest(raw)

    def export_snapshot(
        self,
        app_name: str,
        manifest: str,
        dest_dir: str,
        on_progress=None,
        make_zip: bool = False,
        workers: int = DEFAULT_WORKERS,
    ) -> ExportResult:
        """多线程下载一个快照并还原成文件。"""
        if not self.is_logged_in:
            raise NotLoggedIn("还没登录")

        def report(done: int, total: int, phase: str) -> None:
            if on_progress:
                on_progress(done, total, phase)

        self.log(f"读取云端文件清单…（{manifest}）")
        files, target, man = self._load_manifest(app_name, manifest)
        prefix = target.rsplit("/manifests/", 1)[0]

        elems = list(man.chunk_data_list.elements)
        total = len(elems)
        report(0, total, "准备下载分块")
        chunks: dict[int, bytes] = {}
        done = 0
        workers = max(1, min(int(workers or DEFAULT_WORKERS), MAX_WORKERS))
        self.log(f"开始下载 {total} 个分块（{workers} 线程）…")
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {}
            for chunk in elems:
                info = files.get(f"{prefix}/{chunk.path}")
                if not info:
                    self.log(f"警告：清单里缺少 {chunk.path}")
                    continue
                futures[pool.submit(self._fetch_chunk, info["readLink"], chunk.path)] = chunk
            try:
                for fut in as_completed(futures):
                    chunk = futures[fut]
                    parsed = Chunk.read_buffer(fut.result())
                    chunks[parsed.guid_num] = parsed.data
                    done += 1
                    report(done, total, f"下载分块 {done}/{total}")
            except Exception:
                for fut in futures:
                    fut.cancel()
                raise

        os.makedirs(dest_dir, exist_ok=True)
        written = 0
        bytes_written = 0
        file_elems = list(man.file_manifest_list.elements)
        for idx, fm in enumerate(file_elems, 1):
            relative = fm.filename.replace("\\", "/")
            path = os.path.join(dest_dir, *relative.split("/"))
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "wb") as fh:
                for part in fm.chunk_parts:
                    data = chunks.get(part.guid_num)
                    if data is None:
                        raise CloudSaverError(f"{relative} 缺少分块数据")
                    fh.write(data[part.offset: part.offset + part.size])
            written += 1
            bytes_written += fm.file_size
            report(written, len(file_elems), f"写出文件 {written}/{len(file_elems)}")

        self.log(f"已还原 {written} 个文件 → {dest_dir}")
        result = ExportResult(dest_dir, written, bytes_written)
        if make_zip:
            zip_path = dest_dir.rstrip("\\/") + ".zip"
            self.log("正在打包 zip…")
            with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
                for root, _dirs, names in os.walk(dest_dir):
                    for name in names:
                        full = os.path.join(root, name)
                        zf.write(full, os.path.relpath(full, dest_dir))
            self.log(f"打包完成 → {zip_path}")
            result.path = zip_path
        return result

    # ------------------------------------------------------------ 本地存档目录

    def resolve_save_dir(self, game: GameEntry) -> str | None:
        """把 Epic 元数据里的 {appdata}/../locallow/... 之类的模板还原成本机路径。"""
        template = (game.save_folder or "").strip()
        if not template:
            return None
        text = template.replace("\\", "/")
        unresolved: list[str] = []

        def repl(match: re.Match) -> str:
            key = match.group(1).lower()
            mapping = {
                "appdata": os.environ.get("LOCALAPPDATA", ""),
                "localappdata": os.environ.get("LOCALAPPDATA", ""),
                "userdir": os.path.join(os.path.expanduser("~"), "Documents"),
                "userprofile": os.path.expanduser("~"),
                "epicid": self.account_id,
                "installdir": "",
            }
            if key not in mapping or (key == "installdir"):
                unresolved.append(key)
                return match.group(0)
            value = mapping[key]
            if not value:
                unresolved.append(key)
            return value

        resolved = re.sub(r"\{([A-Za-z_]+)\}", repl, text)
        if unresolved:
            raise CloudSaverError(
                "这个游戏的存档目录依赖安装路径，工具没法自动算，请手动选择目录"
            )
        resolved = os.path.normpath(resolved.replace("/", "\\"))
        # 统一显示成 LocalLow（Windows 不区分大小写，路径本身不变）
        resolved = re.sub(r"\\locallow\\", r"\\LocalLow\\", resolved, flags=re.I)
        return resolved

    def list_save_locations(self, game: GameEntry) -> list[SaveLocation]:
        """列出本机可能属于这个游戏的存档目录（Epic 当前账号 / Steam 账号 / 其他）。"""
        out: list[SaveLocation] = []
        try:
            base = self.resolve_save_dir(game)
        except CloudSaverError as exc:
            self.log(str(exc))
            return out
        if not base:
            return out
        out.append(SaveLocation(base, "Epic 当前账号" if base.rstrip("\\/").endswith(self.account_id) else "Epic"))

        parent = os.path.dirname(base.rstrip("\\/"))
        if os.path.isdir(parent):
            try:
                names = sorted(os.listdir(parent))
            except OSError:
                names = []
            for name in names:
                full = os.path.join(parent, name)
                if not os.path.isdir(full) or os.path.normcase(full) == os.path.normcase(base):
                    continue
                if re.fullmatch(r"[0-9a-fA-F]{32}", name):
                    kind = "Epic 其他账号"
                elif re.fullmatch(r"\d{17}", name):
                    kind = "Steam 账号"
                else:
                    kind = "其他账号"
                out.append(SaveLocation(full, kind))
        return out

    def restore_snapshot(
        self,
        app_name: str,
        manifest: str,
        target_dir: str,
        backup: bool = True,
        on_progress=None,
        workers: int = DEFAULT_WORKERS,
    ) -> ExportResult:
        """把某个云端快照直接还原到本机目录（先下载到缓存，再复制过去）。"""
        if not self.is_logged_in:
            raise NotLoggedIn("还没登录")
        if not target_dir:
            raise CloudSaverError("没有指定还原目录")

        safe_app = re.sub(r"[^0-9A-Za-z_.-]", "_", app_name)
        stamp = manifest[:-len(".manifest")] if manifest.endswith(".manifest") else manifest
        cache = os.path.join(self.cache_dir, safe_app, stamp)
        if not (os.path.isdir(cache) and any(os.scandir(cache))):
            exported = self.export_snapshot(
                app_name, manifest, cache, on_progress=on_progress, workers=workers
            )
            file_count = exported.files
        else:
            file_count = sum(len(names) for _, _, names in os.walk(cache))
            self.log(f"复用本地缓存：{cache}")

        backup_path = ""
        if backup and os.path.isdir(target_dir):
            existing = [n for n in os.listdir(target_dir)]
            if existing:
                os.makedirs(self.backup_dir, exist_ok=True)
                backup_path = os.path.join(
                    self.backup_dir,
                    f"{safe_app}_{datetime.now():%Y%m%d-%H%M%S}.zip",
                )
                self.log(f"备份现有存档 → {backup_path}")
                with zipfile.ZipFile(backup_path, "w", zipfile.ZIP_DEFLATED) as zf:
                    for root, _dirs, names in os.walk(target_dir):
                        for name in names:
                            full = os.path.join(root, name)
                            zf.write(full, os.path.relpath(full, target_dir))

        os.makedirs(target_dir, exist_ok=True)
        copied = 0
        total = sum(len(names) for _, _, names in os.walk(cache))
        for root, _dirs, names in os.walk(cache):
            rel = os.path.relpath(root, cache)
            out_dir = target_dir if rel == "." else os.path.join(target_dir, rel)
            os.makedirs(out_dir, exist_ok=True)
            for name in names:
                shutil.copy2(os.path.join(root, name), os.path.join(out_dir, name))
                copied += 1
                if on_progress:
                    on_progress(copied, total, f"写入存档 {copied}/{total}")
        self.log(f"已还原 {copied} 个文件 → {target_dir}")
        return ExportResult(target_dir, file_count, backup=backup_path)
