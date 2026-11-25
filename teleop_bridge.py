#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
XT-R1 遥操作 + 位姿桥  (python2 / ROS kinetic|melodic)

HTTP 8099
  GET  /health           存活、/cmd_vel 订阅者数、位姿新鲜度
  GET  /state            {x,y,th,traj,meta{hz,res,ox,oy,w,h}}
  POST /cmd   {"lin":0.15,"ang":0}    设定目标速度（10Hz 持续发布，0.6s 无包自动停）
  POST /stop                          立即停车
  POST /goal  {"x":..,"y":..,"th":..} 发 /move_base_simple/goal（需导航栈）

安全：限速 LIN<=0.2 m/s、ANG<=1.0 rad/s；看门狗 0.6s。
"""
import os
import json
import math
import time
import threading
import BaseHTTPServer
import SocketServer
import subprocess

import rospy
import tf
from geometry_msgs.msg import Twist, PoseStamped

DATA = '/home/xtrobot/data'
PORT = 8099
MAX_LIN = 0.20
MAX_ANG = 1.00
WATCHDOG = 0.6
PUB_HZ = 10.0

_lock = threading.Lock()
_target = [0.0, 0.0]      # lin, ang
_last_cmd = 0.0
_stopping = False

_pose = None              # (x, y, th)
_pose_ts = 0.0
_traj = []                # [[x,y], ...]
_sub_count = 0


def clamp(v, m):
    return max(-m, min(m, v))


def read_meta():
    """从 map_saver 产出的 live_map.yaml / .pgm 读地图元信息"""
    meta = {'res': 0.05, 'ox': -25.6, 'oy': -25.6, 'w': 1024, 'h': 1024, 'ts': 0, 'ok': False}
    try:
        y = os.path.join(DATA, 'live_map.yaml')
        for ln in open(y, 'r'):
            ln = ln.strip()
            if ln.startswith('resolution:'):
                meta['res'] = float(ln.split(':', 1)[1])
            elif ln.startswith('origin:'):
                v = ln.split(':', 1)[1].strip().strip('[]').split(',')
                meta['ox'] = float(v[0])
                meta['oy'] = float(v[1])
    except Exception:
        return meta
    try:
        p = os.path.join(DATA, 'live_map.pgm')
        f = open(p, 'rb')
        keep = []
        for _ in range(6):
            ln = f.readline()
            if not ln:
                break
            if ln.startswith('#'):
                continue
            keep.append(ln)
        f.close()
        toks = ' '.join(keep).split()
        if toks and toks[0] == 'P5':
            meta['w'] = int(toks[1])
            meta['h'] = int(toks[2])
        meta['ts'] = os.path.getmtime(p)
        meta['ok'] = True
    except Exception:
        pass
    return meta


class Node(object):
    def __init__(self):
        self.pub = rospy.Publisher('/cmd_vel', Twist, queue_size=1)
        self.goal_pub = rospy.Publisher('/move_base_simple/goal', PoseStamped, queue_size=1)
        self.listener = tf.TransformListener()
        threading.Thread(target=self._pub_loop).start()
        threading.Thread(target=self._pose_loop).start()

    def _pub_loop(self):
        global _stopping
        r = rospy.Rate(PUB_HZ)
        while not rospy.is_shutdown():
            with _lock:
                lin, ang = _target[0], _target[1]
                idle = (time.time() - _last_cmd) > WATCHDOG
            if idle:
                lin, ang = 0.0, 0.0
                with _lock:
                    _target[0] = 0.0
                    _target[1] = 0.0
            t = Twist()
            t.linear.x = lin
            t.angular.z = ang
            try:
                self.pub.publish(t)
                global _sub_count
                _sub_count = self.pub.get_num_connections()
            except Exception:
                pass
            r.sleep()

    def _pose_loop(self):
        global _pose, _pose_ts
        r = rospy.Rate(PUB_HZ)
        while not rospy.is_shutdown():
            try:
                (trans, rot) = self.listener.lookupTransform('/map', '/base_footprint', rospy.Time(0))
                (_, _, th) = tf.transformations.euler_from_quaternion(rot)
                _pose = (trans[0], trans[1], th)
                _pose_ts = time.time()
                if not _traj or math.hypot(trans[0] - _traj[-1][0],
                                           trans[1] - _traj[-1][1]) > 0.05:
                    _traj.append([round(trans[0], 3), round(trans[1], 3)])
                    if len(_traj) > 600:
                        del _traj[:200]
            except Exception:
                pass
            r.sleep()

    def state(self):
        meta = read_meta()
        st = {
            'ok': True,
            'pose': list(_pose) if _pose else None,
            'age': round(time.time() - _pose_ts, 2) if _pose else None,
            'traj': _traj[-400:],
            'meta': meta,
            'cmd_subs': _sub_count,
            'target': {'lin': round(_target[0], 3), 'ang': round(_target[1], 3)},
            'ts': time.time(),
        }
        return st

    def set_cmd(self, lin, ang):
        global _last_cmd
        with _lock:
            _target[0] = clamp(lin, MAX_LIN)
            _target[1] = clamp(ang, MAX_ANG)
            _last_cmd = time.time()
        return {'ok': True, 'lin': _target[0], 'ang': _target[1]}

    def stop(self):
        global _last_cmd
        with _lock:
            _target[0] = 0.0
            _target[1] = 0.0
            _last_cmd = 0.0
        return {'ok': True, 'stopped': True}

    def send_goal(self, x, y, th):
        if self.goal_pub.get_num_connections() == 0:
            return {'ok': False,
                    'error': '没有节点订阅 /move_base_simple/goal（导航栈未启动，或底盘无里程计）'}
        ps = PoseStamped()
        ps.header.stamp = rospy.Time.now()
        ps.header.frame_id = 'map'
        ps.pose.position.x = float(x)
        ps.pose.position.y = float(y)
        ps.pose.position.z = 0.0
        ps.pose.orientation.z = math.sin(float(th) / 2.0)
        ps.pose.orientation.w = math.cos(float(th) / 2.0)
        self.goal_pub.publish(ps)
        return {'ok': True, 'goal': [float(x), float(y), float(th)]}


NODE = None


BAGDIR = os.path.join(DATA, 'bags')
_rec = {'p': None, 'path': None, 't0': 0.0}


def list_bags():
    out = []
    try:
        for fn in os.listdir(BAGDIR):
            if not fn.endswith('.bag'):
                continue
            fp = os.path.join(BAGDIR, fn)
            out.append({'name': fn[:-4], 'size': os.path.getsize(fp),
                        'ts': os.path.getmtime(fp)})
    except Exception:
        pass
    out.sort(key=lambda x: x['ts'], reverse=True)
    return out


def rec_status():
    running = bool(_rec['p'] and _rec['p'].poll() is None)
    d = {'running': running, 'name': _rec['path'] and os.path.basename(_rec['path'])[:-4]}
    if running:
        d['sec'] = round(time.time() - _rec['t0'], 1)
        try:
            d['size'] = os.path.getsize(_rec['path'])
        except Exception:
            d['size'] = 0
    return d


def rec_start(name):
    if _rec['p'] and _rec['p'].poll() is None:
        return {'ok': False, 'error': 'already recording'}
    try:
        os.makedirs(BAGDIR)
    except Exception:
        pass
    name = (name or time.strftime('rec_%Y%m%d_%H%M%S')).replace('/', '_').replace(' ', '_')
    path = os.path.join(BAGDIR, name + '.bag')
    try:
        _rec['p'] = subprocess.Popen(['rosbag', 'record', '-O', path, '/scan', '/tf', '/map'],
                                     stdout=open('/tmp/bagrec.log', 'w'),
                                     stderr=subprocess.STDOUT)
        _rec['path'] = path
        _rec['t0'] = time.time()
        return {'ok': True, 'name': name, 'path': path}
    except Exception as e:
        return {'ok': False, 'error': str(e)}


def rec_stop():
    p = _rec['p']
    if not p or p.poll() is not None:
        return {'ok': True, 'running': False}
    try:
        p.terminate()
        for _ in range(40):
            if p.poll() is not None:
                break
            time.sleep(0.1)
        if p.poll() is None:
            p.kill()
    except Exception:
        pass
    size = 0
    try:
        size = os.path.getsize(_rec['path'])
    except Exception:
        pass
    return {'ok': True, 'running': False, 'size': size,
            'name': os.path.basename(_rec['path'])[:-4]}


class H(BaseHTTPServer.BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'

    def log_message(self, fmt, *a):
        pass

    def _send(self, code, obj, ctype='application/json; charset=utf-8'):
        if not isinstance(obj, (str, bytes)):
            obj = json.dumps(obj)
        self.send_response(code)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', str(len(obj)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(obj)

    def _body(self):
        try:
            n = int(self.headers.get('Content-Length', 0))
            if n <= 0:
                return {}
            return json.loads(self.rfile.read(n))
        except Exception:
            return {}

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET,POST,OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.send_header('Content-Length', '0')
        self.end_headers()

    def do_GET(self):
        p = self.path.split('?')[0]
        if p.startswith('/health'):
            return self._send(200, {'ok': True, 'cmd_subs': _sub_count,
                                    'age': round(time.time() - _pose_ts, 2) if _pose else None,
                                    'ros': not rospy.is_shutdown()})
        if p.startswith('/state'):
            return self._send(200, NODE.state())
        if p.startswith('/bags'):
            return self._send(200, {'ok': True, 'bags': list_bags(), 'rec': rec_status()})
        return self._send(404, {'error': 'not found'})

    def do_POST(self):
        p = self.path.split('?')[0]
        d = self._body()
        if p.startswith('/cmd'):
            try:
                return self._send(200, NODE.set_cmd(float(d.get('lin', 0.0)),
                                                    float(d.get('ang', 0.0))))
            except Exception as e:
                return self._send(400, {'error': str(e)})
        if p.startswith('/stop'):
            return self._send(200, NODE.stop())
        if p.startswith('/rec/start'):
            return self._send(200, rec_start(d.get('name')))
        if p.startswith('/rec/stop'):
            return self._send(200, rec_stop())
        if p.startswith('/goal'):
            try:
                return self._send(200, NODE.send_goal(d.get('x', 0), d.get('y', 0), d.get('th', 0)))
            except Exception as e:
                return self._send(400, {'error': str(e)})
        return self._send(404, {'error': 'not found'})


def main():
    global NODE
    rospy.init_node('xt_teleop_bridge', anonymous=False)
    NODE = Node()
    srv = SocketServer.ThreadingTCPServer(('0.0.0.0', PORT), H)
    srv.daemon_threads = True
    print('xt_teleop_bridge on :%d  (Ctrl-C to quit)' % PORT)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        NODE.stop()
        print('stopped')


if __name__ == '__main__':
    main()
