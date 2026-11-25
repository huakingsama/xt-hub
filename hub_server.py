#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
XT-R1 多人协作控制台  —— 单文件、纯标准库、Python 3.6+
跑在机器人上：python3 hub_server.py --port 8000
本地测试   ：python3 hub_server.py --dry-run --port 8000

角色：admin(全权) / operator(拿到控制权才能写) / viewer(只读)
规则：读是广播(不限人数)，写是抢占(租约+超时自动释放)
"""
import base64
import hashlib
import hmac
import json
import math
import os
import re
import shlex
import subprocess
import sys
import threading
import urllib.request
import time
from http.server import BaseHTTPRequestHandler, HTTPServer, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlparse

if getattr(sys, "frozen", False):
    # PyInstaller onefile：__file__ 在临时解包目录，配置要跟着 exe 走
    HERE = os.path.dirname(os.path.abspath(sys.executable))
else:
    _f = os.path.abspath(__file__)
    HERE = os.path.dirname(_f)
    if not os.path.isdir(HERE):          # zipapp: __file__ 在 .pyz 压缩包内部
        HERE = os.path.dirname(HERE)
CONF = os.path.join(HERE, "config.json")
AUDIT = os.path.join(HERE, "audit.jsonl")
LOCK = threading.RLock()

DRY = "--dry-run" in sys.argv

# ---------------------------------------------------------------- config ----
DEFAULT = {
    "port": 8000,
    "secret": "",
    "lease_ttl": 90,
    "robot": {"host": "192.168.110.44", "cam": 8090, "map": 8091, "fuse": 8093},
    "slam_script": "~/slam_ctl.sh",
    "users": [],
}


def load_conf():
    if os.path.exists(CONF):
        with open(CONF, "r", encoding="utf-8") as f:
            return json.load(f)
    c = dict(DEFAULT)
    c["secret"] = base64.b16encode(os.urandom(16)).decode()
    save_conf(c)
    return c


def save_conf(c):
    tmp = CONF + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(c, f, ensure_ascii=False, indent=2)
    os.replace(tmp, CONF)


CFG = load_conf()


def pbkdf2(pw, salt):
    return hashlib.pbkdf2_hmac("sha256", pw.encode(), salt.encode(), 120000).hex()


def add_user(name, pw, role="viewer"):
    salt = base64.b16encode(os.urandom(8)).decode()
    for u in CFG["users"]:
        if u["u"] == name:
            u.update({"salt": salt, "h": pbkdf2(pw, salt), "role": role})
            save_conf(CFG)
            return
    CFG["users"].append({"u": name, "salt": salt, "h": pbkdf2(pw, salt), "role": role})
    save_conf(CFG)


def check_pw(name, pw):
    for u in CFG["users"]:
        if u["u"] == name and hmac.compare_digest(u["h"], pbkdf2(pw, u["salt"])):
            return u
    return None


def role_of(name):
    for u in CFG["users"]:
        if u["u"] == name:
            return u["role"]
    return None


# ---------------------------------------------------------------- tokens ----
def sign(tok):
    mac = hmac.new(CFG["secret"].encode(), tok.encode(), hashlib.sha256).hexdigest()[:32]
    return tok + "." + mac


def unsign(s):
    if "." not in s:
        return None
    tok, mac = s.rsplit(".", 1)
    good = hmac.new(CFG["secret"].encode(), tok.encode(), hashlib.sha256).hexdigest()[:32]
    if not hmac.compare_digest(mac, good):
        return None
    try:
        return json.loads(base64.b64decode(tok.encode()).decode())
    except Exception:
        return None


def make_session(user):
    payload = {"u": user, "r": role_of(user), "exp": time.time() + 12 * 3600}
    return sign(base64.b64encode(json.dumps(payload).encode()).decode())


def session_of(handler):
    raw = handler.headers.get("Cookie", "")
    for part in raw.split(";"):
        if part.strip().startswith("xt="):
            d = unsign(part.strip()[3:])
            if d and d.get("exp", 0) > time.time():
                return d
    return None


# ----------------------------------------------------------------- lease ----
LEASE = {"holder": None, "token": None, "exp": 0}


def lease_state():
    with LOCK:
        if LEASE["holder"] and LEASE["exp"] < time.time():
            LEASE.update({"holder": None, "token": None, "exp": 0})
        return dict(LEASE)


def audit(user, action, detail, ok):
    rec = {"t": time.strftime("%Y-%m-%d %H:%M:%S"), "u": user, "a": action,
           "d": detail, "ok": ok}
    with LOCK:
        with open(AUDIT, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")


# -------------------------------------------------------------- commands ----
WHITELIST = {"start", "stop", "save", "status"}


def run_slam(action):
    script = os.path.expanduser(CFG["slam_script"])
    if DRY:
        return 0, "[dry-run] bash %s %s\n(模拟: 未真正执行)" % (script, action)
    if action not in ("status",) and not os.path.exists(script):
        return 127, "找不到 %s" % script
    try:
        p = subprocess.run(["bash", script, action], stdout=subprocess.PIPE,
                           stderr=subprocess.STDOUT, timeout=180)
        return p.returncode, p.stdout.decode("utf-8", "replace")[-4000:]
    except subprocess.TimeoutExpired:
        return 124, "超时(180s)"
    except Exception as e:
        return 1, repr(e)


# ----------------------------------------------------------------- demo ----
# 没有机器人时用：合成"地图 / 融合俯视 / 相机"三路假画面，界面与流程完全一样
DEMO = "--demo" in sys.argv
_GRID = {}       # 演示用累积栅格
_T0 = time.time()


def _png(w, h, rgb):
    import struct
    import zlib
    raw = bytearray()
    for y in range(h):
        raw.append(0)
        raw += rgb[y * w * 3:(y + 1) * w * 3]
    def ch(t, d):
        return (struct.pack(">I", len(d)) + t + d
                + struct.pack(">I", zlib.crc32(t + d) & 0xffffffff))
    return (b"\x89PNG\r\n\x1a\n"
            + ch(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
            + ch(b"IDAT", zlib.compress(bytes(raw), 6))
            + ch(b"IEND", b""))


# 演示房间：8m x 6m，右下角留一个 1m 的门洞
SEGS = [(-4, -3, 4, -3), (4, -3, 4, 3), (-4, 3, -4, -3),
        (-4, 3, 0, 3), (1, 3, 4, 3)]


def _ray(ox, oy, dx, dy):
    best = 12.0
    for x1, y1, x2, y2 in SEGS:
        ex, ey = x2 - x1, y2 - y1
        den = dx * ey - dy * ex
        if abs(den) < 1e-9:
            continue
        t = ((x1 - ox) * ey - (y1 - oy) * ex) / den
        u = ((x1 - ox) * dy - (y1 - oy) * dx) / den
        if t > 0 and 0 <= u <= 1 and t < best:
            best = t
    return best


_DEMO_CACHE = {}
_DEMO_LOCK = threading.Lock()


def _demo_png(path, t):
    """同一条路径 0.45s 内复用同一张图，避免多人同时打开时重复渲染"""
    now = time.time()
    hit = _DEMO_CACHE.get(path)
    if hit and now - hit[0] < 0.45:
        return hit[1]
    with _DEMO_LOCK:
        hit = _DEMO_CACHE.get(path)
        if hit and time.time() - hit[0] < 0.45:
            return hit[1]
        fn = demo_map if "map" in path else (demo_fuse if "fuse" in path else demo_rgb)
        png = fn(t)
        _DEMO_CACHE[path] = (time.time(), png)
        return png


def demo_map(t):
    """累积式栅格建图：越看越像真的"""
    W = H = 460
    res = 0.022
    g = _GRID.setdefault("m", bytearray(W * H))
    ang0 = t * 0.42                      # 慢慢转
    ox = 1.60 * math.cos(t * 0.18)        # 绕房间走一圈
    oy = 1.10 * math.sin(t * 0.18)
    for i in range(720):
        a = ang0 + i * (2 * math.pi / 720)
        dx, dy = math.cos(a), math.sin(a)
        r = _ray(ox, oy, dx, dy)
        steps = int(r / res)
        for s in range(2, steps):
            px = int(W / 2 + (ox + dx * s * res) / res)
            py = int(H / 2 + (oy + dy * s * res) / res)
            for ddy in (0, 1):
                for ddx in (0, 1):
                    X, Y = px + ddx, py + ddy
                    if 0 <= X < W and 0 <= Y < H and g[Y * W + X] == 0:
                        g[Y * W + X] = 1
        px = int(W / 2 + (ox + dx * r) / res)
        py = int(H / 2 + (oy + dy * r) / res)
        for ddy in (-1, 0, 1):
            for ddx in (-1, 0, 1):
                X, Y = px + ddx, py + ddy
                if 0 <= X < W and 0 <= Y < H:
                    g[Y * W + X] = 2
    rgb = bytearray(W * H * 3)
    for i, v in enumerate(g):
        c = (120, 126, 136) if v == 0 else ((246, 247, 249) if v == 1 else (26, 26, 30))
        rgb[i * 3:i * 3 + 3] = bytes(c)
    return _png(W, H, rgb)


def demo_fuse(t):
    """雷达(橙) + 深度(蓝红) 俯视"""
    S = 420
    C = S / 2
    rgb = bytearray(b"\x0b\x0f\x14" * (S * S))
    import math as _m
    for i in range(360):
        a = t * 0.4 + i * (2 * _m.pi / 360)
        dx, dy = _m.cos(a), _m.sin(a)
        r = _ray(0, 0, dx, dy)
        for k in range(4):
            rr = r * (0.45 + 0.13 * k)
            px, py = int(C + rr * 40 * dx), int(C + rr * 40 * dy)
            if 0 <= px < S and 0 <= py < S:
                o = (py * S + px) * 3
                rgb[o:o + 3] = bytes((110, 72, 24))
        px, py = int(C + r * 40 * dx), int(C + r * 40 * dy)
        for ddy in (0, 1):
            for ddx in (0, 1):
                X, Y = px + ddx, py + ddy
                if 0 <= X < S and 0 <= Y < S:
                    o = (Y * S + X) * 3
                    rgb[o:o + 3] = bytes((255, 168, 60))
    for i in range(160):
        d = 0.9 + 2.4 * abs(_m.sin(i * 0.31 + t))
        a = t * 0.4 - 0.5 + i * 0.0065
        px = int(C + d * 90 * _m.cos(a))
        py = int(C + d * 90 * _m.sin(a))
        if 0 <= px < S and 0 <= py < S:
            k = min(1.0, d / 3.2)
            o = (py * S + px) * 3
            rgb[o:o + 3] = bytes((int(60 + 195 * k), int(160 - 120 * k), int(255 - 200 * k)))
    return _png(S, S, rgb)


def demo_rgb(t):
    """彩色滚动条 + 走动的色块，用来验证"流"是活的"""
    W, H = 480, 320
    rgb = bytearray(W * H * 3)
    for y in range(H):
        v = int(40 + 60 * (y / H))
        for x in range(W):
            o = (y * W + x) * 3
            rgb[o:o + 3] = bytes((v, v + 8, v + 20))
    bx = int((t * 90) % (W - 60))
    for y in range(120, 200):
        for x in range(bx, bx + 60):
            o = (y * W + x) * 3
            rgb[o:o + 3] = bytes((90, 200, 140))
    band = int((t * 160) % W)
    for y in range(H):
        for x in range(max(0, band - 6), min(W, band + 6)):
            o = (y * W + x) * 3
            rgb[o:o + 3] = bytes((240, 200, 90))
    return _png(W, H, rgb)


B_PORT = 8099
_BSTATE = {"t": 0.0, "v": None}


def _bridge(path, payload=None, timeout=1.6):
    url = "http://%s:%d%s" % (CFG["robot"]["host"], B_PORT, path)
    data = None
    hdr = {}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        hdr["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=hdr)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


def _home():
    return os.path.expanduser("~")


def dir3d():
    """找 3d_maps 目录：环境变量优先，其次 ~/3d_maps、脚本同级、一键脚本下"""
    cands = [os.environ.get("XTHUB_3D_DIR", ""), os.path.join(_home(), "3d_maps"),
             os.path.join(HERE, "3d_maps"), os.path.join(HERE, "..", "3d_maps"),
             os.path.join(HERE, "..", "一键脚本", "3d_maps")]
    for d in cands:
        if d and os.path.isdir(d):
            return os.path.abspath(d)
    return ""


def list3d():
    """列出可看的 3D 地图（*.html，排除 index.html）"""
    d = dir3d()
    if not d:
        return {"ok": False, "dir": "", "items": [], "error": "没找到 3d_maps 目录"}
    items = []
    try:
        for fn in os.listdir(d):
            if not fn.endswith(".html") or fn == "index.html":
                continue
            fp = os.path.join(d, fn)
            try:
                stt = os.stat(fp)
            except OSError:
                continue
            base = fn[:-5]
            pts = 0
            try:
                if stt.st_size < 4 * 1024 * 1024:
                    txt = open(fp, "rb").read().decode("utf-8", "replace")
                    i = txt.find("const P=[[")
                    j = txt.find("]]", i) if i >= 0 else -1
                    if i >= 0 and j > i:
                        pts = txt[i + 10:j].count("], [") + 1
            except Exception:
                pass
            items.append({
                "name": fn, "ts": time.strftime("%Y-%m-%d %H:%M", time.localtime(stt.st_mtime)),
                "kb": round(stt.st_size / 1024), "points": pts,
                "png": os.path.exists(os.path.join(d, base + ".png")),
                "pcd": os.path.exists(os.path.join(d, base + ".pcd")),
            })
    except OSError as e:
        return {"ok": False, "dir": d, "items": [], "error": str(e)}
    items.sort(key=lambda x: x["name"], reverse=True)
    return {"ok": True, "dir": d, "items": items}


def read3d(name):
    """安全读取 3d_maps 里的单个文件（防目录穿越）"""
    d = dir3d()
    if not d:
        return None, None
    safe = os.path.basename(name)
    if safe != name or not re.match(r"^[A-Za-z0-9_.\-]+$", safe):
        return None, None
    fp = os.path.join(d, safe)
    if not os.path.isfile(fp):
        return None, None
    ext = os.path.splitext(safe)[1].lower()
    ctype = {".html": "text/html; charset=utf-8", ".png": "image/png",
             ".pcd": "application/octet-stream"}.get(ext, "application/octet-stream")
    with open(fp, "rb") as f:
        return f.read(), ctype


STACK_PORT = int(os.environ.get("XTHUB_STACK_PORT", "8100"))


def stack_proxy(path, method="GET", timeout=20):
    """转发到机器人上的 robot_stack.py(:8100)"""
    url = "http://127.0.0.1:%d%s" % (STACK_PORT, path)
    req = urllib.request.Request(url, data=(b"" if method == "POST" else None),
                                 method=method)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


def demo_stack():
    """演示态：五个组件都在跑，让人能看到完整的界面"""
    names = [("slam", "雷达 + 建图", 8091), ("camera", "深度相机驱动", 0),
             ("fuse", "雷达+深度融合画面", 8093), ("cam", "相机画面服务", 8090),
             ("bridge", "遥控桥", 8099)]
    return {"ok": True, "dry": True, "up": len(names), "total": len(names),
            "host": "demo", "ts": time.strftime("%H:%M:%S"), "mode": "radar",
            "comps": [{"name": n, "label": l, "note": "", "up": True,
                       "port": bool(p) if p else None, "port_no": p, "last": None}
                      for n, l, p in names]}


def demo_state():
    """演示位姿：与 demo_map 用同一套参数，叠在图上正好对齐"""
    t = time.time() - _T0
    W = H = 460
    res = 0.022
    ox = 1.60 * math.cos(t * 0.18)
    oy = 1.10 * math.sin(t * 0.18)
    th = t * 0.42
    traj = _GRID.setdefault("traj", [])
    if not traj or math.hypot(ox - traj[-1][0], oy - traj[-1][1]) > 0.05:
        traj.append([round(ox, 3), round(oy, 3)])
        if len(traj) > 400:
            del traj[:100]
    return {"ok": True, "pose": [ox, oy, th], "age": 0.0,
            "traj": traj[-300:],
            "meta": {"res": res, "ox": -W / 2.0 * res, "oy": -H / 2.0 * res,
                     "w": W, "h": H, "flip": 0, "ok": True},
            "cmd_subs": 1, "target": {"lin": 0, "ang": 0}, "ts": time.time()}


REC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "records")
_REC = {"on": False, "t0": 0.0, "frames": [], "name": None, "th": None}


def _rec_loop():
    while True:
        time.sleep(0.5)
        if not _REC["on"]:
            continue
        try:
            st = api_state()
            pose = st.get("pose")
            if not pose:
                continue
            t = round(time.time() - _REC["t0"], 2)
            _REC["frames"].append([t, round(pose[0], 3), round(pose[1], 3), round(pose[2], 3)])
            if len(_REC["frames"]) > 20000:
                _REC["frames"].pop(0)
        except Exception:
            pass


def rec_start(name):
    if _REC["on"]:
        return {"ok": False, "error": "正在录制"}
    try:
        os.makedirs(REC_DIR)
    except Exception:
        pass
    _REC.update({"on": True, "t0": time.time(), "frames": [],
                 "name": (name or time.strftime("traj_%Y%m%d_%H%M%S")).replace("/", "_")})
    return {"ok": True, "name": _REC["name"]}


def rec_stop():
    if not _REC["on"]:
        return {"ok": True, "frames": 0}
    _REC["on"] = False
    n = len(_REC["frames"])
    if n >= 2:
        path = os.path.join(REC_DIR, _REC["name"] + ".json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"name": _REC["name"], "start": _REC["t0"],
                       "dur": _REC["frames"][-1][0], "frames": _REC["frames"]}, f)
    return {"ok": True, "frames": n, "name": _REC["name"]}


def rec_list():
    out = []
    try:
        for fn in os.listdir(REC_DIR):
            if not fn.endswith(".json"):
                continue
            fp = os.path.join(REC_DIR, fn)
            try:
                with open(fp, "r", encoding="utf-8") as f:
                    d = json.load(f)
                out.append({"name": d.get("name"), "frames": len(d.get("frames", [])),
                            "dur": d.get("dur", 0), "size": os.path.getsize(fp)})
            except Exception:
                pass
    except Exception:
        pass
    out.sort(key=lambda x: x["dur"], reverse=True)
    return out


def rec_get(name):
    path = os.path.join(REC_DIR, os.path.basename(name or "") + ".json")
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"error": "not found"}


threading.Thread(target=_rec_loop, daemon=True).start()


def api_state():
    if DEMO or DRY:
        return demo_state()
    try:
        v = _bridge("/state")
        _BSTATE.update({"t": time.time(), "v": v})
        return v
    except Exception as e:
        if _BSTATE["v"] and time.time() - _BSTATE["t"] < 6:
            v = dict(_BSTATE["v"])
            v["stale"] = True
            return v
        return {"ok": False, "error": "位姿桥不可达: %s" % e}


def robot_status():
    """给顶部状态灯用：谁活着、雷达多少 Hz"""
    if DEMO:
        return {"mode": "demo", "radar": True, "hz": 7.18, "hector": True}
    if DRY:
        return {"mode": "dry-run", "radar": True, "hz": 7.10, "hector": True}
    out = {"mode": "live", "radar": False, "hz": 0.0, "hector": False}

    def alive(pat):
        try:
            return subprocess.run(["pgrep", "-f", pat], stdout=subprocess.DEVNULL,
                                  stderr=subprocess.DEVNULL).returncode == 0
        except Exception:
            return False

    out["hector"] = alive("hector") or alive("cartographer")
    out["radar"] = alive("rplidar")
    try:
        with open(os.path.expanduser("~/data/status.txt"), "r") as f:
            parts = f.read().strip().split("|")
        if len(parts) > 1:
            out["hz"] = float(parts[1])
    except Exception:
        pass
    return out


def recent_activity(n=12):
    if not os.path.exists(AUDIT):
        return []
    try:
        with open(AUDIT, "r", encoding="utf-8") as f:
            lines = f.readlines()[-n:]
    except Exception:
        return []
    res = []
    for ln in reversed(lines):
        try:
            res.append(json.loads(ln))
        except Exception:
            pass
    return res


# ------------------------------------------------------------------ html ----
CSS = """
*{box-sizing:border-box}
body{margin:0;background:#0e1116;color:#d7dde6;font:14px/1.5 -apple-system,"Segoe UI","Microsoft YaHei",sans-serif}
a{color:#6cb6ff;text-decoration:none}
.wrap{max-width:1280px;margin:0 auto;padding:18px}
h1{font-size:19px;margin:0 0 4px}
.sub{color:#7d8794;font-size:12px;margin-bottom:18px}
.card{background:#161b22;border:1px solid #232b36;border-radius:10px;padding:16px;margin-bottom:14px}
.bar{display:flex;gap:10px;align-items:center;flex-wrap:wrap}
input,select{background:#0d1117;border:1px solid #2b3542;color:#d7dde6;padding:9px 11px;border-radius:7px;font-size:14px}
input:focus,select:focus{outline:none;border-color:#3d7dd8}
button{background:#24476f;color:#e6eefc;border:1px solid #2f5d92;padding:9px 15px;border-radius:7px;font-size:14px;cursor:pointer}
button:hover{background:#2c5688}
button.ghost{background:#1a212b;border-color:#2b3542;color:#9aa6b5}
button.danger{background:#5a2330;border-color:#7d2f3f;color:#ffdbe2}
button:disabled{opacity:.4;cursor:not-allowed}
.pill{display:inline-block;padding:2px 9px;border-radius:99px;font-size:12px;border:1px solid}
.p-admin{color:#ffd479;border-color:#6b5320;background:#2a2213}
.p-oper{color:#7fd6a0;border-color:#255c3c;background:#13251b}
.p-view{color:#8ecbff;border-color:#254b6b;background:#132230}
.p-off{color:#8b95a3;border-color:#333c48;background:#1a2029}
.grid{display:grid;grid-template-columns:repeat(3,1fr);gap:12px}
@media(max-width:900px){.grid{grid-template-columns:1fr}}
.tile{background:#0b0f14;border:1px solid #232b36;border-radius:9px;overflow:hidden}
.tile h3{margin:0;padding:8px 11px;font-size:12px;color:#8b95a3;font-weight:500;border-bottom:1px solid #1d242e}
.tile .body{height:340px;display:flex;align-items:center;justify-content:center;color:#4a5563;font-size:12px;text-align:center;padding:10px}
.tile img,.tile iframe{width:100%;height:340px;border:0;display:block;object-fit:contain;background:#0b0f14}
pre{background:#0b0f14;border:1px solid #1d242e;border-radius:7px;padding:11px;overflow:auto;font-size:12px;max-height:260px;color:#9fb0c3}
table{width:100%;border-collapse:collapse;font-size:13px}
th,td{text-align:left;padding:7px 9px;border-bottom:1px solid #1d242e}
th{color:#7d8794;font-weight:500;font-size:12px}
.lease{display:flex;justify-content:space-between;align-items:center;gap:12px;flex-wrap:wrap}
.hint{color:#7d8794;font-size:12px}
.login{max-width:340px;margin:12vh auto}
.err{color:#ff8b9a;font-size:13px;margin-top:10px}
"""


def _go(url, msg="正在跳转…"):
    """不依赖 302 的跳转页：meta refresh + 脚本 + 手点链接，三保险"""
    return (
        "<!doctype html><html lang=zh><head><meta charset=utf-8>"
        "<meta http-equiv=refresh content=\"0;url=%s\">"
        "<title>跳转中 · XT-R1</title></head>"
        "<body style=\"margin:0;background:#0e1116;color:#d7dde6;font:14px/1.6 "
        "-apple-system,'Segoe UI','Microsoft YaHei',sans-serif;padding:60px\">"
        "<div style=\"max-width:420px;margin:0 auto\">%s"
        "<p><a href=\"%s\" style=\"color:#6cb6ff\">点这里继续</a></p></div>"
        "<script>setTimeout(function(){location.replace('%s')},60)</script>"
        "</body></html>" % (url, msg, url, url))


def page(title, body, user=None, extra=""):
    who = ""
    if user:
        cls = {"admin": "p-admin", "operator": "p-oper"}.get(user["r"], "p-view")
        who = ('<span class="pill %s">%s · %s</span> '
               '<a href="/live" style="margin-left:10px">控制台</a>'
               '%s <a href="/logout" style="margin-left:10px;color:#7d8794">退出</a>'
               % (cls, user["u"], user["r"],
                  ' <a href="/admin" style="margin-left:10px">管理</a>' if user["r"] == "admin" else ""))
    return ("<!doctype html><html lang=zh><head><meta charset=utf-8>"
            "<meta name=viewport content='width=device-width,initial-scale=1'>"
            "<title>%s · XT-R1</title><style>%s</style>%s</head><body><div class=wrap>"
            "<div class=bar style='justify-content:space-between;margin-bottom:14px'>"
            "<div><h1>XT-R1 协作控制台</h1><div class=sub style='margin:0'>多人共享机器人 · 读是广播，写是抢占</div></div>"
            "<div>%s</div></div>%s</div></body></html>"
            % (title, CSS + CSS2, extra, who, body))


LOGIN = """
<div class=card style='max-width:340px;margin:8vh auto'>
  <h1 style='margin-bottom:14px'>登录</h1>
  <form method=post action=/login>
    <input name=u placeholder=用户名 style='width:100%%;margin-bottom:9px' autofocus>
    <input name=p type=password placeholder=密码 style='width:100%%;margin-bottom:12px'>
    <button style='width:100%%'>进入</button>
  </form>
  %s
</div>
"""


CSS2 = """
.hud{position:sticky;top:0;z-index:20;display:flex;justify-content:space-between;align-items:center;
  gap:14px;background:#12171f;border:1px solid #232b36;border-radius:9px;padding:9px 13px;margin-bottom:12px;flex-wrap:wrap}
.hud b{font-weight:500;font-size:13px;color:#c3ccd8}
.dot{display:inline-block;width:8px;height:8px;border-radius:99px;background:#4a5563;margin-right:6px;vertical-align:1px}
.dot.on{background:#3fbf7f;box-shadow:0 0 7px #3fbf7f88}
.dot.warn{background:#e0a92c}
.dot.off{background:#c8455a}
.sep{display:inline-block;width:1px;height:14px;background:#2b3542;margin:0 4px;vertical-align:-2px}
.stage{display:grid;grid-template-columns:2fr 1fr;grid-template-rows:1fr 1fr;gap:10px;height:calc(100vh - 250px);min-height:420px}
#z-map{grid-row:1/3}
.tile{position:relative;background:#0b0f14;border:1px solid #232b36;border-radius:10px;overflow:hidden;cursor:zoom-in;display:flex;flex-direction:column}
.tile h3{margin:0;padding:7px 11px;font-size:11.5px;color:#8b95a3;font-weight:500;border-bottom:1px solid #1d242e;
  display:flex;justify-content:space-between}
.tile .body{flex:1;display:flex;align-items:center;justify-content:center;color:#4a5563;font-size:12px;text-align:center;padding:8px}
.tile img{flex:1;width:100%;min-height:0;object-fit:contain;display:block;background:#0b0f14}
.tile.zoom{position:fixed;inset:10px;z-index:60;cursor:zoom-out;box-shadow:0 0 0 100vmax #000a}
.ctl{position:sticky;bottom:0;z-index:20;display:flex;gap:9px;align-items:center;flex-wrap:wrap;
  background:#12171f;border:1px solid #232b36;border-radius:9px;padding:10px 13px;margin-top:12px}
.flex{flex:1}
.low{display:grid;grid-template-columns:1.3fr 1fr .95fr;gap:10px;margin-top:10px}
.feed{background:#0b0f14;border:1px solid #1d242e;border-radius:9px;padding:9px 11px;font-size:12px;
  color:#8b95a3;height:150px;overflow:auto}
.feed div{padding:2px 0;border-bottom:1px solid #141a22}
.feed .t{color:#5d6875;margin-right:7px}
.feed .u{color:#7fb4ff}

.mapwrap{position:relative;flex:1;min-height:0;display:flex}
#cv{position:absolute;inset:0;width:100%;height:100%;pointer-events:auto;cursor:crosshair}
.zb{cursor:pointer;color:#4f8cff}
.kbd{font-size:11px;color:#5d6875;letter-spacing:.3px}
input[type=range]{width:84px;accent-color:#4f8cff;vertical-align:-3px}
.chip{font-size:11.5px;color:#8b95a3;border:1px solid #2b3542;border-radius:99px;padding:2px 9px}
.lk3{color:#7ac2ff;text-decoration:none;font-size:12px;margin-left:6px}
.lk3:hover{text-decoration:underline}
.stackdots{display:inline-flex;gap:10px;flex-wrap:wrap;font-size:11.5px;color:#9aa5b3}
.stackdots .st{display:inline-flex;align-items:center;gap:4px}
.stackdots .dot{width:7px;height:7px}

.rec{background:#0b0f14;border:1px solid #1d242e;border-radius:9px;padding:9px 11px;height:150px;overflow:auto}
.rech{display:flex;justify-content:space-between;align-items:center;margin-bottom:7px}
.rech b{font-size:12px;color:#8b95a3;font-weight:500}
.rech button{padding:3px 10px;font-size:11.5px}
.rrow{display:flex;justify-content:space-between;align-items:center;padding:4px 0;border-bottom:1px solid #141a22;font-size:12px;color:#9aa5b1}
.rrow button{padding:2px 9px;font-size:11px}
@media(max-width:900px){.stage{grid-template-columns:1fr;grid-template-rows:none;height:auto}
 .stage .tile{min-height:280px}#z-map{grid-row:auto}.low{grid-template-columns:1fr}}
"""


def live_page(user, robot):
    demo = DEMO
    host = robot["host"]
    T = {
        "MAP": "/demo/map.png" if demo else "http://%s:%s/map.png" % (host, robot["map"]),
        "FUSE": "/demo/fuse.png" if demo else "http://%s:%s/fuse.png" % (host, robot["fuse"]),
        "CAM": "/demo/rgb.png" if demo else "http://%s:%s/rgb" % (host, robot["cam"]),
        "CAMT": "演示合成" if demo else "实时流 :%s" % robot["cam"],
        "MAPHINT": "点图下发目标" if not (demo or DRY) else "点图预览目标",
        "MODE": "演示模式（合成数据）" if demo else ("演练模式（不下发指令）" if DRY else "真实机器人"),
        "USER": user["u"],
        "ADMIN": "true" if user["r"] == "admin" else "false",
        "ECHO": "true" if (demo or DRY) else "false",
    }
    tpl = r"""
<div class=hud>
  <div class=bar>
    <span class=dot id=d-rad></span><b id=v-rad>雷达</b>
    <span class=sep></span>
    <span class=dot id=d-hec></span><b id=v-hec>建图</b>
    <span class=sep></span>
    <b style="color:#7d8794">__MODE__</b>
    <span class=sep></span><a class=lk3 href="/3d" target="_blank">3D 地图 ↗</a>
  </div>
  <div class=bar>
    <span class=chip id=v-tel>键盘待命</span>
    <span class=pill p-off id=v-holder>无人驾驶</span>
    <span class=hint id=v-exp></span>
  </div>
</div>

<div class=stage>
  <div class=tile id=z-map>
    <h3><span>实时地图 · 位姿 · 轨迹</span>
        <span><span class=kbd>点图=目标</span> <span class=zb onclick="zoom('z-map')">⤢</span></span></h3>
    <div class=mapwrap>
      <div class=body id=t-map>连接中…</div>
      <canvas id=cv></canvas>
    </div>
  </div>
  <div class=tile id=z-fuse onclick="zoom('z-fuse')">
    <h3><span>雷达 + 深度融合</span><span class=zb>⤢</span></h3>
    <div class=body id=t-fuse>连接中…</div>
  </div>
  <div class=tile id=z-cam onclick="zoom('z-cam')">
    <h3><span>相机</span><span class=kbd>__CAMT__</span></h3>
    <img id=t-cam src="__CAM__" onerror="this.style.display='none';document.getElementById('camx').style.display='flex'">
    <div class=body id=camx style="display:none">等待相机…</div>
  </div>
</div>

<div class=ctl>
  <span class=chip>传感器栈</span>
  <span id=stackdots class=stackdots>读取中…</span>
  <button class=ghost onclick="stackCmd('all','start')">全部启动</button>
  <button class=ghost onclick="stackCmd('all','stop')">全部停止</button>
  <span class=sep></span>
  <button class=ghost id=b-mode onclick="setMode()">建图模式</button>
  <span class=flex></span>
  <button onclick=claim()>接管控制权</button>
  <button class=ghost onclick=rel()>释放</button>
  <span class=sep></span>
  <button class=ghost onclick="act('start')">启动建图</button>
  <button onclick="act('save')">保存地图</button>
  <button class=ghost onclick="act('status')">自检</button>
  <span class=flex></span>
  <span class=kbd>速度 <input id=spd type=range min=5 max=20 value=12 oninput="LIN=this.value/100;document.getElementById('v-lin').textContent=(this.value/100).toFixed(2)"> <span id=v-lin>0.12</span> m/s</span>
  <button class=danger onclick=stopask()>急停</button>
</div>

<div class=low>
  <pre id=out>就绪。接管后用 W/S 前后、A/D 转向（松手即停）；点地图下发导航目标。</pre>
  <div class=feed id=feed></div>
  <div class=rec>
    <div class=rech><b>轨迹录制 / 回放</b><button id=btn-rec onclick=toggleRec()>开始录制</button></div>
    <div id=reclist>加载中…</div>
  </div>
</div>

<script>
var USR='__USER__', TOK=null, LIN=0.12, ANG=0.8, ST={}, GOAL=null, ECHO=__ECHO__, KEY={};
function q(u,o){return fetch(u,o).then(function(r){return r.json()})}
function out(t){document.getElementById('out').textContent=t}
function zoom(id){document.getElementById(id).classList.toggle('zoom')}
document.addEventListener('keydown',function(e){
  if(e.key==='Escape'){var z=document.querySelector('.tile.zoom');if(z)z.classList.remove('zoom');return}
  var k=e.key.toLowerCase();
  if('wasd'.indexOf(k)>=0||k.indexOf('arrow')===0){KEY[k]=1;e.preventDefault();drive()}
});
document.addEventListener('keyup',function(e){
  var k=e.key.toLowerCase();
  if(KEY[k]){delete KEY[k]; if(!Object.keys(KEY).length)push(0,0)}
});
function drive(){
  if(!TOK){out('请先接管控制权');return}
  var lin=0,ang=0;
  if(KEY.w||KEY.arrowup)lin+=LIN;
  if(KEY.s||KEY.arrowdown)lin-=LIN;
  if(KEY.a||KEY.arrowleft)ang+=ANG;
  if(KEY.d||KEY.arrowright)ang-=ANG;
  push(lin,ang);
}
function push(lin,ang){
  var t=document.getElementById('v-tel');
  t.textContent=(lin||ang)?('行驶 '+lin.toFixed(2)+' / '+ang.toFixed(2)):'键盘待命';
  fetch('/api/teleop',{method:'POST',headers:{'Content-Type':'application/json','X-Token':TOK||''},
    body:JSON.stringify({lin:lin,ang:ang})}).then(function(r){return r.json()}).then(function(r){
      if(r.error)out('遥控失败：'+r.error)}).catch(function(){});
}
setInterval(function(){if(Object.keys(KEY).length)drive()},110);

function paint(s){
  var h=document.getElementById('v-holder'),e=document.getElementById('v-exp');
  if(s.holder){h.className='pill p-oper';h.textContent=s.holder==USR?'你在驾驶':(s.holder+' 在驾驶');
    e.textContent='剩余 '+Math.max(0,Math.round(s.exp-Date.now()/1000))+' 秒';}
  else{h.className='pill p-off';h.textContent='无人驾驶';e.textContent='';}
}
function lease(){q('/api/lease').then(function(s){paint(s);
  if(s.holder===USR){TOK=s.token}else if(!s.holder){TOK=null}})}
function claim(){q('/api/lease/claim',{method:'POST'}).then(function(s){
  if(s.error){out('接管失败：'+s.error);return} TOK=s.token;paint(s);
  out('已接管。W/S 前后、A/D 转向、空格/松手停；点地图下发目标。')})}
function rel(){fetch('/api/teleop',{method:'POST',headers:{'Content-Type':'application/json','X-Token':TOK||''},
  body:JSON.stringify({lin:0,ang:0})}).catch(function(){});
  q('/api/lease/release',{method:'POST'}).then(function(s){TOK=null;paint(s);out('已释放控制权')})}
function act(a){ if(!TOK){out('请先接管控制权');return}
  if(a==='stop'&&!confirm('确认停止建图？'))return;
  out('执行 '+a+' …');
  q('/api/cmd?action='+a,{method:'POST',headers:{'X-Token':TOK}}).then(function(r){
    out((r.ok?'OK  ':'ERR ')+a+'\n'+(r.out||r.error||''))})}
function stopask(){ if(!TOK){out('请先接管控制权');return}
  fetch('/api/teleop',{method:'POST',headers:{'Content-Type':'application/json','X-Token':TOK},
    body:JSON.stringify({lin:0,ang:0})}).catch(function(){});
  if(confirm('确认急停？建图与雷达会全部停止。'))act('stop');}

/* ---------- 轨迹录制 / 回放 ---------- */
var PLAY=null, RECON=false;
function toggleRec(){
  if(!TOK){out('请先接管控制权');return}
  if(RECON){
    q('/api/rec/stop',{method:'POST',headers:{'X-Token':TOK}}).then(function(r){
      RECON=false;document.getElementById('btn-rec').textContent='开始录制';
      document.getElementById('btn-rec').className='';
      out('录制结束，共 '+r.frames+' 帧');recList()});
  }else{
    q('/api/rec/start',{method:'POST',headers:{'X-Token':TOK}}).then(function(r){
      if(r.error){out('录制失败：'+r.error);return}
      RECON=true;document.getElementById('btn-rec').textContent='停止录制';
      document.getElementById('btn-rec').className='danger';out('录制中：'+r.name)});
  }
}
function recList(){
  q('/api/rec/list').then(function(d){
    var el=document.getElementById('reclist');
    if(!d.items||!d.items.length){el.innerHTML='<div class=rrow>还没有记录</div>';return}
    el.innerHTML=d.items.map(function(x){
      return '<div class=rrow><span>'+x.name+'</span><span>'+
        x.dur.toFixed(1)+'s · '+x.frames+'帧 <button class=ghost onclick="play(\''+x.name+'\')">回放</button></span></div>'
    }).join('');
  }).catch(function(){});
}
function play(name){
  q('/api/rec/get?name='+encodeURIComponent(name)).then(function(d){
    if(!d.frames||d.frames.length<2){out('这段记录太短，没法回放');return}
    PLAY={f:d.frames,t0:performance.now(),i:0,pose:null,trail:[],name:name};
    out('回放 '+name+'：'+d.frames.length+' 帧 / '+d.frames[d.frames.length-1][0].toFixed(1)+' 秒');
  });
}
function playTick(){
  if(!PLAY)return;
  var t=(performance.now()-PLAY.t0)/1000, f=PLAY.f, j=PLAY.i;
  while(j+1<f.length&&f[j+1][0]<=t)j++;
  PLAY.i=j;
  if(j>=f.length-1&&t>f[j][0]+1.2){PLAY=null;out('回放结束');return}
  var a=f[j], b=f[Math.min(j+1,f.length-1)], k=(b[0]-a[0])>0.01?Math.min(1,(t-a[0])/(b[0]-a[0])):0;
  PLAY.pose=[a[1]+(b[1]-a[1])*k, a[2]+(b[2]-a[2])*k, a[3]+(b[3]-a[3])*k];
  PLAY.trail=f.slice(0,j+1).map(function(p){return [p[1],p[2]]});
  draw();
}
setInterval(playTick,50);
setInterval(recList,8000);

/* ---------- 地图叠加：位姿 / 轨迹 / 目标 ---------- */
function toWorld(ev){
  var m=ST.meta, img=document.querySelector('#t-map img'); if(!m||!img)return null;
  var r=img.getBoundingClientRect();
  var fx=(ev.clientX-r.left)/r.width, fy=(ev.clientY-r.top)/r.height;
  if(fx<0||fx>1||fy<0||fy>1)return null;
  var px=fx*m.w, py=fy*m.h;
  var wy=(m.flip?(m.h-py):py)*m.res+m.oy;
  return [px*m.res+m.ox, wy];
}
function draw(){
  var m=ST.meta, cv=document.getElementById('cv'); if(!cv)return;
  var wrap=cv.parentElement.getBoundingClientRect();
  if(cv.width!==Math.round(wrap.width)||cv.height!==Math.round(wrap.height)){
    cv.width=Math.round(wrap.width); cv.height=Math.round(wrap.height)}
  var g=cv.getContext('2d'); g.clearRect(0,0,cv.width,cv.height);
  var img=document.querySelector('#t-map img'); if(!m||!img){return}
  var ir=img.getBoundingClientRect();
  var ox=ir.left-wrap.left, oy=ir.top-wrap.top, sx=ir.width/m.w, sy=ir.height/m.h;
  function P(wx,wy){var px=(wx-m.ox)/m.res, py=(wy-m.oy)/m.res; if(m.flip)py=m.h-py;
    return [ox+px*sx, oy+py*sy]}
  var E=PLAY?{pose:PLAY.pose,traj:PLAY.trail}:{pose:ST.pose,traj:ST.traj};
  if(E.traj&&E.traj.length>1){
    g.beginPath(); g.strokeStyle=PLAY?'rgba(255,180,60,.85)':'rgba(79,140,255,.75)'; g.lineWidth=2;
    E.traj.forEach(function(p,i){var q=P(p[0],p[1]); i?g.lineTo(q[0],q[1]):g.moveTo(q[0],q[1])});
    g.stroke();
  }
  if(E.pose){
    var p=P(E.pose[0],E.pose[1]);
    var ang=m.flip?(-E.pose[2]):E.pose[2];   // 地图上下翻转时角度取反
    g.save(); g.translate(p[0],p[1]); g.rotate(ang);
    g.beginPath(); g.moveTo(12,0); g.lineTo(-7,7); g.lineTo(-3,0); g.lineTo(-7,-7); g.closePath();
    g.fillStyle='#ff4d6d'; g.fill(); g.strokeStyle='#fff'; g.lineWidth=1.5; g.stroke(); g.restore();
  }
  if(GOAL){
    var gp=P(GOAL[0],GOAL[1]);
    g.beginPath(); g.arc(gp[0],gp[1],7,0,6.284); g.strokeStyle='#3fbf7f'; g.lineWidth=2; g.stroke();
    g.beginPath(); g.moveTo(gp[0]-11,gp[1]); g.lineTo(gp[0]+11,gp[1]);
    g.moveTo(gp[0],gp[1]-11); g.lineTo(gp[0],gp[1]+11); g.stroke();
  }
}
function tapGoal(ev){
  var w=toWorld(ev); if(!w){return}
  GOAL=w;
  if(!TOK){out('目标已标记（未接管，仅预览）：x='+w[0].toFixed(2)+' y='+w[1].toFixed(2));draw();return}
  q('/api/goal',{method:'POST',headers:{'Content-Type':'application/json','X-Token':TOK},
    body:JSON.stringify({x:w[0],y:w[1],th:0})}).then(function(r){
      out(r.ok?'已下发目标 x='+w[0].toFixed(2)+' y='+w[1].toFixed(2):'下发失败：'+(r.error||''))});
  draw();
}
document.addEventListener('click',function(e){
  if(e.target.id==='cv')tapGoal(e);
});

function hive(id,url,ms){
  var el=document.getElementById(id), i=new Image();
  i.onload=function(){if(el.firstChild!==i){el.innerHTML='';el.appendChild(i)}
    setTimeout(function(){hive(id,url,ms)},ms)};
  i.onerror=function(){el.textContent='等待数据 '+url;
    setTimeout(function(){hive(id,url,ms)},3000)};
  i.src=url+'?t='+Date.now();
}
hive('t-map','__MAP__',1200);
hive('t-fuse','__FUSE__',1200);

function state(){
  q('/api/state').then(function(s){ST=s; draw()}).catch(function(){});
}
function status(){
  q('/api/status').then(function(s){
    document.getElementById('d-rad').className='dot '+(s.radar?'on':'off');
    document.getElementById('v-rad').textContent='雷达 '+(s.hz?s.hz.toFixed(1)+'Hz':'断开');
    document.getElementById('d-hec').className='dot '+(s.hector?'on':'warn');
    document.getElementById('v-hec').textContent='建图 '+(s.hector?'运行中':'未运行');
  }).catch(function(){});
}
function stackCmd(c,a){
  if(!TOK){alert('请先接管控制权');return}
  if(a==='stop' && !confirm('停止整个传感器栈？地图和画面都会中断'))return;
  document.getElementById('stackdots').textContent='执行中…';
  q('/api/stack/cmd?c='+c+'&a='+a,{method:'POST',headers:{'X-Token':TOK}})
    .then(function(x){
      if(x.error){alert(x.error);stack();return}
      document.getElementById('stackdots').textContent=(x.ok?'已执行':'执行失败');
      setTimeout(stack,1200);
    }).catch(function(e){document.getElementById('stackdots').textContent='请求失败';});
}
function setMode(){
  var cur=(window._MODE||'radar');
  var next=(cur==='fused'?'radar':'fused');
  var nm={radar:'纯雷达建图',fused:'雷达+深度融合建图'}[next];
  if(!TOK){alert('请先接管控制权');return}
  if(!confirm('切换到「'+nm+'」？\n\n会重启建图程序，当前地图会中断（已保存的不会丢）。'))return;
  document.getElementById('stackdots').textContent='切换中…约 20 秒';
  q('/api/stack/mode?a='+next,{method:'POST',headers:{'X-Token':TOK}})
    .then(function(x){
      if(x.error){alert(x.error);stack();return}
      setTimeout(stack,3000);
    }).catch(function(){document.getElementById('stackdots').textContent='切换失败';});
}
function stack(){
  q('/api/stack').then(function(s){
    var el=document.getElementById('stackdots');
    if(s.error){el.innerHTML='<span style="color:#ff8b9a">栈服务未响应</span>';return}
    window._MODE=s.mode||'radar';
    var mb=document.getElementById('b-mode');
    if(mb)mb.textContent={'fused':'融合建图 ✓','radar':'纯雷达 ✓'}[window._MODE]||'建图模式';
    el.innerHTML=(s.comps||[]).map(function(c){
      return '<span class=st title="'+c.label+(c.note?' · '+c.note:'')+'">'+
        '<i class="dot '+(c.up?'on':'off')+'"></i>'+c.label+'</span>';
    }).join('')||'<span style="color:#7d8794">无组件</span>';
  }).catch(function(){
    var el=document.getElementById('stackdots');
    if(el)el.innerHTML='<span style="color:#ff8b9a">栈服务未响应</span>';
  });
}
function feed(){
  q('/api/activity').then(function(a){
    document.getElementById('feed').innerHTML=a.map(function(x){
      return '<div><span class=t>'+x.t.slice(11)+'</span><span class=u>'+x.u+'</span> '+x.a+
        (x.ok?'':' <span style=color:#ff8b9a>失败</span>')+'</div>'}).join('')||'<div>暂无活动</div>';
  }).catch(function(){});
}
lease();status();feed();state();recList();stack();
setInterval(lease,4000); setInterval(status,3000); setInterval(feed,6000); setInterval(stack,5000);
setInterval(state,700);
setInterval(draw,400);
setInterval(function(){if(TOK)q('/api/lease/heartbeat',{method:'POST',headers:{'X-Token':TOK}})
  .then(function(s){if(s.error)TOK=null;paint(s)})},30000);
</script>
"""
    for k, v in T.items():
        tpl = tpl.replace("__%s__" % k, v)
    return tpl


def page3d(user=None):
    body = """<div class=top><b>3D 点云地图</b>
  <a class=lk href=/live>← 返回控制台</a>
  <span class=flex></span><span id=dir class=dim></span></div>
<div class=two>
  <div class=list id=list>加载中…</div>
  <div class=view><iframe id=fr src="about:blank" title="3D"></iframe>
    <div id=empty class=empty>从左边选一个地图开始看<br><span class=dim>拖拽旋转 · 滚轮缩放 · R 重置</span></div></div>
</div>
<script>
function pick(n){
  document.getElementById('fr').src='/maps3d/'+encodeURIComponent(n);
  document.getElementById('empty').style.display='none';
  [].forEach.call(document.querySelectorAll('.row'),function(r){
    r.className='row'+(r.dataset.n===n?' on':'')});
}
function load(){
  fetch('/api/maps3d',{credentials:'same-origin'}).then(function(r){return r.json()}).then(function(s){
    var el=document.getElementById('list');
    document.getElementById('dir').textContent=s.dir||'';
    if(!s.ok||!s.items.length){
      el.innerHTML='<div class=dim style="padding:14px">'+(s.error||'还没有 3D 地图')+
        '<br><br>在车上跑一次三维采集：<br><code>41-3d-map.bat</code> 或 <code>run3d.sh</code></div>';return}
    el.innerHTML=s.items.map(function(it){
      return '<div class=row data-n="'+it.name+'" onclick="pick(\''+it.name+'\')">'+
        '<div class=nm>'+it.name.replace('.html','')+'</div>'+
        '<div class=meta>'+it.ts+' · '+(it.points||'—')+' 点 · '+it.kb+' KB'+
        (it.png?' · <a href="/maps3d/'+it.name.replace('.html','.png')+'" target=_blank>静态图</a>':'')+
        (it.pcd?' · <a href="/maps3d/'+it.name.replace('.html','.pcd')+'">pcd</a>':'')+
        '</div></div>'}).join('');
  }).catch(function(e){document.getElementById('list').textContent='读取失败 '+e});
}
load();
</script>"""
    return page("3D 地图", body, user, extra="""
<style>
.top{display:flex;align-items:center;gap:14px;padding:12px 18px;border-bottom:1px solid #232733;font-size:14px}
.top b{color:#fff;font-weight:600}.lk{color:#7ac2ff;text-decoration:none;font-size:13px}
.flex{flex:1}.dim{color:#6f7686;font-size:12px}
.two{display:grid;grid-template-columns:340px 1fr;gap:0;height:calc(100vh - 49px)}
.list{overflow:auto;border-right:1px solid #232733;padding:8px}
.row{padding:10px 12px;border-radius:8px;cursor:pointer;border:1px solid transparent}
.row:hover{background:#161a23;border-color:#242a36}
.row.on{background:#12243a;border-color:#2d5f96}
.nm{color:#e6e9f0;font-size:13px;margin-bottom:3px}
.meta{color:#6f7686;font-size:11.5px}.meta a{color:#7ac2ff;text-decoration:none}
.view{position:relative;background:#0a0a0e}
.view iframe{width:100%;height:100%;border:0;display:block}
.empty{position:absolute;inset:0;display:flex;flex-direction:column;align-items:center;justify-content:center;
  color:#7d8296;font-size:14px;line-height:2;pointer-events:none}
code{background:#141821;padding:2px 6px;border-radius:4px;color:#9fc7ff}
@media(max-width:900px){.two{grid-template-columns:1fr;height:auto}
 .view{height:62vh}.list{max-height:34vh;border-right:0;border-bottom:1px solid #232733}}
</style>""")


def admin_page(users, lease):
    rows = "".join(
        "<tr><td>%s</td><td>%s</td><td><form method=post action=/api/user/del style=display:inline>"
        "<input type=hidden name=u value='%s'><button class=ghost style='padding:3px 9px'>删除</button></form></td></tr>"
        % (u["u"], u["role"], u["u"]) for u in users)
    body = """
<div class=card>
  <h1 style='margin-bottom:12px'>控制权</h1>
  <div class=bar><span>当前持有：<b>%s</b></span>
  <form method=post action=/api/lease/force><button class=danger>强制释放</button></form></div>
</div>
<div class=card>
  <h1 style='margin-bottom:12px'>用户</h1>
  <table><tr><th>用户名</th><th>角色</th><th></th></tr>%s</table>
  <form method=post action=/api/user/add class=bar style='margin-top:14px'>
    <input name=u placeholder=用户名>
    <input name=p placeholder=密码>
    <select name=role><option>viewer</option><option>operator</option><option>admin</option></select>
    <button>添加/重置</button>
  </form>
</div>
<div class=card>
  <h1 style='margin-bottom:12px'>审计（最近 80 条）</h1>
  <pre id=au>加载中...</pre>
</div>
<script>fetch('/api/audit').then(r=>r.text()).then(t=>{document.getElementById('au').textContent=t})</script>
""" % (lease["holder"] or "无", rows)
    return body


# ---------------------------------------------------------------- handler ----
class H(BaseHTTPRequestHandler):
    server_version = "XT-HUB/1.0"

    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype="text/html; charset=utf-8", cookie=None):
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        if cookie:
            self.send_header("Set-Cookie", cookie)
        self.end_headers()
        try:
            self.wfile.write(body)
        except Exception:
            pass

    def _json(self, obj, code=200):
        self._send(code, json.dumps(obj, ensure_ascii=False), "application/json; charset=utf-8")

    def _json_body(self):
        try:
            n = int(self.headers.get("Content-Length", 0))
            if n <= 0:
                return {}
            return json.loads(self.rfile.read(n).decode("utf-8", "replace"))
        except Exception:
            return {}

    def _form(self):
        n = int(self.headers.get("Content-Length") or 0)
        return parse_qs(self.rfile.read(n).decode("utf-8")) if n else {}

    # ------------------------------------------------------------- GET ----
    def do_GET(self):
        u = urlparse(self.path)
        p = u.path
        qs = parse_qs(u.query)
        s = session_of(self)
        if DEMO and p.startswith("/demo/"):
            t = time.time() - _T0
            key = p.split("?")[0]
            return self._send(200, _demo_png(key, t), "image/png")
        if p == "/healthz":
            return self._send(200, "ok %s demo=%s dry=%s" % (time.strftime("%H:%M:%S"), DEMO, DRY),
                              "text/plain; charset=utf-8")
        if p == "/":
            return self._send(200, page("登录", LOGIN % ""))
        if p == "/logout":
            return self._send(200, _go("/", "已退出登录。"),
                              cookie="xt=; Path=/; Max-Age=0",
                              ctype="text/html; charset=utf-8")
        if not s:
            return self._send(200, page("登录", LOGIN % "<div class=hint>请先登录</div>"))
        if p == "/live":
            return self._send(200, page("控制台", live_page(s, CFG["robot"]) + "", s))
        if p == "/3d":
            return self._send(200, page3d(s))
        if p == "/api/maps3d":
            return self._json(list3d())
        if p.startswith("/maps3d/"):
            data, ctype = read3d(unquote(p[len("/maps3d/"):]))
            if data is None:
                return self._send(404, "not found")
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            self.wfile.write(data)
            return
        if p == "/admin":
            if s["r"] != "admin":
                return self._send(403, page("拒绝", "<div class=card>需要管理员权限</div>", s))
            return self._send(200, page("管理", admin_page(CFG["users"], lease_state()), s))
        if p == "/api/lease":
            st = lease_state()
            return self._json(st)
        if p == "/api/status":
            return self._json(robot_status())
        if p == "/api/stack":
            if DEMO:
                return self._json(demo_stack())
            try:
                return self._json(stack_proxy("/status"))
            except Exception as e:
                return self._json({"error": "传感器栈服务未响应: %s" % e, "comps": []})
        if p == "/api/activity":
            return self._json(recent_activity())
        if p == "/api/state":
            return self._json(api_state())
        if p == "/api/rec/list":
            return self._json({"ok": True, "items": rec_list(), "rec": {"on": _REC["on"],
                              "name": _REC["name"], "frames": len(_REC["frames"])}})
        if p == "/api/rec/get":
            return self._json(rec_get((qs.get("name") or [""])[0]))
        if p == "/api/audit":
            if s["r"] != "admin":
                return self._json({"error": "forbidden"}, 403)
            lines = []
            if os.path.exists(AUDIT):
                with open(AUDIT, "r", encoding="utf-8") as f:
                    lines = f.readlines()[-80:]
            return self._send(200, "".join(lines), "text/plain; charset=utf-8")
        if p == "/health":
            return self._json({"ok": True, "user": s["u"]})
        return self._send(404, "404")

    def _redir(self, to):
        self.send_response(302)
        self.send_header("Location", to)
        self.send_header("Content-Length", "0")
        self.end_headers()

    # ------------------------------------------------------------ POST ----
    def do_POST(self):
        u = urlparse(self.path)
        p, qs = u.path, parse_qs(u.query)
        s = session_of(self)

        if p == "/login":
            f = self._form()
            name = (f.get("u") or [""])[0]
            pw = (f.get("p") or [""])[0]
            usr = check_pw(name, pw)
            if not usr:
                audit(name or "?", "login", "密码错误", False)
                return self._send(200, page("登录", LOGIN % "<div class=err>用户名或密码错误</div>"))
            audit(name, "login", "", True)
            return self._send(200, _go("/live", "登录成功，正在进入控制台…"),
                              cookie="xt=%s; Path=/; Max-Age=43200; HttpOnly" % make_session(name),
                              ctype="text/html; charset=utf-8")

        if not s:
            return self._json({"error": "未登录"}, 401)
        tok = self.headers.get("X-Token") or (qs.get("token") or [""])[0]

        if p == "/api/lease/claim":
            with LOCK:
                cur = lease_state()
                if cur["holder"] and cur["holder"] != s["u"]:
                    return self._json({"error": "%s 正在操作" % cur["holder"]})
                LEASE.update({"holder": s["u"], "token": base64.b16encode(os.urandom(12)).decode(),
                              "exp": time.time() + CFG["lease_ttl"]})
                audit(s["u"], "claim", "", True)
                return self._json(dict(LEASE))
        if p == "/api/lease/heartbeat":
            with LOCK:
                if not LEASE["holder"] or LEASE["token"] != tok:
                    return self._json({"error": "租约失效", "holder": None, "exp": 0})
                LEASE["exp"] = time.time() + CFG["lease_ttl"]
                return self._json(dict(LEASE))
        if p == "/api/lease/release":
            with LOCK:
                if LEASE["token"] == tok or s["r"] == "admin":
                    LEASE.update({"holder": None, "token": None, "exp": 0})
                    audit(s["u"], "release", "", True)
                return self._json(lease_state())
        if p == "/api/lease/force":
            if s["r"] != "admin":
                return self._send(403, "forbidden")
            with LOCK:
                LEASE.update({"holder": None, "token": None, "exp": 0})
            audit(s["u"], "force-release", "", True)
            return self._redir("/admin")
        if p == "/api/cmd":
            a = (qs.get("action") or [""])[0]
            if a not in WHITELIST:
                return self._json({"error": "未知动作"})
            st = lease_state()
            if st["token"] != tok:
                return self._json({"error": "没有控制权，请先接管"})
            rc, out = run_slam(a)
            audit(s["u"], "cmd:" + a, out[:200].replace("\n", " "), rc == 0)
            return self._json({"ok": rc == 0, "rc": rc, "out": out})
        if p == "/api/stack/cmd":
            st = lease_state()
            if st["token"] != tok:
                return self._json({"error": "没有控制权，请先接管"})
            c = (qs.get("c") or ["all"])[0]
            a = (qs.get("a") or ["start"])[0]
            if a not in ("start", "stop", "restart"):
                return self._json({"error": "a 只能是 start/stop/restart"})
            if DEMO:
                audit(s["u"], "stack:" + a, c, True)
                return self._json({"ok": True, "demo": True, "comp": c, "action": a,
                                   "out": "[demo] 演示模式不会真的启停"})
            try:
                r = stack_proxy("/cmd?c=%s&a=%s" % (c, a), "POST", timeout=180)
                audit(s["u"], "stack:%s:%s" % (a, c), str(r.get("ok")), bool(r.get("ok")))
                return self._json(r)
            except Exception as e:
                audit(s["u"], "stack:%s:%s" % (a, c), str(e)[:80], False)
                return self._json({"error": "传感器栈服务未响应: %s" % e})
        if p == "/api/stack/mode":
            st = lease_state()
            if st["token"] != tok:
                return self._json({"error": "没有控制权，请先接管"})
            m = (qs.get("a") or ["radar"])[0]
            if m not in ("radar", "fused"):
                return self._json({"error": "a 只能是 radar / fused"})
            if DEMO:
                audit(s["u"], "mode:" + m, "demo", True)
                return self._json({"ok": True, "demo": True, "mode": m})
            try:
                r = stack_proxy("/mode?a=" + m, "POST", timeout=240)
                audit(s["u"], "mode:" + m, str(r.get("ok")), bool(r.get("ok")))
                return self._json(r)
            except Exception as e:
                audit(s["u"], "mode:" + m, str(e)[:80], False)
                return self._json({"error": "传感器栈服务未响应: %s" % e})
        if p == "/api/rec/start":
            st = lease_state()
            if st["token"] != tok:
                return self._json({"error": "没有控制权，请先接管"})
            r = rec_start((qs.get("name") or [""])[0])
            if r.get("ok"):
                audit(s["u"], "rec:start", r.get("name", ""), True)
            return self._json(r)
        if p == "/api/rec/stop":
            st = lease_state()
            if st["token"] != tok:
                return self._json({"error": "没有控制权，请先接管"})
            r = rec_stop()
            audit(s["u"], "rec:stop", "%s frames" % r.get("frames", 0), True)
            return self._json(r)
        if p == "/api/teleop":
            st = lease_state()
            if st["token"] != tok:
                return self._json({"error": "没有控制权，请先接管"})
            body = self._json_body()
            lin = float(body.get("lin", 0) or 0)
            ang = float(body.get("ang", 0) or 0)
            if DEMO or DRY:
                return self._json({"ok": True, "lin": lin, "ang": ang, "echo": True})
            try:
                return self._json(_bridge("/cmd", {"lin": lin, "ang": ang}, 1.2))
            except Exception as e:
                return self._json({"ok": False, "error": str(e)})
        if p == "/api/goal":
            st = lease_state()
            if st["token"] != tok:
                return self._json({"error": "没有控制权，请先接管"})
            body = self._json_body()
            if DEMO or DRY:
                return self._json({"ok": True, "goal": [body.get("x"), body.get("y"), body.get("th")], "echo": True})
            try:
                return self._json(_bridge("/goal", body, 2.0))
            except Exception as e:
                return self._json({"ok": False, "error": str(e)})
        if p == "/api/user/add":
            if s["r"] != "admin":
                return self._send(403, "forbidden")
            f = self._form()
            n = (f.get("u") or [""])[0].strip()
            pw = (f.get("p") or [""])[0]
            r = (f.get("role") or ["viewer"])[0]
            if n and pw:
                add_user(n, pw, r)
                audit(s["u"], "user:add", n + "/" + r, True)
            return self._redir("/admin")
        if p == "/api/user/del":
            if s["r"] != "admin":
                return self._send(403, "forbidden")
            f = self._form()
            n = (f.get("u") or [""])[0]
            CFG["users"] = [x for x in CFG["users"] if x["u"] != n]
            save_conf(CFG)
            audit(s["u"], "user:del", n, True)
            return self._redir("/admin")
        return self._send(404, "404")


def _start_reloader():
    """--reload: 源码改动后自动重启进程（开发用）"""
    if getattr(sys, "frozen", False):
        return
    try:
        path = os.path.abspath(__file__)
        if not os.path.isfile(path):
            return
    except Exception:
        return

    def _watch():
        m = os.path.getmtime(path)
        while True:
            time.sleep(2)
            try:
                n = os.path.getmtime(path)
            except OSError:
                continue
            if n != m:
                print("[reload] hub_server.py changed, restarting...", flush=True)
                os.execv(sys.executable, [sys.executable] + sys.argv[:])

    threading.Thread(target=_watch, daemon=True).start()


def main():
    port = CFG["port"]
    for i, a in enumerate(sys.argv):
        if a == "--port" and i + 1 < len(sys.argv):
            port = int(sys.argv[i + 1])
    if "--init-admin" in sys.argv:
        i = sys.argv.index("--init-admin")
        pw = sys.argv[i + 1] if i + 1 < len(sys.argv) else "admin123"
        add_user("admin", pw, "admin")
        print("admin 已创建，密码：%s" % pw)
        return
    if not CFG["users"]:
        add_user("admin", "admin123", "admin")
        print("首次运行：已创建 admin / admin123 —— 请立刻登录改密码")
    class Srv(ThreadingHTTPServer):
        daemon_threads = True
        allow_reuse_address = True
        request_queue_size = 64
    if "--reload" in sys.argv:
        _start_reloader()

    srv = Srv(("0.0.0.0", port), H)
    print("XT-HUB on http://0.0.0.0:%d  (dry-run=%s)" % (port, DRY))
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
