#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""低延迟 MJPEG 服务器（python2 + ROS melodic）

设计要点（v2）：
1. ROS 回调只存原始 Image，**不做编码** —— 没人在看的流不消耗 CPU；
2. 有人拉流时才编码，且编码结果按时间戳缓存，多客户端共享同一帧；
3. 编码前等比缩小（彩色 <=480 宽、深度 <=320 宽）、质量 55，减少 CPU 与带宽；
4. 整帧一次性写出 + TCP_NODELAY，避免 Nagle 与分片等待；
5. 每路最多 20fps，丢旧帧不排队。

路由：/rgb /depth /ir /snap/<name> /
"""
import threading
import time

import cv2
import rospy
from BaseHTTPServer import BaseHTTPRequestHandler, HTTPServer
from SocketServer import ThreadingMixIn
from sensor_msgs.msg import Image
from cv_bridge import CvBridge

STREAMS = {
    'rgb': '/rgb_view',
    'depth': '/depth_colored',
    'ir': '/camera/ir/image',
}
MAXW = {'rgb': 480, 'depth': 320, 'ir': 320}
QUALITY = 55
FRAME_INTERVAL = 1.0 / 20.0

raw = {}          # name -> (msg, stamp)
enc = {}          # name -> (jpeg_bytes, stamp)
lock = threading.Lock()


class Grabber(object):
    def __init__(self, name, topic):
        self.name = name
        self.bridge = CvBridge()
        self.sub = rospy.Subscriber(topic, Image, self.cb, queue_size=1, buff_size=2 ** 24)
        rospy.loginfo('%s <- %s' % (name, topic))

    def cb(self, msg):
        with lock:
            raw[self.name] = (msg, time.time())


def encoded(name):
    """按需编码；同一时间戳只编一次（多客户端共享）。"""
    with lock:
        item = raw.get(name)
        cached = enc.get(name)
    if not item:
        return None, 0
    msg, ts = item
    if cached and cached[1] == ts:
        return cached[0], ts
    try:
        img = _bridge.imgmsg_to_cv2(msg, 'bgr8' if msg.encoding in ('rgb8', 'bgr8') else 'mono8')
        if len(img.shape) == 2:
            img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
        h, w = img.shape[:2]
        mw = MAXW.get(name, 480)
        if w > mw:
            nh = int(h * mw / float(w))
            img = cv2.resize(img, (mw, nh), interpolation=cv2.INTER_AREA)
        ok, buf = cv2.imencode('.jpg', img, [cv2.IMWRITE_JPEG_QUALITY, QUALITY])
        if not ok:
            return None, ts
        data = buf.tostring()
        with lock:
            enc[name] = (data, ts)
        return data, ts
    except Exception:
        return None, ts


_bridge = CvBridge()


class Handler(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.0'

    def setup(self):
        BaseHTTPRequestHandler.setup(self)
        try:
            import socket
            self.connection.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        except Exception:
            pass

    def log_message(self, fmt, *args):
        pass

    def do_GET(self):
        path = self.path.split('?')[0].strip('/')
        if path in ('', 'index.html'):
            return self.send_page()
        if path.startswith('snap/'):
            data, _ = encoded(path[5:])
            if not data:
                self.send_response(503)
                self.end_headers()
                return
            self.send_response(200)
            self.send_header('Content-Type', 'image/jpeg')
            self.send_header('Content-Length', str(len(data)))
            self.send_header('Cache-Control', 'no-store')
            self.end_headers()
            self.wfile.write(data)
            return
        if path in STREAMS:
            return self.stream(path)
        self.send_response(404)
        self.end_headers()

    def stream(self, name):
        self.send_response(200)
        self.send_header('Age', '0')
        self.send_header('Cache-Control', 'no-cache, private')
        self.send_header('Pragma', 'no-cache')
        self.send_header('Content-Type', 'multipart/x-mixed-replace; boundary=frame')
        self.end_headers()
        last = 0
        try:
            while True:
                data, ts = encoded(name)
                if data and ts != last:
                    last = ts
                    head = ('--frame\r\nContent-Type: image/jpeg\r\n'
                            'Content-Length: %d\r\n\r\n' % len(data))
                    self.wfile.write(head + data + '\r\n')
                    self.wfile.flush()
                else:
                    time.sleep(FRAME_INTERVAL)
        except Exception:
            return

    def send_page(self):
        body = ('<html><meta charset=utf-8><title>XT-R1 画面</title>'
                '<body style="background:#111;color:#ddd;font-family:sans-serif">'
                '<h3>XT-R1 相机</h3>'
                '<img src=/rgb width=480><br><img src=/depth width=320><br>'
                '<img src=/ir width=320></body></html>')
        self.send_response(200)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def main():
    rospy.init_node('cam_server', anonymous=False)
    for name, topic in STREAMS.items():
        Grabber(name, topic)
    srv = ThreadedHTTPServer(('0.0.0.0', 8090), Handler)
    rospy.loginfo('cam_server on :8090')
    srv.serve_forever()


if __name__ == '__main__':
    main()
