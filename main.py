"""
SaveGrab —— 图形界面

运行： python main.py
自检： python main.py --selftest            （生成 preview.png 后退出）
      python main.py --selftest-login      （生成含登录弹窗的截图）
命令行：
      python main.py --cli-export Boga D:/saves
      python main.py --cli-restore Boga "C:/Users/<you>/AppData/LocalLow/KojimaProductions/DeathStranding/<EpicID>"
"""
from __future__ import annotations

import ctypes
import logging
import os
import queue
import sys
import threading
import time
import tkinter as tk
import webbrowser
from datetime import datetime
from tkinter import filedialog, messagebox, ttk

# 打包成 windowed exe 后 stdout/stderr 是 None，给 logging 兜个底
logging.getLogger().addHandler(logging.NullHandler())

try:  # 高 DPI 下界面才不糊
    ctypes.windll.shcore.SetProcessDpiAwareness(1)
except Exception:  # noqa: BLE001
    pass

from epic_core import (  # noqa: E402
    DEFAULT_WORKERS,
    CloudSaver,
    CloudSaverError,
    ExportResult,
    GameEntry,
    SaveLocation,
    Snapshot,
    app_data_dir,
)

VERSION = "0.3.1"
LOGIN_URL = "https://legendary.gl/epiclogin"

BG = "#16171d"
PANEL = "#20222b"
PANEL_2 = "#262935"
HEADER = "#2c3040"
BORDER = "#31343f"
FG = "#e8eaf2"
DIM = "#9aa0b4"
ACCENT = "#4f8cff"
ACCENT_2 = "#3a6fd8"
GREEN = "#3ecf8e"
GREEN_2 = "#2f9e6e"
RED = "#ff6b6b"

FONT = ("Microsoft YaHei UI", 10)
FONT_BOLD = ("Microsoft YaHei UI", 11, "bold")
FONT_TITLE = ("Microsoft YaHei UI", 15, "bold")
FONT_SMALL = ("Microsoft YaHei UI", 9)
FONT_MONO = ("Consolas", 9)


def human_time(dt: datetime) -> str:
    return dt.astimezone().strftime("%Y-%m-%d %H:%M")


def resource_path(*parts: str) -> str:
    """兼容源码运行和 PyInstaller 打包后的资源路径。"""
    base = getattr(sys, "_MEIPASS", None) or os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base, *parts)


def _say(msg: str) -> None:
    try:
        print(msg)
    except Exception:  # noqa: BLE001
        pass


def _crash_log(text: str) -> None:
    """windowed exe 没有控制台，崩溃信息往文件里写。"""
    candidates = []
    try:
        candidates.append(os.path.join(app_data_dir(), "error.log"))
    except Exception:  # noqa: BLE001
        pass
    try:
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            candidates.append(os.path.join(os.path.dirname(meipass), "error.log"))
        candidates.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), "error.log"))
    except Exception:  # noqa: BLE001
        pass
    for path in candidates:
        try:
            with open(path, "a", encoding="utf-8") as fh:
                fh.write(text)
            _say(f"crash log -> {path}")
            return
        except Exception:  # noqa: BLE001
            continue


def _install_crash_hooks() -> None:
    import traceback

    def hook(exc_type, exc, tb):
        _crash_log(
            f"\n=== {datetime.now():%Y-%m-%d %H:%M:%S} ===\n"
            + "".join(traceback.format_exception(exc_type, exc, tb))
        )

    sys.excepthook = hook


