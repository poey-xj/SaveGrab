"""
下载源码运行所需的第三方包到 vendor/（不需要 pip 能联网装包）。

用法：
    python build/fetch_vendor.py

说明：
    - 仓库里不提交 vendor/（里面有二进制 .pyd，体积大且不适合放 git）
    - 跑完这个脚本后，`python main.py` 就能直接从源码启动
    - 打包 exe 也会用到这个目录（见 build/build_exe.bat）
"""
from __future__ import annotations

import io
import json
import os
import re
import sys
import time
import urllib.request
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
DEST = os.path.normpath(os.path.join(HERE, "..", "vendor"))

# CI（GitHub Windows runner）默认 cp1252，打印中文会崩，这里强制 UTF-8
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass

# 与 v0.3.0 发布时一致的版本（legendary 0.21.1 + 它的依赖）
PACKAGES = {
    "legendary-gl": "0.21.1",
    "requests": "2.34.2",
    "urllib3": "2.8.0",
    "certifi": "2026.11.20",
    "charset-normalizer": "3.5.3",
    "idna": "3.20",
    "pycryptodomex": "3.24.2",
    "filelock": "4.3.1",
}

PY = f"cp{sys.version_info.major}{sys.version_info.minor}"


def pick_wheel(files: list[dict]) -> dict | None:
    ranked: list[tuple[int, dict]] = []
    for item in files:
        name = item["filename"]
        if not name.endswith(".whl"):
            continue
        if name.endswith("-py3-none-any.whl") or name.endswith("-py2.py3-none-any.whl"):
            ranked.append((0, item))
        elif f"-{PY}-{PY}-win_amd64.whl" in name:
            ranked.append((1, item))
        elif re.search(r"-cp3\d+-abi3-win_amd64\.whl$", name):
            ranked.append((2, item))
        elif name.endswith("-py3-none-win_amd64.whl"):
            ranked.append((3, item))
    if not ranked:
        return None
    ranked.sort(key=lambda pair: pair[0])
    return ranked[0][1]


def fetch(url: str, tries: int = 4, timeout: int = 180) -> bytes:
    last = None
    for attempt in range(1, tries + 1):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "fetch-vendor"})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read()
        except Exception as exc:  # noqa: BLE001
            last = exc
            print(f"    retry {attempt}/{tries}: {exc!r}", flush=True)
            time.sleep(2 * attempt)
    raise RuntimeError(f"下载失败：{last}")


def main() -> int:
    os.makedirs(DEST, exist_ok=True)
    print("目标目录：", DEST, flush=True)
    for package, version in PACKAGES.items():
        try:
            with urllib.request.urlopen(
                f"https://pypi.org/pypi/{package}/{version}/json", timeout=60
            ) as resp:
                data = json.load(resp)
        except Exception as exc:  # noqa: BLE001
            print(f"!! {package}: 获取元数据失败 {exc!r}", flush=True)
            continue
        wheel = pick_wheel(data.get("urls", []))
        if wheel is None:
            print(f"!! {package} {version}: 没有兼容的 wheel")
            continue
        print(f"[{package} {version}] {wheel['filename']}", flush=True)
        blob = fetch(wheel["url"])
        with zipfile.ZipFile(io.BytesIO(blob)) as zf:
            zf.extractall(DEST)
        print(f"    ok {len(blob)} bytes", flush=True)
    print("完成。现在可以运行：python main.py", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
