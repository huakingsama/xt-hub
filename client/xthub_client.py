#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
XT-HUB 客户端  v1.0
==================
给使用者用的桌面程序：自动找车 → 检查在线 → 用独立窗口打开控制台。

· 不需要 Python、不需要命令行
· 记住上次连的地址；车换了 IP 会自动重新扫描
· 用 Edge/Chrome 的 --app 模式打开，没有地址栏，像原生程序
"""

import io
import json
import os
import shutil
import tempfile
import zipfile
import socket
import subprocess
import sys
import threading
import time
import urllib.request
import webbrowser

import tkinter as tk
from tkinter import ttk
from tkinter import messagebox
from tkinter import simpledialog

try:
    from PIL import Image, ImageTk
    HAVE_PIL = True
except Exception:
    HAVE_PIL = False

APP_NAME = "XT-HUB 客户端"
VER = "v1.7"   # 显示用
VERNUM = "1.7"  # 跟服务器比大小用
HUB_PORT = 8000
CAM_PORT = 8090     # 相机画面（MJPEG）
MAP_PORT = 8091     # 实时地图（PNG）
FUSE_PORT = 8093    # 雷达+深度融合（PNG）

# ---------------------------------------------------------------- 配置存储
def cfg_path():
    base = os.environ.get("APPDATA") or os.path.expanduser("~")
    d = os.path.join(base, "XTHubClient")
    try:
        os.makedirs(d, exist_ok=True)
    except Exception:
        d = os.path.expanduser("~")
    return os.path.join(d, "client.json")


def load_cfg():
    try:
        with open(cfg_path(), "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_cfg(d):
    try:
        with open(cfg_path(), "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


# ---------------------------------------------------------------- 网络探测
def local_prefixes():
    """本机所在 /24 网段"""
    out = set()
    try:
        import subprocess as sp
        if os.name == "nt":
            txt = sp.run(["powershell", "-NoProfile", "-Command",
                          "Get-NetIPAddress -AddressFamily IPv4 | "
                          "Select-Object -ExpandProperty IPAddress"],
                         capture_output=True, text=True, timeout=8).stdout
            for line in txt.splitlines():
                ip = line.strip()
                p = ip.split(".")
                if len(p) == 4 and not ip.startswith("127.") and not ip.startswith("169.254."):
                    out.add(".".join(p[:3]))
    except Exception:
        pass
    if not out:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("223.5.5.5", 80))
            ip = s.getsockname()[0]
            s.close()
            out.add(".".join(ip.split(".")[:3]))
        except Exception:
            pass
    return sorted(out)


def local_ips():
    """本机自己的 IPv4 地址集合（用来在列表里标注"本机"）"""
    out = set()
    try:
        import subprocess as sp
        if os.name == "nt":
            txt = sp.run(["powershell", "-NoProfile", "-Command",
                          "Get-NetIPAddress -AddressFamily IPv4 | "
                          "Select-Object -ExpandProperty IPAddress"],
                         capture_output=True, text=True, timeout=8).stdout
            for line in txt.splitlines():
                ip = line.strip()
                if ip.count(".") == 3 and not ip.startswith("169.254."):
                    out.add(ip)
    except Exception:
        pass
    return out


def probe(ip, port=HUB_PORT, timeout=0.35):
    s = socket.socket()
    s.settimeout(timeout)
    try:
        return s.connect_ex((ip, port)) == 0
    finally:
        s.close()


def health(ip, port=HUB_PORT, timeout=3):
    try:
        with urllib.request.urlopen("http://%s:%d/healthz" % (ip, port), timeout=timeout) as r:
            return r.read(200).decode("utf-8", "replace").strip()
    except Exception:
        return ""


def scan(prefixes, on_found=None):
    """并发探测 8000 端口"""
    found = []
    threads = []

    def worker(ip):
        if probe(ip):
            found.append(ip)
            if on_found:
                on_found(ip)

    for p in prefixes:
        for i in range(1, 255):
            ip = "%s.%d" % (p, i)
            t = threading.Thread(target=worker, args=(ip,), daemon=True)
            t.start()
            threads.append(t)
            if len(threads) >= 128:          # 分批，避免线程爆掉
                for x in threads:
                    x.join(timeout=0.6)
                threads = []
    for x in threads:
        x.join(timeout=0.6)
    return sorted(set(found))


# ---------------------------------------------------------------- 打开窗口
def browsers():
    cands = [
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    ]
    return [c for c in cands if os.path.exists(c)]


def open_console(url):
    """优先用 --app 打开，无地址栏，像独立软件"""
    for exe in browsers():
        try:
            subprocess.Popen([exe, "--app=%s" % url, "--window-size=1500,950"])
            return "app"
        except Exception:
            continue
    webbrowser.open(url)
    return "browser"


# ---------------------------------------------------------------- 界面
BG = "#0e1116"
FG = "#d7dde6"
DIM = "#7c8794"
ACC = "#3b82f6"
OK = "#22c55e"
BAD = "#ef4444"
WARN = "#eab308"



# ---------------------------------------------------------------- 自更新
def _vnum(v):
    """把 '1.10' 这种版本号变成可比较的元组"""
    try:
        return tuple(int(x) for x in str(v).strip().lstrip("vV").split("."))
    except Exception:
        return (0,)


def remote_version(ip, port=HUB_PORT, timeout=4):
    """问服务器：最新客户端版本是多少"""
    url = "http://%s:%d/api/client/version" % (ip, port)
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8", "replace"))
    except Exception:
        return None


def _fmt(n):
    if n >= 1048576:
        return "%.1f MB" % (n / 1048576.0)
    if n >= 1024:
        return "%.0f KB" % (n / 1024.0)
    return "%d B" % n


def download(url, dst, on_progress=None, tries=4):
    """带断点续传的下载。dst.part 存在就接着下，网络抖动自动重试。"""
    part = dst + ".part"
    for attempt in range(1, tries + 1):
        have = os.path.getsize(part) if os.path.exists(part) else 0
        req = urllib.request.Request(url)
        if have:
            req.add_header("Range", "bytes=%d-" % have)
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                code = getattr(r, "status", 200)
                if code == 200 and have:
                    have = 0                      # 服务器不支持续传 → 重头来
                    open(part, "wb").close()
                total = int(r.headers.get("Content-Length") or 0) + have
                mode = "ab" if have else "wb"
                got = have
                with open(part, mode) as f:
                    while True:
                        chunk = r.read(65536)
                        if not chunk:
                            break
                        f.write(chunk)
                        got += len(chunk)
                        if on_progress:
                            on_progress(got, total)
            if total and got < total:
                raise IOError("连接中断（%s / %s）" % (_fmt(got), _fmt(total)))
            if os.path.exists(dst):
                os.remove(dst)
            os.replace(part, dst)
            return got
        except Exception as e:
            if attempt >= tries:
                raise
            time.sleep(1.2 * attempt)             # 退避后再试，接着下
    return 0


UPDATE_BAT = r"""@echo off
chcp 65001 >nul
set "SRC=%~1"
set "DST=%~2"
set "EXE=%~3"
:wait
tasklist /FI "IMAGENAME eq XTHUBClient.exe" 2>nul | find /i "XTHUBClient.exe" >nul
if not errorlevel 1 (
  ping -n 2 127.0.0.1 >nul
  goto wait
)
robocopy "%SRC%" "%DST%" /E /NFL /NDL /NJH /NJS /NP >nul
start "" "%EXE%"
ping -n 3 127.0.0.1 >nul
del "%~f0" 2>nul
"""


def apply_update(base_url, info, on_progress=None, on_phase=None):
    """下载 → 解压 → 交给 update.bat 替换 → 本进程退出"""
    if not getattr(sys, "frozen", False):
        return "当前是源码方式运行，不能自更新（只有 exe 可以）"
    if not info.get("zip"):
        return "服务器上没有放升级包（dist/client.zip）"
    td = tempfile.mkdtemp(prefix="xthub_upd_")
    zp = os.path.join(td, "client.zip")
    def phase(t):
        if on_phase:
            on_phase(t)

    phase("正在下载安装包…")
    download(base_url.rstrip("/") + info["zip"], zp, on_progress)
    phase("正在解压…")
    raw = os.path.join(td, "raw")
    with zipfile.ZipFile(zp) as z:
        z.extractall(raw)
    # 兼容两种打包：根目录直接是文件，或多一层 "XT-HUB 客户端/"
    src = raw
    inner = [n for n in os.listdir(raw) if not n.startswith("__MACOSX")]
    if len(inner) == 1 and os.path.isdir(os.path.join(raw, inner[0])):
        src = os.path.join(raw, inner[0])
    if not os.path.isfile(os.path.join(src, "XTHUBClient.exe")):
        return "升级包里没找到 XTHUBClient.exe，包可能打错了"

    phase("正在替换程序…")
    target = os.path.dirname(os.path.abspath(sys.executable))
    bat = os.path.join(td, "update.bat")
    with open(bat, "w", encoding="ascii", newline="\r\n") as f:
        f.write(UPDATE_BAT)
    subprocess.Popen(["cmd", "/c", bat, src, target, os.path.abspath(sys.executable)],
                     creationflags=getattr(subprocess, "CREATE_NEW_CONSOLE", 0))
    return None   # None = 成功，调用方随即退出


class DownloadDialog(tk.Toplevel):
    """更新时的进度窗口：下载百分比 / 速度 / 剩余时间 / 当前阶段。"""

    def __init__(self, master, ver_from, ver_to, size):
        tk.Toplevel.__init__(self, master)
        self.title("正在更新 XT-HUB 客户端")
        self.configure(bg=PANEL)
        self.resizable(False, False)
        self.protocol("WM_DELETE_WINDOW", lambda: None)   # 下载中不许关
        self.t0 = time.time()
        self.last_t = self.t0
        self.last_n = 0
        self.speed = 0.0

        tk.Label(self, text="发现新版本 %s → %s" % (ver_from, ver_to), bg=PANEL, fg=FG,
                 font=("Microsoft YaHei UI", 11, "bold")).pack(anchor="w", padx=18, pady=(16, 4))
        self.lbl = tk.Label(self, text="准备下载…", bg=PANEL, fg=DIM,
                            font=("Microsoft YaHei UI", 9))
        self.lbl.pack(anchor="w", padx=18)
        self.bar = ttk.Progressbar(self, length=420, mode="determinate", maximum=100)
        self.bar.pack(padx=18, pady=10, fill="x")
        self.sub = tk.Label(self, text="共 %.1f MB" % (size / 1048576.0), bg=PANEL, fg=DIM,
                            font=("Consolas", 9))
        self.sub.pack(anchor="w", padx=18, pady=(0, 16))
        self.update_idletasks()
        self.geometry("+%d+%d" % (master.winfo_rootx() + 60, master.winfo_rooty() + 60))

    def progress(self, got, total):
        now = time.time()
        dt = now - self.last_t
        if dt >= 0.4:
            self.speed = (got - self.last_n) / dt
            self.last_t, self.last_n = now, got
        pct = int(got * 100 / total) if total else 0
        left = ""
        if self.speed > 1024 and total:
            secs = int((total - got) / self.speed)
            left = "  剩 %d:%02d" % (secs // 60, secs % 60)
        self.bar["value"] = pct
        self.lbl.config(text="正在下载  %d%%   %s / %s" % (pct, _fmt(got), _fmt(total)))
        self.sub.config(text="%s/s%s" % (_fmt(self.speed), left))

    def phase(self, text):
        self.bar.config(mode="indeterminate")
        self.bar.start(12)
        self.lbl.config(text=text)
        self.sub.config(text="这一步可能需要几十秒，请不要关闭窗口")

    def close(self):
        try:
            self.bar.stop()
            self.destroy()
        except Exception:
            pass


class VideoWindow(tk.Toplevel):
    """客户端内置画面窗口：彩色 / 深度 / 融合 / 地图，四路切换。"""

    CHANNELS = [
        ("rgb",   "彩色画面", CAM_PORT,  "mjpeg", "/rgb"),
        ("depth", "深度画面", CAM_PORT,  "mjpeg", "/depth"),
        ("fuse",  "雷达+深度融合", FUSE_PORT, "png", "/fuse.png"),
        ("map",   "实时地图", MAP_PORT,  "png", "/map.png"),
    ]

    def __init__(self, master, ip):
        tk.Toplevel.__init__(self, master)
        self.ip = ip
        self.stop_flag = False
        self.cur = None
        self._img = None

        self.title("XT-HUB 画面 · %s" % ip)
        self.configure(bg=BG)
        self.geometry("860x680")
        self.minsize(560, 420)

        bar = tk.Frame(self, bg=BG)
        bar.pack(fill="x", padx=10, pady=(10, 4))
        for key, label, _p, _k, _path in self.CHANNELS:
            b = tk.Button(bar, text=label, command=lambda k=key: self.play(k),
                          bg="#1f2937", fg=FG, bd=0, relief="flat",
                          activebackground="#374151", activeforeground="white",
                          padx=12, pady=5, cursor="hand2",
                          font=("Microsoft YaHei UI", 9))
            b.pack(side="left", padx=(0, 6))
        tk.Button(bar, text="关闭", command=self.close,
                  bg="#374151", fg=FG, bd=0, relief="flat",
                  activebackground="#4b5563", activeforeground="white",
                  padx=12, pady=5, cursor="hand2",
                  font=("Microsoft YaHei UI", 9)).pack(side="right")

        self.lbl = tk.Label(self, bg="#0b0f14", fg=DIM,
                            text="正在连接画面 …",
                            font=("Microsoft YaHei UI", 11))
        self.lbl.pack(fill="both", expand=True, padx=10, pady=(0, 10))

        self.protocol("WM_DELETE_WINDOW", self.close)
        if not HAVE_PIL:
            self.lbl.config(text="本机缺少图片组件（Pillow），无法显示画面")
            return
        self.play("rgb")

    # ---------------- 切换通道
    def play(self, key):
        self.stop_flag = True          # 让上一个线程退出
        time.sleep(0.05)
        self.stop_flag = False
        self.cur = key
        self.lbl.config(text="连接中 …", image="")
        threading.Thread(target=self._worker, args=(key,), daemon=True).start()

    def _chan(self, key):
        for c in self.CHANNELS:
            if c[0] == key:
                return c
        return self.CHANNELS[0]

    def _worker(self, key):
        _k, label, port, kind, path = self._chan(key)
        url = "http://%s:%d%s" % (self.ip, port, path)
        while not self.stop_flag:
            try:
                if kind == "mjpeg":
                    self._stream(url)
                else:
                    self._poll(url)
            except Exception as e:
                self._text("%s\n\n连不上：%s\n（车上对应服务可能没启动，控制台点『全部启动』）"
                           % (label, e))
                time.sleep(2)

    # ---------------- MJPEG 拉流（只画最新一帧，永不积压）
    def _stream(self, url):
        resp = urllib.request.urlopen(url, timeout=4)
        buf = b""
        dropped = 0
        while not self.stop_flag:
            chunk = resp.read(16384)
            if not chunk:
                buf = b""
                time.sleep(0.2)
                continue
            buf += chunk
            # 把缓冲区里所有完整帧切出来，只保留最后一帧 → 延迟恒定，不会越看越慢
            frames = []
            while True:
                i = buf.find(b"\xff\xd8")
                if i < 0:
                    buf = b""
                    break
                j = buf.find(b"\xff\xd9", i + 2)
                if j < i:
                    buf = buf[i:]          # 半帧，留到下次
                    break
                frames.append(buf[i:j + 2])
                buf = buf[j + 2:]
            if not frames:
                continue
            dropped += max(0, len(frames) - 1)
            self._draw(frames[-1])

    # ---------------- PNG 轮询
    def _poll(self, url):
        while not self.stop_flag:
            sep = "&" if "?" in url else "?"
            data = urllib.request.urlopen(url + sep + "t=%d" % int(time.time() * 1000),
                                          timeout=6).read()
            if data:
                self._draw(data)
            time.sleep(0.25)

    def _draw(self, raw):
        try:
            im = Image.open(io.BytesIO(raw))
            im.load()
        except Exception:
            return
        try:
            box = self._box
        except AttributeError:
            box = None
        if box is None or time.time() - getattr(self, "_box_t", 0) > 2:
            box = (max(self.winfo_width() - 24, 320), max(self.winfo_height() - 70, 240))
            self._box, self._box_t = box, time.time()
        if im.size > box:
            im.thumbnail(box)
        try:
            photo = ImageTk.PhotoImage(im, master=self)
        except Exception:
            return
        self._img = photo
        self.after(0, lambda: (self.lbl.config(image=photo, text=""),))

    def _text(self, msg):
        self.after(0, lambda: self.lbl.config(text=msg, image=""))

    def close(self):
        self.stop_flag = True
        self.destroy()


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.cfg = load_cfg()
        self.hits = []
        self.sel = None
        self.scanning = False

        self.title("%s %s" % (APP_NAME, VER))
        self.configure(bg=BG)
        self.geometry("560x420")
        self.minsize(520, 380)
        try:
            self.iconbitmap(default="")
        except Exception:
            pass

        self._build()
        self.after(200, self.start_scan)

    # ---------------- 布局
    def _build(self):
        top = tk.Frame(self, bg=BG)
        top.pack(fill="x", padx=18, pady=(16, 6))

        tk.Label(top, text="XT-HUB", bg=BG, fg=FG,
                 font=("Segoe UI", 18, "bold")).pack(side="left")
        tk.Label(top, text="机器人多人控制台 · 客户端", bg=BG, fg=DIM,
                 font=("Segoe UI", 9)).pack(side="left", padx=(8, 0), pady=(6, 0))
        tk.Label(top, text=VER, bg=BG, fg=DIM,
                 font=("Segoe UI", 9)).pack(side="right", pady=(8, 0))

        # 状态条
        self.lbl_state = tk.Label(self, text="正在查找车 …", bg=BG, fg=WARN,
                                  font=("Microsoft YaHei UI", 11), anchor="w")
        self.lbl_state.pack(fill="x", padx=18, pady=(4, 8))

        # 找到的列表
        box = tk.Frame(self, bg="#151a22")
        box.pack(fill="both", expand=True, padx=18)
        self.lst = tk.Listbox(box, bg="#151a22", fg=FG, bd=0, highlightthickness=0,
                              selectbackground=ACC, selectforeground="white",
                              font=("Consolas", 10), activestyle="none")
        self.lst.pack(fill="both", expand=True, padx=6, pady=6)
        self.lst.bind("<<ListboxSelect>>", self.on_pick)
        self.lst.bind("<Double-Button-1>", lambda e: self.enter())

        # 底部按钮
        bar = tk.Frame(self, bg=BG)
        bar.pack(fill="x", padx=18, pady=12)

        self.btn_scan = tk.Button(bar, text="重新查找", command=self.start_scan,
                                  bg="#1f2937", fg=FG, bd=0, relief="flat",
                                  activebackground="#374151", activeforeground="white",
                                  padx=14, pady=6, cursor="hand2",
                                  font=("Microsoft YaHei UI", 10))
        self.btn_scan.pack(side="left")

        self.btn_go = tk.Button(bar, text="进入控制台  ▶", command=self.enter,
                                bg=ACC, fg="white", bd=0, relief="flat",
                                activebackground="#2563eb", activeforeground="white",
                                padx=18, pady=6, cursor="hand2",
                                font=("Microsoft YaHei UI", 10, "bold"))
        self.btn_go.pack(side="right")

        self.btn_video = tk.Button(bar, text="看画面 ▶", command=self.open_video,
                                   bg="#0ea5e9", fg="white", bd=0, relief="flat",
                                   activebackground="#0284c7", activeforeground="white",
                                   padx=14, pady=6, cursor="hand2",
                                   font=("Microsoft YaHei UI", 10, "bold"))
        self.btn_video.pack(side="right", padx=(0, 8))

        self.btn_upd = tk.Button(bar, text="检查更新", command=self.check_update,
                                 bg="#1f2937", fg=FG, bd=0, relief="flat",
                                 activebackground="#374151", activeforeground="white",
                                 padx=12, pady=6, cursor="hand2",
                                 font=("Microsoft YaHei UI", 10))
        self.btn_upd.pack(side="right", padx=(0, 8))

        self.btn_manual = tk.Button(bar, text="手动输地址", command=self.manual_ip,
                                    bg="#1f2937", fg=FG, bd=0, relief="flat",
                                    activebackground="#374151", activeforeground="white",
                                    padx=10, pady=6, cursor="hand2",
                                    font=("Microsoft YaHei UI", 9))
        self.btn_manual.pack(side="left", padx=(8, 0))

        self.lbl_tip = tk.Label(self, text="提示：双击列表也能进入；车没开机时这里会显示找不到",
                                bg=BG, fg=DIM, font=("Microsoft YaHei UI", 8))
        self.lbl_tip.pack(fill="x", padx=18, pady=(0, 12))

    # ---------------- 扫描
    def start_scan(self):
        if self.scanning:
            return
        self.scanning = True
        self.hits = []
        self.sel = None
        self.lst.delete(0, "end")
        self.btn_scan.config(state="disabled", text="查找中…")
        self.lbl_state.config(text="正在查找车 …（约 2 秒）", fg=WARN)
        threading.Thread(target=self._scan_thread, daemon=True).start()

    def _scan_thread(self):
        prefixes = local_prefixes()
        # 先试上次成功过的地址
        last = self.cfg.get("last_ip")
        if last and probe(last, self.cfg.get("last_port", HUB_PORT)):
            self.after(0, lambda: self._add(last, prefer=True))
        found = scan(prefixes)
        for ip in found:
            if ip != last:
                self.after(0, lambda i=ip: self._add(i))
        self.after(0, self._scan_done)

    def _add(self, ip, prefer=False):
        if ip in self.hits:
            return
        self.hits.append(ip)
        h = health(ip)
        tag = "[本机] " if ip in local_ips() else ""
        label = "%s%-16s  %s" % (tag, ip, h if h else "(无响应)")
        self.lst.insert("end", label)
        reachable = bool(h)
        if (self.sel is None and reachable) or (prefer and reachable):
            self.sel = ip
            idx = self.lst.size() - 1
            self.lst.selection_clear(0, "end")
            self.lst.selection_set(idx)
            self.lbl_state.config(text="找到 XT-HUB：%s" % ip, fg=OK)

    def _scan_done(self):
        self.scanning = False
        if self.sel:
            self.after(600, lambda: self.check_update(silent=True))
        self.btn_scan.config(state="normal", text="重新查找")
        if not self.hits:
            self.lbl_state.config(
                text="没有找到车 · 请确认车已通电并连同一个 Wi-Fi", fg=BAD)
            self.lbl_tip.config(
                text="找不到时：①车屏幕亮不亮 ②车的 Wi-Fi 连上没 ③和你在同一个路由吗")

    # ---------------- 交互
    def on_pick(self, _evt=None):
        s = self.lst.curselection()
        if not s:
            return
        self.sel = self.hits[s[0]]
        h = health(self.sel)
        if not h.startswith("ok"):
            self.lbl_state.config(
                text="已选：%s（无响应，这台没跑服务）" % self.sel, fg=BAD)
            return
        if self.sel in local_ips():
            self.lbl_state.config(
                text="已选：%s（这台电脑自己，没有真实画面）" % self.sel, fg=WARN)
        else:
            self.lbl_state.config(text="已选：%s" % self.sel, fg=OK)

    def manual_ip(self):
        """手动输入地址：适合跨网段/自动扫描扫不到的情况"""
        d = simpledialog.askstring(
            APP_NAME, "输入服务器地址（例如 10.35.186.232 或 10.35.186.232:8000）：",
            parent=self)
        if not d:
            return
        d = d.strip().replace("http://", "").replace("https://", "").rstrip("/")
        ip = d.split(":")[0]
        port = HUB_PORT
        if ":" in d:
            try:
                port = int(d.split(":")[1])
            except Exception:
                port = HUB_PORT
        h = health(ip, port)
        if not h.startswith("ok"):
            messagebox.showwarning(APP_NAME,
                                   "连不上 %s:%d\n\n请确认：\n"
                                   "· 对方电脑开着并且服务器在跑\n"
                                   "· 你和他在同一个网络\n"
                                   "· 对方防火墙放行了 %d 端口" % (ip, port, port))
            return
        self.cfg["last_ip"] = ip
        self.cfg["last_port"] = port
        save_cfg(self.cfg)
        self._add(ip, prefer=True)
        self.lbl_state.config(text="已连接：%s:%d" % (ip, port), fg=OK)
        self.check_update(silent=True)

    def check_update(self, silent=False):
        if not self.sel:
            if not silent:
                messagebox.showinfo(APP_NAME, "先找到一台 XT-HUB 才能检查更新。")
            return
        ip = self.sel
        h = health(ip)
        if not h.startswith("ok"):
            if not silent:
                messagebox.showwarning(
                    APP_NAME,
                    "连不上这台服务器：%s\n\n列表里那一条显示「无响应」，说明这台机器上\n"
                    "没有在跑 XT-HUB（可能是别人的电脑，或者是旧记录）。\n\n"
                    "请选一条显示 ok 的地址再试。" % ip)
            return
        info = remote_version(ip)
        if not info or not info.get("version"):
            if not silent:
                messagebox.showwarning(APP_NAME,
                                       "这台服务器在跑，但没有版本查询接口（hub 是旧版）。\n"
                                       "可以让管理员把 hub 更新到最新，或直接找他要新客户端。")
            return
        need = _vnum(info["version"]) > _vnum(VERNUM)
        if not need:
            if not silent:
                messagebox.showinfo(APP_NAME, "已经是最新版（本机 %s / 服务器 %s）。"
                                    % (VERNUM, info["version"]))
            return
        size = info.get("size") or 0
        ok = messagebox.askyesno(
            APP_NAME,
            "发现新版本！\n\n本机版本：%s\n最新版本：%s\n安装包大小：%.1f MB\n\n"
            "现在更新吗？（客户端会自动关闭、替换完成后重新打开）"
            % (VERNUM, info["version"], size / 1048576.0))
        if not ok:
            return
        self.btn_upd.config(state="disabled", text="下载中…")
        threading.Thread(target=self._do_update,
                         args=("http://%s:%d" % (ip, HUB_PORT), info), daemon=True).start()

    def _do_update(self, base, info):
        size = info.get("size") or 0
        dlg = DownloadDialog(self, VERNUM, info.get("version", "?"), size)

        def prog(got, total):
            try:
                dlg.progress(got, total)
            except Exception:
                pass

        def phase(text):
            try:
                dlg.phase(text)
            except Exception:
                pass

        err = apply_update(base, info, prog, phase)
        if err:
            dlg.close()
            self.after(0, lambda: (self.btn_upd.config(state="normal", text="检查更新"),
                                   messagebox.showerror(APP_NAME, "更新失败：" + err)))
            return
        self.after(0, lambda: dlg.phase("更新完成，程序即将自动重启 …"))
        time.sleep(0.8)
        os._exit(0)

    def enter(self):
        if not self.sel:
            messagebox.showwarning(APP_NAME, "还没有找到车。\n请让车上电，或点「重新查找」。")
            return
        ip = self.sel
        h = health(ip)
        if not h.startswith("ok"):
            messagebox.showerror(APP_NAME,
                                 "连不上 %s:8000\n车可能关机了，或 IP 变了。\n\n点「重新查找」试试。" % ip)
            return
        self.cfg["last_ip"] = ip
        save_cfg(self.cfg)
        how = open_console("http://%s:%d" % (ip, HUB_PORT))
        self.lbl_tip.config(text="已在%s打开 · 账号找管理员要（管理员 zwh）" %
                                 ("独立窗口" if how == "app" else "浏览器"))

    def open_video(self):
        """在客户端里直接看车上画面（不需要浏览器）。"""
        if not self.sel:
            messagebox.showwarning(APP_NAME, "还没有找到车。\n请让车上电，或点「重新查找」。")
            return
        ip = self.sel
        if not health(ip).startswith("ok"):
            messagebox.showerror(APP_NAME, "连不上 %s:8000\n车可能关机了，或 IP 变了。" % ip)
            return
        self.cfg["last_ip"] = ip
        save_cfg(self.cfg)
        VideoWindow(self, ip)
        self.lbl_tip.config(text="画面窗口已打开 · 四路可切换；连不上就回控制台点『全部启动』")


def main():
    # 直接看画面：XTHUBClient.exe --video [IP]
    if "--video" in sys.argv:
        i = sys.argv.index("--video")
        ip = sys.argv[i + 1] if len(sys.argv) > i + 1 else None
        if not ip:
            ip = load_cfg().get("last_ip") or "192.168.110.44"
        try:
            app = App()
            app.withdraw()
            VideoWindow(app, ip)
            app.mainloop()
        except Exception as e:
            print(e)
            return 1
        return 0

    # 单实例：已经有窗口就退出
    try:
        App().mainloop()
    except Exception as e:
        try:
            from tkinter import messagebox as mb
            mb.showerror(APP_NAME, "启动失败：%s" % e)
        except Exception:
            print(e)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