class LoginDialog(tk.Toplevel):
    WIDTH = 640
    HEIGHT = 560
    PLACEHOLDER = "在这里粘贴 Epic 返回的 JSON（或单独的 authorizationCode）"

    def __init__(self, master: "App"):
        super().__init__(master)
        self.app = master
        self._placeholder_on = False
        self.title("登录 Epic 账号")
        self.configure(bg=BG)
        self.resizable(False, False)
        self.transient(master)
        self.grab_set()

        master.update_idletasks()
        px, py = master.winfo_rootx(), master.winfo_rooty()
        pw, ph = master.winfo_width(), master.winfo_height()
        self.geometry(
            f"{self.WIDTH}x{self.HEIGHT}"
            f"+{px + max(0, (pw - self.WIDTH) // 2)}+{py + max(0, (ph - self.HEIGHT) // 2)}"
        )

        pad = {"padx": 22}
        tk.Label(self, text="登录 Epic 账号", bg=BG, fg=FG, font=FONT_TITLE).pack(
            anchor="w", pady=(20, 6), **pad
        )
        tk.Label(
            self,
            text=(
                "1. 点下面的按钮打开 Epic 登录页，用你的 Epic 账号登录\n"
                "2. 登录后会返回一段 JSON（含 authorizationCode）\n"
                "3. 整段复制，粘贴到下面的输入框，点「登录」\n\n"
                "授权码只用于换取一次登录会话，本工具不会保存你的密码。"
            ),
            bg=BG, fg=DIM, font=FONT, justify="left",
        ).pack(anchor="w", **pad)

        try:
            urls = master.saver.login_urls()
        except Exception:  # noqa: BLE001
            urls = [("打开 Epic 登录页", LOGIN_URL)]
        row_btn = tk.Frame(self, bg=BG)
        row_btn.pack(anchor="w", pady=(12, 0), **pad)
        for idx, (label, url) in enumerate(urls):
            style = "Accent.TButton" if idx == 0 else "TButton"
            ttk.Button(row_btn, text=label, style=style,
                       command=lambda u=url: webbrowser.open(u)).pack(side="left", padx=(0, 8))

        self.text = tk.Text(self, height=8, bg=PANEL, fg=FG, insertbackground=FG,
                            relief="flat", font=FONT_MONO, wrap="char", padx=10, pady=8)
        self.text.pack(fill="both", expand=True, **pad)
        self.text.insert("1.0", self.PLACEHOLDER)
        self.text.configure(fg=DIM)
        self._placeholder_on = True
        self.text.bind("<FocusIn>", self._clear_placeholder)
        self.text.bind("<1>", self._clear_placeholder)
        self.text.bind("<Control-a>", self._select_all)

        row = tk.Frame(self, bg=BG)
        row.pack(fill="x", pady=14, **pad)
        ttk.Button(row, text="取消", command=self.destroy).pack(side="right")
        self.ok = ttk.Button(row, text="登录", style="Accent.TButton", command=self._submit)
        self.ok.pack(side="right", padx=(0, 10))

        self.status = tk.Label(self, text="", bg=BG, fg=DIM, font=FONT)
        self.status.pack(anchor="w", pady=(0, 16), **pad)

    def _select_all(self, _event=None):
        self.text.tag_add("sel", "1.0", "end-1c")
        return "break"

    def _clear_placeholder(self, _event=None):
        if self._placeholder_on:
            self.text.delete("1.0", "end")
            self.text.configure(fg=FG)
            self._placeholder_on = False

    def _submit(self):
        raw = "" if self._placeholder_on else self.text.get("1.0", "end").strip()
        if not raw:
            self.status.configure(text="先粘贴授权码", fg=RED)
            return
        self.ok.state(["disabled"])
        self.status.configure(text="正在登录…", fg=DIM)

        def work():
            try:
                self.app.saver.login_with_code(raw)
                self.app.queue.put(("login_ok", None))
            except Exception as exc:  # noqa: BLE001
                self.app.queue.put(("login_fail", str(exc)))

        threading.Thread(target=work, daemon=True).start()


