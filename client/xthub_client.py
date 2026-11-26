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

import json
import os
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

APP_NAME = "XT-HUB 客户端"
VER = "v1.0"
HUB_PORT = 8000

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
        if last and probe(last):
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
        if self.sel is None or prefer:
            self.sel = ip
            idx = self.lst.size() - 1
            self.lst.selection_clear(0, "end")
            self.lst.selection_set(idx)
            self.lbl_state.config(text="找到 XT-HUB：%s" % ip, fg=OK)

    def _scan_done(self):
        self.scanning = False
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
        if self.sel in local_ips():
            self.lbl_state.config(
                text="已选：%s（这台电脑自己，没有真实画面）" % self.sel, fg=WARN)
        else:
            self.lbl_state.config(text="已选：%s" % self.sel, fg=OK)

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


def main():
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
