#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
robot_stack.py - 机器人传感器栈统一管理器（跑在机器人上）

把散落在一堆 bat/sh 里的雷达、深度相机、建图、画面服务收拢成一个带状态的小服务，
供 XT-HUB 网页点按钮启停。

用法:
    python3 robot_stack.py                 # 监听 0.0.0.0:8100
    python3 robot_stack.py --port 8101
    python3 robot_stack.py --dry           # 只回显命令，不真跑（调试用）

接口:
    GET  /health              -> {"ok":true,...}
    GET  /status              -> 每个组件 up/port/detail + 汇总
    POST /cmd?c=<comp>&a=start|stop|restart
    POST /cmd?c=all&a=start|stop          # 按依赖顺序整栈启停
    GET  /log?c=<comp>&n=40   -> 组件最近日志

依赖: 纯标准库 + bash + 机器人上已有的 slam_ctl.sh / fuse_ctl.sh。
"""
import json
import os
import re
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

HOME = os.path.expanduser("~")
DRY = "--dry" in sys.argv
LOCK = threading.Lock()          # 启停串行化，避免两个人在网页上同时点
LAST = {}                        # comp -> {"t":ts,"action":...,"out":...}

SH = "bash -lc "

# ---------------------------------------------------------------- 组件定义
# check: (pgrep 模式, 监听端口, 日志文件)
# 顺序即依赖顺序：ROS 主节点 -> 雷达/建图 -> 相机 -> 融合 -> 遥控桥
COMPS = [
    dict(
        name="slam", label="雷达 + 建图", check=("hector_[m]apping", 8091, "/tmp/hector.log"),
        start=SH + "~/slam_ctl.sh start", stop=SH + "~/slam_ctl.sh stop",
        note="roscore + rplidar + hector + mapview(:8091)",
    ),
    dict(
        name="camera", label="深度相机驱动", check=("astra_camera_nod[e]|uvc_camera_nod[e]", 0, "/tmp/astra.log"),
        start=SH + "~/start_astra.sh", stop=SH + "'pkill -f astra_camera_nod[e]; pkill -f uvc_camera_nod[e]'",
        note="调 start_astra.sh（Astra 深度 + RGB）",
    ),
    dict(
        name="fuse", label="雷达+深度融合画面", check=("fuse_[v]iew.py", 8093, HOME + "/fuse.log"),
        start=SH + "~/fuse_ctl.sh start", stop=SH + "~/fuse_ctl.sh stop",
        note=":8093/fuse.png",
    ),
    dict(
        name="cam", label="相机画面服务", check=("cam_serve[r].py", 8090, "/tmp/cam_server.log"),
        start=SH + "'cd ~ && setsid nohup python cam_server.py > /tmp/cam_server.log 2>&1 < /dev/null &'",
        stop=SH + "'pkill -9 -f cam_serve[r].py'",
        note=":8090/rgb /depth /ir",
    ),
    dict(
        name="bridge", label="遥控桥", check=("teleop_[b]ridge.py", 8099, "/tmp/bridge.log"),
        start=SH + "'cd ~ && setsid nohup python teleop_bridge.py > /tmp/bridge.log 2>&1 < /dev/null &'",
        stop=SH + "'pkill -9 -f teleop_[b]ridge.py'",
        note=":8099 位姿/速度/目标点",
    ),
]
BY_NAME = {c["name"]: c for c in COMPS}
START_ORDER = ["slam", "camera", "fuse", "cam", "bridge"]


# ---------------------------------------------------------------- 建图模式
# radar: hector 订阅 /scan        -> ~/slam_ctl.sh start
# fused: hector 订阅 /scan_fused  -> ~/slam2_ctl.sh start（雷达+深度融合）
MODES = {
    "radar": dict(label="纯雷达", script=SH + "~/slam_ctl.sh start", topic="scan"),
    "fused": dict(label="雷达+深度融合", script=SH + "~/slam2_ctl.sh start", topic="scan_fused"),
}


def detect_mode():
    """看 hector 进程的命令行里订的是哪个话题"""
    if DRY:
        return "radar"
    code, out = sh("pgrep -af 'hector_[m]apping' | head -1", timeout=10)
    if not out or code != 0:
        return ""
    if "_scan_topic:=scan_fused" in out:
        return "fused"
    if "_scan_topic:=scan" in out:
        return "radar"
    return ""


# ---------------------------------------------------------------- 三维采集
CAP = {"on": False, "t0": 0, "secs": 0, "phase": "", "out": "", "log": "", "ok": None}
CAP_LOCK = threading.Lock()
PCD = HOME + "/data/map3d.pcd"
MAP3D_DIR = HOME + "/3d_maps"


def _cap_set(**kw):
    CAP.update(kw)


def capture_worker(secs):
    try:
        _cap_set(on=True, t0=int(time.time()), secs=secs, phase="准备", out="", log="", ok=None)
        sh("rm -f %s" % PCD, timeout=10)
        _cap_set(phase="启动 cloud3d")
        sh("pkill -9 -f cloud3d 2>/dev/null; true", timeout=10)
        code, out = sh("cd ~ && setsid nohup python cloud3d.py > /tmp/c3d.log 2>&1 < /dev/null &", timeout=20)
        _cap_set(phase="累积点云 %d 秒" % secs)
        time.sleep(secs)
        _cap_set(phase="收尾")
        sh("pkill -9 -f cloud3d 2>/dev/null; true", timeout=10)
        time.sleep(1)
        if not os.path.exists(PCD):
            _cap_set(phase="失败", ok=False, log="没生成 %s（cloud3d 可能没起来）\n" % PCD + tail_file("/tmp/c3d.log"))
            return
        _cap_set(phase="生成 HTML")
        code, out = sh("python ~/make3d_html.py %s %s" % (PCD, MAP3D_DIR), timeout=120)
        if code != 0:
            _cap_set(phase="失败", ok=False, log=out)
            return
        m = re.search(r"/[^\s]*map3d_[0-9_]+(\w*)\.html|(map3d_[0-9_]+\.html)", out)
        name = m.group(0) if m else ""
        _cap_set(phase="完成", ok=True, out=name, log=out)
    except Exception as e:
        _cap_set(phase="异常", ok=False, log=str(e))
    finally:
        _cap_set(on=False)


# ---------------------------------------------------------------- 工具
def sh(cmd, timeout=90):
    """跑一条 shell，返回 (code, 输出尾部)"""
    if DRY:
        return 0, "[dry] " + cmd
    try:
        p = subprocess.run(cmd, shell=True, stdout=subprocess.PIPE,
                           stderr=subprocess.STDOUT, timeout=timeout)
        out = p.stdout.decode("utf-8", "replace")
        return p.returncode, out.strip()[-1500:]
    except subprocess.TimeoutExpired:
        return 124, "timeout after %ss" % timeout


def pgrep_alive(pattern):
    code, _ = sh("pgrep -f '%s' >/dev/null 2>&1" % pattern, timeout=10)
    return code == 0


def port_open(port):
    if not port:
        return None
    code, _ = sh("ss -lnt 2>/dev/null | grep -q ':%d '" % port, timeout=10)
    return code == 0


def tail_file(path, n=40):
    if not path or not os.path.exists(path):
        return ""
    try:
        with open(path, "rb") as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            f.seek(max(0, size - 8192))
            data = f.read().decode("utf-8", "replace")
        return "\n".join(data.splitlines()[-n:])
    except Exception as e:
        return "read fail: %s" % e


def _hostname():
    try:
        return os.uname()[1]
    except Exception:
        return os.environ.get("COMPUTERNAME", "unknown")


def comp_status(c):
    alive = pgrep_alive(c["check"][0])
    port = port_open(c["check"][1])
    return {
        "name": c["name"], "label": c["label"], "note": c["note"],
        "up": bool(alive), "port": port, "port_no": c["check"][1],
        "last": LAST.get(c["name"]),
    }


def do_action(name, action):
    c = BY_NAME.get(name)
    if not c:
        return {"error": "unknown component: %s" % name}
    cmd = {"start": c["start"], "stop": c["stop"],
           "restart": c["stop"] + " ; sleep 2 ; " + c["start"]}[action]
    t0 = time.time()
    code, out = sh(cmd)
    LAST[name] = {"t": int(time.time()), "action": action,
                  "ok": code == 0, "secs": round(time.time() - t0, 1)}
    return {"ok": code == 0, "comp": name, "action": action,
            "secs": round(time.time() - t0, 1), "out": out}


# ---------------------------------------------------------------- HTTP
class H(BaseHTTPRequestHandler):
    server_version = "robot-stack/1.0"

    def log_message(self, *a):
        pass

    def _json(self, obj, code=200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        u = urlparse(self.path)
        qs = parse_qs(u.query)
        p = u.path

        if p == "/health":
            return self._json({"ok": True, "ts": time.strftime("%H:%M:%S"), "dry": DRY})

        if p == "/status":
            comps = [comp_status(c) for c in COMPS]
            up = sum(1 for c in comps if c["up"])
            return self._json({
                "ok": True, "ts": time.strftime("%H:%M:%S"),
                "host": _hostname(), "dry": DRY, "mode": detect_mode(),
                "up": up, "total": len(comps),
                "comps": comps,
            })

        if p == "/capture3d":
            st = dict(CAP)
            if st["t0"] and st["on"]:
                st["elapsed"] = int(time.time()) - st["t0"]
            return self._json({"ok": True, "cap": st, "dir": MAP3D_DIR})

        if p == "/log":
            c = BY_NAME.get((qs.get("c") or [""])[0])
            if not c:
                return self._json({"error": "unknown component"}, 400)
            n = int((qs.get("n") or ["40"])[0])
            return self._json({"ok": True, "comp": c["name"], "log": tail_file(c["check"][2], n)})

        return self._json({"error": "not found"}, 404)

    def do_POST(self):
        u = urlparse(self.path)
        qs = parse_qs(u.query)
        if u.path == "/capture3d":
            secs = int((qs.get("secs") or ["30"])[0])
            secs = max(5, min(180, secs))
            if not CAP_LOCK.acquire(blocking=False):
                return self._json({"error": "已经在采集了"}, 409)
            t = threading.Thread(target=lambda: (capture_worker(secs), CAP_LOCK.release()))
            t.daemon = True
            t.start()
            return self._json({"ok": True, "started": True, "secs": secs})
        if u.path == "/mode":
            m = (qs.get("a") or [""])[0]
            if m not in MODES:
                return self._json({"error": "a 只能是 radar / fused"}, 400)
            if not LOCK.acquire(blocking=False):
                return self._json({"error": "另一个操作正在进行，请稍后"}, 409)
            try:
                code, out = sh(MODES[m]["script"], timeout=180)
                LAST["mode"] = {"t": int(time.time()), "action": m, "ok": code == 0}
                return self._json({"ok": code == 0, "mode": m,
                                   "label": MODES[m]["label"],
                                   "topic": MODES[m]["topic"], "out": out[-800:]})
            finally:
                LOCK.release()
        if u.path != "/cmd":
            return self._json({"error": "not found"}, 404)
        name = (qs.get("c") or [""])[0]
        action = (qs.get("a") or ["start"])[0]
        if action not in ("start", "stop", "restart"):
            return self._json({"error": "bad action"}, 400)
        if not LOCK.acquire(blocking=False):
            return self._json({"error": "另一个操作正在进行，请稍后"}, 409)
        try:
            if name == "all":
                order = START_ORDER if action == "start" else list(reversed(START_ORDER))
                res = []
                for nm in order:
                    res.append(do_action(nm, action))
                    time.sleep(1)
                return self._json({"ok": all(r.get("ok") for r in res), "all": res})
            return self._json(do_action(name, action))
        finally:
            LOCK.release()


def main():
    port = 8100
    if "--port" in sys.argv:
        port = int(sys.argv[sys.argv.index("--port") + 1])
    srv = ThreadingHTTPServer(("0.0.0.0", port), H)
    srv.daemon_threads = True
    print("robot_stack on http://0.0.0.0:%d  dry=%s" % (port, DRY))
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