class App(tk.Tk):
    def __init__(self, demo: bool = False, autoshot: bool = False, login_shot: bool = False):
        super().__init__()
        self.demo = demo
        self.title("SaveGrab")
        self.geometry("1240x830")
        self.minsize(1080, 720)
        self.configure(bg=BG)

        icon = resource_path("assets", "app.ico")
        if os.path.exists(icon):
            try:
                self.iconbitmap(icon)
            except Exception:  # noqa: BLE001
                pass

        self.queue: "queue.Queue[tuple]" = queue.Queue()
        self.saver = CloudSaver(log=self._log_threadsafe)
        self.games: list[GameEntry] = []
        self.snapshots: list[Snapshot] = []
        self.current_app = ""
        self.location_map: dict[str, str] = {}
        self.busy = False
        self.dest_var = tk.StringVar(
            value=os.path.join(os.path.expanduser("~"), "Documents", "Epic云存档")
        )

        self._build_style()
        self._build_ui()
        self.after(120, self._poll)
        self._refresh_account()

        if demo:
            self._load_demo()
            if autoshot and login_shot:
                self.after(400, self._open_login)
                self.after(1800, self._selftest_grab)
            elif autoshot:
                self.after(600, self._selftest_grab)
        else:
            self.after(200, self._startup_login)

    # ------------------------------------------------------------ 样式

    def _build_style(self):
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure(".", background=BG, foreground=FG, font=FONT,
                        bordercolor=BORDER, focuscolor=BG)
        style.configure("TFrame", background=BG)
        style.configure("TLabel", background=BG, foreground=FG)
        style.configure("TButton", background=PANEL_2, foreground=FG, borderwidth=0,
                        padding=(14, 8), focusthickness=0)
        style.map("TButton",
                  background=[("active", HEADER), ("disabled", PANEL)],
                  foreground=[("disabled", DIM)])
        style.configure("Accent.TButton", background=ACCENT, foreground="#ffffff")
        style.map("Accent.TButton", background=[("active", ACCENT_2), ("disabled", PANEL)],
                  foreground=[("disabled", DIM)])
        style.configure("Restore.TButton", background=GREEN_2, foreground="#ffffff")
        style.map("Restore.TButton", background=[("active", "#268a5f"), ("disabled", PANEL)],
                  foreground=[("disabled", DIM)])
        style.configure("TEntry", fieldbackground=PANEL, foreground=FG,
                        insertcolor=FG, borderwidth=0, padding=7)
        style.configure("TCheckbutton", background=BG, foreground=FG, focusthickness=0)
        style.map("TCheckbutton", background=[("active", BG)])
        style.configure("Treeview", background=PANEL, fieldbackground=PANEL, foreground=FG,
                        rowheight=27, borderwidth=0)
        style.map("Treeview", background=[("selected", ACCENT_2)],
                  foreground=[("selected", "#ffffff")])
        style.configure("Treeview.Heading", background=HEADER, foreground=DIM,
                        relief="flat", borderwidth=0, padding=(6, 7))
        style.map("Treeview.Heading", background=[("active", HEADER)])
        style.configure("TProgressbar", background=ACCENT, troughcolor=PANEL,
                        borderwidth=0, thickness=6)
        style.configure("Vertical.TScrollbar", background=PANEL_2, troughcolor=BG,
                        arrowcolor=DIM, borderwidth=0)
        style.configure("TCombobox", fieldbackground=PANEL, background=PANEL_2,
                        foreground=FG, arrowcolor=DIM, bordercolor=BORDER,
                        lightcolor=PANEL, darkcolor=PANEL, padding=5)
        style.map("TCombobox",
                  fieldbackground=[("readonly", PANEL), ("active", PANEL)],
                  foreground=[("readonly", FG)],
                  background=[("active", PANEL_2), ("readonly", PANEL_2)],
                  selectbackground=[("readonly", PANEL)],
                  selectforeground=[("readonly", FG)])
        self.option_add("*TCombobox*Listbox.background", PANEL)
        self.option_add("*TCombobox*Listbox.foreground", FG)
        self.option_add("*TCombobox*Listbox.selectBackground", ACCENT_2)
        self.option_add("*TCombobox*Listbox.selectForeground", "#ffffff")

    # ------------------------------------------------------------ 界面

    def _build_ui(self):
        header = tk.Frame(self, bg=BG)
        header.grid(row=0, column=0, sticky="ew", padx=18, pady=(16, 10))
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)

        line1 = tk.Frame(header, bg=BG)
        line1.pack(fill="x")
        tk.Label(line1, text="SaveGrab", bg=BG, fg=FG, font=FONT_TITLE).pack(side="left")
        tk.Label(line1, text=f"v{VERSION}", bg=BG, fg=DIM, font=FONT).pack(
            side="left", padx=(10, 0), pady=(6, 0)
        )

        self.account_label = tk.Label(line1, text="未登录", bg=BG, fg=DIM, font=FONT)
        self.account_label.pack(side="right", padx=(10, 0))
        self.logout_btn = ttk.Button(line1, text="退出登录", command=self._logout)
        self.logout_btn.pack(side="right", padx=(8, 0))
        self.login_btn = ttk.Button(line1, text="登录 Epic", style="Accent.TButton",
                                    command=self._open_login)
        self.login_btn.pack(side="right")

        line2 = tk.Frame(header, bg=BG)
        line2.pack(fill="x", pady=(2, 0))
        tk.Label(line2, text="不用下载游戏，直连 Epic 云端把存档拉回本地",
                 bg=BG, fg=DIM, font=FONT).pack(side="left")

        body = tk.Frame(self, bg=BG)
        body.grid(row=1, column=0, sticky="nsew", padx=18, pady=(0, 8))
        body.columnconfigure(0, weight=3, minsize=360)
        body.columnconfigure(1, weight=4)
        body.rowconfigure(0, weight=1)

        self._build_left(body)
        self._build_right(body)

        footer = tk.Frame(self, bg=BG)
        footer.grid(row=2, column=0, sticky="ew", padx=18, pady=(0, 14))
        footer.columnconfigure(0, weight=1)

        self.progress = ttk.Progressbar(footer, mode="determinate", maximum=100)
        self.progress.grid(row=0, column=0, sticky="ew", pady=(0, 5))
        self.status = tk.Label(footer, text="准备就绪", bg=BG, fg=DIM, font=FONT, anchor="w")
        self.status.grid(row=1, column=0, sticky="ew")

        self.logbox = tk.Text(footer, height=6, bg=PANEL, fg=DIM, relief="flat",
                              font=FONT_MONO, wrap="word", padx=10, pady=8,
                              insertbackground=FG, state="disabled")
        self.logbox.grid(row=2, column=0, sticky="ew", pady=(8, 0))

    def _build_left(self, parent):
        frame = tk.Frame(parent, bg=BG)
        frame.grid(row=0, column=0, sticky="nsew", padx=(0, 12))

        top = tk.Frame(frame, bg=BG)
        top.pack(fill="x")
        tk.Label(top, text="游戏库", bg=BG, fg=FG, font=FONT_BOLD).pack(side="left")
        tk.Label(top, text="仅显示支持云存档的", bg=BG, fg=DIM, font=FONT).pack(side="left", padx=(8, 0))
        self.refresh_btn = ttk.Button(top, text="刷新", command=self._refresh_games)
        self.refresh_btn.pack(side="right")

        self.search_var = tk.StringVar()
        self.search_var.trace_add("write", lambda *_: self._filter_games())
        search_row = tk.Frame(frame, bg=BG)
        search_row.pack(fill="x", pady=(8, 8))
        tk.Label(search_row, text="搜索", bg=BG, fg=DIM, font=FONT).pack(side="left", padx=(0, 8))
        ttk.Entry(search_row, textvariable=self.search_var).pack(side="left", fill="x", expand=True)

        wrap = tk.Frame(frame, bg=PANEL)
        wrap.pack(fill="both", expand=True)
        self.games_tree = ttk.Treeview(wrap, columns=("title", "app"), show="headings",
                                       selectmode="browse")
        self.games_tree.heading("title", text="游戏")
        self.games_tree.heading("app", text="代号")
        self.games_tree.column("title", width=230, anchor="w")
        self.games_tree.column("app", width=90, anchor="w")
        self.games_tree.pack(side="left", fill="both", expand=True)
        sb = ttk.Scrollbar(wrap, orient="vertical", command=self.games_tree.yview)
        sb.pack(side="right", fill="y")
        self.games_tree.configure(yscrollcommand=sb.set)
        self.games_tree.bind("<<TreeviewSelect>>", lambda _e: self._on_game_selected())

    def _build_right(self, parent):
        frame = tk.Frame(parent, bg=BG)
        frame.grid(row=0, column=1, sticky="nsew")
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(1, weight=1)

        top = tk.Frame(frame, bg=BG)
        top.grid(row=0, column=0, sticky="ew")
        tk.Label(top, text="云端快照", bg=BG, fg=FG, font=FONT_BOLD).pack(side="left")
        self.snapshot_hint = tk.Label(top, text="先选左边一个游戏", bg=BG, fg=DIM, font=FONT)
        self.snapshot_hint.pack(side="left", padx=(8, 0))

        wrap = tk.Frame(frame, bg=PANEL)
        wrap.grid(row=1, column=0, sticky="nsew", pady=(8, 10))
        self.snap_tree = ttk.Treeview(
            wrap, columns=("time", "files", "size", "slots", "stamp"),
            show="headings", selectmode="extended", height=8,
        )
        for column, title, width, stretch in (
            ("time", "存档时间", 190, False),
            ("files", "文件", 52, False),
            ("size", "大小", 78, False),
            ("slots", "内容", 150, True),
            ("stamp", "快照", 128, False),
        ):
            self.snap_tree.heading(column, text=title)
            self.snap_tree.column(column, width=width, anchor="w", stretch=stretch)
        self.snap_tree.pack(side="left", fill="both", expand=True)
        sb = ttk.Scrollbar(wrap, orient="vertical", command=self.snap_tree.yview)
        sb.pack(side="right", fill="y")
        self.snap_tree.configure(yscrollcommand=sb.set)

        opts = tk.Frame(frame, bg=BG)
        opts.grid(row=2, column=0, sticky="ew")
        tk.Label(opts, text="导出到", bg=BG, fg=DIM, font=FONT).pack(side="left")
        ttk.Entry(opts, textvariable=self.dest_var).pack(side="left", fill="x", expand=True, padx=8)
        ttk.Button(opts, text="浏览", command=self._choose_dir).pack(side="left")

        row2 = tk.Frame(frame, bg=BG)
        row2.grid(row=3, column=0, sticky="ew", pady=(10, 0))
        self.zip_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(row2, text="打包 ZIP", variable=self.zip_var).pack(side="left")
        tk.Label(row2, text="线程", bg=BG, fg=DIM, font=FONT).pack(side="left", padx=(12, 4))
        self.workers_var = tk.StringVar(value=str(DEFAULT_WORKERS))
        ttk.Combobox(row2, textvariable=self.workers_var, width=3, state="readonly",
                     values=["2", "4", "6", "8"]).pack(side="left")
        self.export_all_btn = ttk.Button(row2, text="导出全部", command=lambda: self._export(False))
        self.export_all_btn.pack(side="right")
        self.export_btn = ttk.Button(row2, text="导出选中", style="Accent.TButton",
                                     command=lambda: self._export(True))
        self.export_btn.pack(side="right", padx=(0, 8))
        self.open_btn = ttk.Button(row2, text="打开目录", command=self._open_dest)
        self.open_btn.pack(side="right", padx=(0, 8))

        row3 = tk.Frame(frame, bg=BG)
        row3.grid(row=4, column=0, sticky="ew", pady=(10, 0))
        tk.Label(row3, text="还原到", bg=BG, fg=DIM, font=FONT).pack(side="left")
        self.target_var = tk.StringVar()
        self.target_combo = ttk.Combobox(row3, textvariable=self.target_var, state="readonly")
        self.target_combo.pack(side="left", fill="x", expand=True, padx=8)
        ttk.Button(row3, text="浏览", command=self._choose_target).pack(side="left")
        self.restore_btn = ttk.Button(row3, text="一键还原选中", style="Restore.TButton",
                                      command=self._restore)
        self.restore_btn.pack(side="left", padx=(8, 0))

        self.restore_hint = tk.Label(frame, text="", bg=BG, fg=DIM, font=FONT_SMALL, anchor="w")
        self.restore_hint.grid(row=5, column=0, sticky="ew", pady=(6, 0))

    # ------------------------------------------------------------ 日志 / 状态

    def _log(self, msg: str):
        stamp = datetime.now().strftime("%H:%M:%S")
        self.logbox.configure(state="normal")
        self.logbox.insert("end", f"[{stamp}] {msg}\n")
        self.logbox.see("end")
        self.logbox.configure(state="disabled")

    def _log_threadsafe(self, msg: str):
        self.queue.put(("log", msg))

    def _set_status(self, text: str, color: str = DIM):
        self.status.configure(text=text, fg=color)

    def _progress(self, done: int, total: int, phase: str = ""):
        pct = 0 if total <= 0 else min(100, int(done * 100 / total))
        self.progress.configure(value=pct)
        if phase:
            self._set_status(f"{phase}  ({pct}%)")

    def _poll(self):
        try:
            while True:
                kind, payload = self.queue.get_nowait()
                if kind == "log":
                    self._log(payload)
                elif kind == "progress":
                    done, total, phase = payload
                    self._progress(done, total, phase)
                elif kind == "login_ok":
                    self._refresh_account()
                    self._close_login_dialogs()
                    self._refresh_games()
                elif kind == "login_fail":
                    self._close_login_dialogs()
                    messagebox.showerror("登录失败", payload, parent=self)
                elif kind == "games":
                    self.games = payload
                    self._filter_games()
                elif kind == "snapshots":
                    self._fill_snapshots(payload)
                elif kind == "snapshot_meta":
                    manifest, files, size_text, slots = payload
                    if self.snap_tree.exists(manifest):
                        self.snap_tree.set(manifest, "files", str(files))
                        self.snap_tree.set(manifest, "size", size_text)
                        self.snap_tree.set(manifest, "slots", slots)
                elif kind == "restore_done":
                    self._set_busy(False)
                    self._set_status(payload.get("status", "还原完成"), GREEN)
                    messagebox.showinfo("还原完成", payload.get("message", ""), parent=self)
                elif kind == "busy":
                    self._set_busy(payload)
                elif kind == "done":
                    self._set_busy(False)
                    self._set_status(payload, GREEN)
                elif kind == "error":
                    self._set_busy(False)
                    self._set_status(payload, RED)
                    self._log("错误：" + payload)
        except queue.Empty:
            pass
        self.after(120, self._poll)

    # ------------------------------------------------------------ 账号

    def _refresh_account(self):
        if self.saver.is_logged_in:
            self.account_label.configure(text=f"已登录：{self.saver.display_name}", fg=GREEN)
            self.login_btn.state(["disabled"])
            self.logout_btn.state(["!disabled"])
        else:
            self.account_label.configure(text="未登录", fg=DIM)
            self.login_btn.state(["!disabled"])
            self.logout_btn.state(["disabled"])

    def _startup_login(self):
        def work():
            self.queue.put(("busy", True))
            try:
                if self.saver.resume_session():
                    self.queue.put(("login_ok", None))
                else:
                    self.queue.put(("done", "未登录，点右上角「登录 Epic」"))
            except Exception as exc:  # noqa: BLE001
                self.queue.put(("error", f"启动检查失败：{exc}"))

        threading.Thread(target=work, daemon=True).start()

    def _open_login(self):
        LoginDialog(self)

    def _close_login_dialogs(self):
        for child in self.winfo_children():
            if isinstance(child, LoginDialog):
                child.destroy()

    def _logout(self):
        self.saver.logout()
        self.games = []
        self.snapshots = []
        self.games_tree.delete(*self.games_tree.get_children())
        self.snap_tree.delete(*self.snap_tree.get_children())
        self.target_combo.configure(values=[])
        self.target_var.set("")
        self._refresh_account()
        self._set_status("已退出登录", DIM)

    # ------------------------------------------------------------ 游戏库

    def _refresh_games(self):
        if self.busy or not self.saver.is_logged_in:
            return
        self._set_busy(True)
        self._set_status("正在读取游戏库…")

        def work():
            try:
                games = self.saver.list_games()
                self.queue.put(("games", games))
                self.queue.put(("done", f"游戏库加载完成，共 {len(games)} 个支持云存档"))
            except Exception as exc:  # noqa: BLE001
                self.queue.put(("error", f"读取游戏库失败：{exc}"))

        threading.Thread(target=work, daemon=True).start()

    def _filter_games(self):
        keyword = self.search_var.get().strip().lower()
        self.games_tree.delete(*self.games_tree.get_children())
        shown = 0
        for game in self.games:
            if keyword and keyword not in game.title.lower() and keyword not in game.app_name.lower():
                continue
            self.games_tree.insert("", "end", iid=game.app_name, values=(game.title, game.app_name))
            shown += 1
        self.snapshot_hint.configure(text=f"{shown} 个游戏")

    def _on_game_selected(self):
        if self.demo:
            return
        selection = self.games_tree.selection()
        if not selection or self.busy:
            return
        app_name = selection[0]
        self.current_app = app_name
        self.snap_tree.delete(*self.snap_tree.get_children())
        self.snapshots = []
        self.snapshot_hint.configure(text="正在读取快照…")
        self._set_status("正在读取云端快照…")

        game = next((g for g in self.games if g.app_name == app_name), None)
        if game is not None:
            self._fill_locations(self.saver.list_save_locations(game))

        def work():
            try:
                snaps = self.saver.list_snapshots(app_name)
                self.queue.put(("snapshots", snaps))
                self._set_status(f"该游戏云端有 {len(snaps)} 份快照", DIM)
            except Exception as exc:  # noqa: BLE001
                self.queue.put(("error", f"读取快照失败：{exc}"))

        threading.Thread(target=work, daemon=True).start()

    def _fill_locations(self, locations: list[SaveLocation]):
        values = [loc.label for loc in locations]
        self.location_map = {loc.label: loc.path for loc in locations}
        self.target_combo.configure(values=values)
        if values:
            self.target_var.set(values[0])
        for loc in locations:
            self._log(f"本机存档目录：[{loc.kind}] {loc.path}")
        if locations:
            self.restore_hint.configure(
                text="还原前请先关闭 Epic 启动器的云存档同步；工具会自动把现有存档备份成 zip。"
            )
        else:
            self.restore_hint.configure(
                text="没找到本机存档目录（游戏可能还没运行过），可以点「浏览」手动指定，"
                     "或还原到 Steam/其他账号的目录。"
            )

    def _fill_snapshots(self, snaps: list[Snapshot]):
        self.snapshots = snaps
        self.snap_tree.delete(*self.snap_tree.get_children())
        for snap in snaps:
            self.snap_tree.insert(
                "", "end", iid=snap.manifest,
                values=(
                    human_time(snap.when),
                    str(snap.file_count) if snap.analysed else "…",
                    snap.size_text if snap.analysed else "…",
                    snap.slots if snap.analysed else "…",
                    snap.when.astimezone().strftime("%m.%d %H:%M"),
                ),
            )
        self.snapshot_hint.configure(text=f"{len(snaps)} 份快照，最新的在最上面")
        if snaps:
            self._set_status(f"最新快照：{human_time(snaps[0].when)}", DIM)
            self._analyse_async(list(snaps))

    def _analyse_async(self, snaps: list[Snapshot]):
        """后台拉 manifest 算文件数 / 体积 / 槽位，不阻塞界面。"""
        if self.demo or not self.current_app:
            return
        app_name = self.current_app

        def work():
            for snap in snaps:
                try:
                    info = self.saver.analyse_snapshot(app_name, snap)
                    self.queue.put(("snapshot_meta", (
                        snap.manifest, info.file_count, info.size_text, info.slots,
                    )))
                except Exception as exc:  # noqa: BLE001
                    self.queue.put(("log", f"分析快照 {snap.stamp} 失败：{exc}"))
                    self.queue.put(("snapshot_meta", (snap.manifest, "?", "?", "—")))

        threading.Thread(target=work, daemon=True).start()

    # ------------------------------------------------------------ 导出

    def _choose_dir(self):
        path = filedialog.askdirectory(initialdir=self.dest_var.get(), parent=self)
        if path:
            self.dest_var.set(path)

    def _open_dest(self):
        path = self.dest_var.get()
        os.makedirs(path, exist_ok=True)
        os.startfile(path)  # noqa: S606

    def _set_busy(self, value: bool):
        self.busy = value
        state = ["disabled"] if value else ["!disabled"]
        for btn in (self.refresh_btn, self.export_btn, self.export_all_btn,
                    self.restore_btn, self.login_btn):
            btn.state(state)
        if not value:
            self._refresh_account()
            self.progress.configure(value=0)

    def _workers(self) -> int:
        try:
            return max(1, int(self.workers_var.get()))
        except (TypeError, ValueError):
            return DEFAULT_WORKERS

    def _export(self, selected_only: bool):
        if self.busy:
            return
        selection = self.games_tree.selection()
        if not selection:
            messagebox.showinfo("提示", "先在左边选一个游戏", parent=self)
            return
        app_name = selection[0]
        title = self.games_tree.item(app_name, "values")[0]

        if selected_only:
            wanted = set(self.snap_tree.selection())
            targets = [s for s in self.snapshots if s.manifest in wanted]
            if not targets:
                messagebox.showinfo("提示", "先在右边选要导出的快照", parent=self)
                return
        else:
            targets = list(self.snapshots)
            if not targets:
                messagebox.showinfo("提示", "这个游戏云端没有快照", parent=self)
                return

        base = os.path.join(self.dest_var.get(), self._safe_name(title))
        make_zip = bool(self.zip_var.get())
        workers = self._workers()
        self._set_busy(True)
        self._log(f"开始导出 {title}，共 {len(targets)} 份快照（{workers} 线程）")

        def work():
            try:
                results = []
                for idx, snap in enumerate(targets, 1):
                    dest = os.path.join(base, snap.stamp)
                    self.queue.put(("log", f"[{idx}/{len(targets)}] {snap.stamp}"))
                    result = self.saver.export_snapshot(
                        app_name, snap.manifest, dest,
                        on_progress=lambda d, t, ph: self.queue.put(("progress", (d, t, ph))),
                        make_zip=make_zip,
                        workers=workers,
                    )
                    results.append(result)
                self.queue.put(("done", f"导出完成，共 {len(results)} 份 → {base}"))
                self.queue.put(("log", f"全部完成：{base}"))
            except Exception as exc:  # noqa: BLE001
                self.queue.put(("error", f"导出失败：{exc}"))

        threading.Thread(target=work, daemon=True).start()

    # ------------------------------------------------------------ 还原

    def _choose_target(self):
        path = filedialog.askdirectory(parent=self)
        if not path:
            return
        values = list(self.target_combo.cget("values"))
        if path not in values:
            values.append(path)
            self.target_combo.configure(values=values)
        self.target_var.set(path)

    def _restore(self):
        if self.busy:
            return
        selection = self.games_tree.selection()
        if not selection:
            messagebox.showinfo("提示", "先在左边选一个游戏", parent=self)
            return
        app_name = selection[0]
        title = self.games_tree.item(app_name, "values")[0]

        wanted = set(self.snap_tree.selection())
        targets = [s for s in self.snapshots if s.manifest in wanted]
        if len(targets) != 1:
            messagebox.showinfo("提示", "请在右边选中一份要还原的快照", parent=self)
            return
        snap = targets[0]

        label = self.target_var.get().strip()
        target_dir = self.location_map.get(label, label)
        if not target_dir:
            messagebox.showinfo("提示", "先选一个还原目录，或者点「浏览」手动指定", parent=self)
            return

        ok = messagebox.askyesno(
            "确认还原",
            f"游戏：{title}\n快照：{snap.stamp}\n还原到：\n{target_dir}\n\n"
            "还原前请先关闭 Epic 启动器的云存档同步，否则可能被旧云档覆盖。\n"
            "工具会自动把现有存档打包备份。\n\n继续？",
            parent=self,
        )
        if not ok:
            return

        workers = self._workers()
        self._set_busy(True)
        self._log(f"开始还原 {title} → {target_dir}")
        self._set_status("正在还原…")

        def work():
            try:
                result = self.saver.restore_snapshot(
                    app_name, snap.manifest, target_dir,
                    backup=True,
                    on_progress=lambda d, t, ph: self.queue.put(("progress", (d, t, ph))),
                    workers=workers,
                )
                lines = [f"已还原 {result.files} 个文件到：", result.target]
                if result.backup:
                    lines += ["", "原存档已备份到：", result.backup]
                lines += ["", "回到游戏确认能读档后，再把云存档同步打开。"]
                self.queue.put(("restore_done", {
                    "status": "还原完成",
                    "message": "\n".join(lines),
                }))
            except Exception as exc:  # noqa: BLE001
                self.queue.put(("error", f"还原失败：{exc}"))

        threading.Thread(target=work, daemon=True).start()

    @staticmethod
    def _safe_name(name: str) -> str:
        bad = '<>:"/\\|?*'
        return "".join("_" if ch in bad else ch for ch in name).strip() or "game"

    # ------------------------------------------------------------ 演示 / 自检

    def _load_demo(self):
        self.games = [
            GameEntry("Boga", "DEATH STRANDING", "f4a904fc",
                      r"{appdata}/../locallow/KojimaProductions/DeathStranding/{EpicID}/"),
            GameEntry("Control", "Control Ultimate Edition", "9c9d1f2a",
                      r"{appdata}/Remedy/Control/{EpicID}/"),
            GameEntry("Eider", "HITMAN 3", "6a4b8c2d", r"{appdata}/IO Interactive/HITMAN3/"),
        ]
        self.search_var.set("")
        self._filter_games()
        self.account_label.configure(text="已登录：demo-user", fg=GREEN)
        self.games_tree.selection_set("Boga")

        demo_snaps = [
            Snapshot("2026.08.23-05.26.03.manifest", datetime(2026, 8, 23, 5, 27),
                     file_count=51, size=10_013_412, slots="手动3 · 自动23 · 快速23", analysed=True),
            Snapshot("2026.08.22-13.22.25.manifest", datetime(2026, 8, 22, 13, 23),
                     file_count=51, size=10_012_880, slots="手动3 · 自动23 · 快速23", analysed=True),
            Snapshot("2026.08.22-10.38.31.manifest", datetime(2026, 8, 22, 10, 40),
                     file_count=50, size=9_345_120, slots="手动2 · 自动23 · 快速23", analysed=True),
        ]
        self._fill_snapshots(demo_snaps)
        self.snap_tree.selection_set("2026.08.23-05.26.03.manifest")
        self.current_app = "Boga"
        self.dest_var.set(r"D:\Epic云存档")
        self._fill_locations([
            SaveLocation(
                r"C:\Users\Demo\AppData\LocalLow\KojimaProductions\DeathStranding"
                r"\0123456789abcdef0123456789abcdef",
                "Epic 当前账号",
            ),
            SaveLocation(
                r"C:\Users\Demo\AppData\LocalLow\KojimaProductions\DeathStranding"
                r"\76561198000000001",
                "Steam 账号",
            ),
        ])
        self.progress.configure(value=62)
        self._set_status("下载分块 41/66  (62%)")
        for line in (
            "已登录：demo-user",
            "游戏库加载完成，共 6 个支持云存档",
            "该游戏云端有 3 份快照",
            "分析快照：51 个文件 / 9.5 MB / 手动3 · 自动23 · 快速23",
            "开始导出 DEATH STRANDING，共 3 份快照（4 线程）",
            "开始下载 11 个分块（4 线程）…",
            "下载分块 6/11",
        ):
            self._log(line)

    def _selftest_grab(self):
        try:
            from PIL import ImageGrab

            dialog = next((c for c in self.winfo_children()
                           if isinstance(c, LoginDialog) and c.winfo_ismapped()), None)
            self.lift()
            self.attributes("-topmost", True)
            self.update()
            if dialog is not None:
                dialog.lift()
                dialog.attributes("-topmost", True)
                dialog.update()
            time.sleep(0.5)
            self.update()

            x1, y1 = self.winfo_rootx(), self.winfo_rooty()
            x2, y2 = x1 + self.winfo_width(), y1 + self.winfo_height()
            if dialog is not None:
                cx, cy = dialog.winfo_rootx(), dialog.winfo_rooty()
                x1, y1 = min(x1, cx), min(y1, cy)
                x2 = max(x2, cx + dialog.winfo_width())
                y2 = max(y2, cy + dialog.winfo_height())
            img = ImageGrab.grab(bbox=(x1, y1, x2, y2))
            name = "preview-login.png" if dialog is not None else "preview.png"
            base = getattr(sys, "_MEIPASS", None) or os.path.dirname(os.path.abspath(__file__))
            out = os.path.join(os.path.dirname(base) if getattr(sys, "_MEIPASS", None) else base, name)
            img.save(out)
            _say(f"screenshot -> {out} ({img.size[0]}x{img.size[1]})")
        except Exception as exc:  # noqa: BLE001
            _say("screenshot failed: " + repr(exc))
        finally:
            self.destroy()


def _cli_log(msg: str) -> None:
    _say(msg)
    try:
        with open(os.path.join(app_data_dir(), "cli.log"), "a", encoding="utf-8") as fh:
            fh.write(f"[{datetime.now():%H:%M:%S}] {msg}\n")
    except Exception:  # noqa: BLE001
        pass


def _find_game(saver: CloudSaver, app_name: str) -> GameEntry | None:
    games = saver.list_games()
    key = app_name.lower()
    return next((g for g in games if g.app_name.lower() == key or key in g.title.lower()), None)


def cli_export(app_name: str, dest_base: str) -> int:
    """命令行导出：最新一份快照（调试 / 自动化用）。"""
    saver = CloudSaver(log=_cli_log)
    if not saver.resume_session():
        _say("未登录：请先运行图形界面登录一次")
        return 2
    entry = _find_game(saver, app_name)
    if not entry:
        _say(f"找不到游戏：{app_name}")
        return 3
    snaps = saver.list_snapshots(entry.app_name)
    if not snaps:
        _say("云端没有快照")
        return 4
    dest = os.path.join(dest_base, App._safe_name(entry.title), snaps[0].stamp)
    _say(f"导出 {entry.title} 最新快照 -> {dest}")
    out = saver.export_snapshot(
        entry.app_name, snaps[0].manifest, dest,
        on_progress=lambda d, t, ph: _say(f"  {ph}"),
        make_zip=True,
    )
    _say(f"完成：{out.path}（{out.files} 个文件）")
    return 0


def cli_restore(app_name: str, target_dir: str) -> int:
    """命令行还原：最新快照 → 指定目录（会先备份现有存档）。"""
    saver = CloudSaver(log=_cli_log)
    if not saver.resume_session():
        _say("未登录：请先运行图形界面登录一次")
        return 2
    entry = _find_game(saver, app_name)
    if not entry:
        _say(f"找不到游戏：{app_name}")
        return 3
    snaps = saver.list_snapshots(entry.app_name)
    if not snaps:
        _say("云端没有快照")
        return 4
    _say(f"还原 {entry.title} 最新快照 -> {target_dir}")
    result = saver.restore_snapshot(
        entry.app_name, snaps[0].manifest, target_dir, backup=True,
        on_progress=lambda d, t, ph: _say(f"  {ph}"),
    )
    _say(f"完成：{result.files} 个文件 → {result.target}")
    if result.backup:
        _say(f"原存档备份：{result.backup}")
    return 0


def main():
    _install_crash_hooks()
    if "--cli-export" in sys.argv:
        idx = sys.argv.index("--cli-export")
        name = sys.argv[idx + 1] if len(sys.argv) > idx + 1 else "Boga"
        base = (sys.argv[idx + 2] if len(sys.argv) > idx + 2
                else os.path.join(os.path.expanduser("~"), "Documents", "Epic云存档"))
        try:
            sys.exit(cli_export(name, base))
        except Exception:  # noqa: BLE001
            import traceback

            _crash_log(f"\n=== {datetime.now():%Y-%m-%d %H:%M:%S} ===\n" + traceback.format_exc())
            raise
    if "--cli-restore" in sys.argv:
        idx = sys.argv.index("--cli-restore")
        name = sys.argv[idx + 1] if len(sys.argv) > idx + 1 else "Boga"
        target = sys.argv[idx + 2] if len(sys.argv) > idx + 2 else ""
        try:
            sys.exit(cli_restore(name, target))
        except Exception:  # noqa: BLE001
            import traceback

            _crash_log(f"\n=== {datetime.now():%Y-%m-%d %H:%M:%S} ===\n" + traceback.format_exc())
            raise
    demo = "--selftest" in sys.argv or "--selftest-login" in sys.argv
    login_shot = "--selftest-login" in sys.argv
    try:
        app = App(demo=demo, autoshot=demo, login_shot=login_shot)
        app.mainloop()
    except Exception as exc:  # noqa: BLE001
        import traceback

        detail = traceback.format_exc()
        _crash_log(f"\n=== {datetime.now():%Y-%m-%d %H:%M:%S} ===\n" + detail)
        _show_fatal(exc, detail)
        sys.exit(1)


def _show_fatal(exc: Exception, detail: str) -> None:
    """启动失败时给个说人话的弹窗，而不是 PyInstaller 的 traceback。"""
    try:
        import tkinter as tk
        from tkinter import messagebox

        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        messagebox.showerror(
            "SaveGrab 启动失败",
            f"{exc}\n\n"
            "常见原因：安全软件拦截程序写数据目录，或文件被占用。\n"
            "解决办法：\n"
            "1. 把整个文件夹换到 D 盘或桌面再运行\n"
            "2. 或用管理员身份运行一次\n"
            "3. 详细日志见同目录下的 error.log",
        )
        root.destroy()
    except Exception:  # noqa: BLE001
        pass


if __name__ == "__main__":
    main()
