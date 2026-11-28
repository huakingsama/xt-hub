#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""实时三维：雷达 + 深度相机点云，浏览器里可拖动旋转（python2 + ROS melodic）

- 订阅 /scan 与 /camera/depth/points，按 map 系位姿累加体素点
- HTTP :8094
    /            自包含页面（canvas，拖动旋转 / 滚轮缩放 / 自动刷新）
    /cloud.bin   二进制点云：uint32 n, uint32 total, 然后 n*4 个 float32 (x,y,z,type)
                 type: 1=深度相机  2=雷达
    /health      文本 ok
- 点云有上限（MAXPTS），超出按插入顺序淘汰最旧的
"""
import math
import struct
import threading
import time

import rospy
import tf
import tf.transformations as tft
import sensor_msgs.point_cloud2 as pc2
from BaseHTTPServer import BaseHTTPRequestHandler, HTTPServer
from SocketServer import ThreadingMixIn
from sensor_msgs.msg import PointCloud2, LaserScan

VOX = 0.05                       # 5cm 体素
CAM_X, CAM_Y, CAM_Z = 0.22, 0.0, 0.45
LID_X, LID_Y, LID_Z = 0.04, 0.0, 0.18
MAXR = 6.0
MAXPTS = 40000                   # 体素上限
SEND_PTS = 6000                  # 每次发给浏览器的最多点数
CLOUD_GAP = 0.5                  # 深度点云最短间隔(秒)

VOXELS = {}                      # (i,j,k) -> tag
ORDER = []                       # 插入顺序，用于淘汰
LK = threading.Lock()
LISTENER = [None]


def pose(stamp):
    try:
        l = LISTENER[0]
        l.waitForTransform("map", "base_footprint", stamp, rospy.Duration(0.4))
        return l.lookupTransform("map", "base_footprint", stamp)
    except Exception:
        return None


def put(px, py, pz, tag, tr):
    R = tft.quaternion_matrix(tr[1])[:3, :3]
    t = tr[0]
    bx = R[0][0] * px + R[0][1] * py + R[0][2] * pz + t[0]
    by = R[1][0] * px + R[1][1] * py + R[1][2] * pz + t[1]
    bz = R[2][0] * px + R[2][1] * py + R[2][2] * pz + t[2]
    key = (int(round(bx / VOX)), int(round(by / VOX)), int(round(bz / VOX)))
    if key in VOXELS:
        return
    VOXELS[key] = tag
    ORDER.append(key)
    if len(ORDER) > MAXPTS:
        for k in ORDER[:len(ORDER) - MAXPTS]:
            VOXELS.pop(k, None)
        del ORDER[:len(ORDER) - MAXPTS]


_last_cloud = [0.0]


def on_cloud(msg):
    now = time.time()
    if now - _last_cloud[0] < CLOUD_GAP:
        return
    _last_cloud[0] = now
    tr = pose(msg.header.stamp)
    if tr is None:
        return
    n = 0
    with LK:
        for p in pc2.read_points(msg, field_names=("x", "y", "z"), skip_nans=True):
            n += 1
            if n % 3:                      # 每 3 个取 1 个，省 CPU
                continue
            ox, oy, oz = p[0], p[1], p[2]
            if oz <= 0.15 or oz > MAXR:
                continue
            put(CAM_X + oz, CAM_Y - ox, CAM_Z - oy, 1, tr)


def on_scan(msg):
    if not msg.ranges:
        return
    tr = pose(msg.header.stamp)
    if tr is None:
        return
    rmin = max(msg.range_min, 0.15)
    rmax = min(msg.range_max, 10.0)
    a = msg.angle_min
    with LK:
        for r in msg.ranges:
            if rmin < r < rmax:
                put(LID_X + r * math.cos(a), LID_Y + r * math.sin(a), LID_Z, 2, tr)
            a += msg.angle_increment


def snapshot(limit=SEND_PTS):
    with LK:
        total = len(ORDER)
        if total == 0:
            return b"", 0
        step = max(1, total // limit)
        keys = ORDER[::step][:limit]
        buf = [struct.pack("<II", len(keys), total)]
        for k in keys:
            buf.append(struct.pack("<ffff", k[0] * VOX, k[1] * VOX, k[2] * VOX,
                                   float(VOXELS.get(k, 2))))
        return "".join(buf), total


PAGE = """<!doctype html><html><head><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1">
<title>XT-R1 实时三维</title>
<style>
html,body{margin:0;height:100%;background:#0b0f17;color:#c9d3e0;
 font-family:system-ui,"Microsoft YaHei",sans-serif;overflow:hidden}
#cv{display:block;width:100%;height:100%;cursor:grab}
#hud{position:fixed;left:12px;top:10px;font-size:12px;line-height:1.7;
 background:rgba(12,18,28,.72);padding:8px 10px;border-radius:8px;border:1px solid #1d2938}
#hud b{color:#6ea8ff}
.dot{display:inline-block;width:8px;height:8px;border-radius:50%;margin-right:5px}
#bar{position:fixed;right:12px;top:10px;font-size:12px}
button{background:#1a2436;color:#c9d3e0;border:1px solid #2b3a52;border-radius:6px;
 padding:5px 10px;font-size:12px;cursor:pointer;margin-left:6px}
button:hover{background:#22314a}
</style></head><body>
<canvas id=cv></canvas>
<div id=hud>
 <div><b>XT-R1 实时三维</b> · 雷达+深度</div>
 <div><span class=dot style="background:#ffb03c"></span>雷达 <span id=n1>-</span>
      <span class=dot style="background:#4fa3ff;margin-left:10px"></span>深度 <span id=n2>-</span></div>
 <div>总点数 <span id=nt>-</span> · 刷新 <span id=fps>-</span></div>
 <div style="opacity:.55;margin-top:4px">拖动旋转 · 滚轮缩放 · 双击复位</div>
</div>
<div id=bar><button id=pp>暂停</button><button id=rs>复位</button></div>
<script>
var cv=document.getElementById('cv'),cx=cv.getContext('2d');
var W=0,H=0,DPR=window.devicePixelRatio||1;
function fit(){W=cv.clientWidth;H=cv.clientHeight;cv.width=W*DPR;cv.height=H*DPR;
 cx.setTransform(DPR,0,0,DPR,0,0);}
window.addEventListener('resize',fit);fit();
var yaw=-0.6,pitch=0.55,dist=14,spin=false,pts=null,ts=0,c1=0,c2=0,tot=0,paused=false;
function proj(x,y,z){
  var cy=Math.cos(yaw),sy=Math.sin(yaw),cp=Math.cos(pitch),sp=Math.sin(pitch);
  var X=x*cy-y*sy, Y0=x*sy+y*cy;
  var Y=Y0*cp-z*sp, Z=Y0*sp+z*cp;
  var f=Math.min(W,H)*0.9/(dist+Z*0.35);
  return [W/2+X*f, H/2-Y*f, Z];
}
var lastDraw=0;
function draw(){
  var nowd=performance.now();
  if(nowd-lastDraw<33){requestAnimationFrame(draw);return;}
  lastDraw=nowd;
  cx.clearRect(0,0,W,H);
  // 地面网格
  cx.strokeStyle='rgba(90,120,160,.13)';cx.lineWidth=1;
  for(var g=-12;g<=12;g+=2){
    var a=proj(g,-12,0),b=proj(g,12,0),c=proj(-12,g,0),d=proj(12,g,0);
    cx.beginPath();cx.moveTo(a[0],a[1]);cx.lineTo(b[0],b[1]);
    cx.moveTo(c[0],c[1]);cx.lineTo(d[0],d[1]);cx.stroke();
  }
  var o=proj(0,0,0);
  cx.fillStyle='#fff';cx.beginPath();cx.arc(o[0],o[1],3.5,0,6.284);cx.fill();
  cx.strokeStyle='#6ea8ff';cx.beginPath();cx.moveTo(o[0],o[1]);
  var fw=proj(1.2,0,0);cx.lineTo(fw[0],fw[1]);cx.stroke();
  if(pts){
    var n1=0,n2=0,i=0,len=pts.length;
    for(i=0;i<len;i+=4){
      var t=pts[i+3], p=proj(pts[i],pts[i+1],pts[i+2]);
      if(t>1.5){cx.fillStyle='#ffb03c';n2++;}else{cx.fillStyle='#4fa3ff';n1++;}
      cx.fillRect(p[0],p[1],1.6,1.6);
    }
    c1=n1;c2=n2;
  }
  document.getElementById('n1').textContent=c1;
  document.getElementById('n2').textContent=c2;
  document.getElementById('nt').textContent=tot;
  if(spin){yaw+=0.006;}
  requestAnimationFrame(draw);
}
function fetchCloud(){
  if(paused){setTimeout(fetchCloud,900);return;}
  var t0=Date.now();
  fetch('/cloud.bin?t='+t0).then(function(r){return r.arrayBuffer()}).then(function(b){
    var dv=new DataView(b);
    if(b.byteLength<8) return;
    tot=dv.getUint32(4,true);
    pts=new Float32Array(b,8);
    ts=Date.now();
    document.getElementById('fps').textContent=Math.round(1000/Math.max(1,ts-lastT))+' Hz';
    lastT=ts;
    setTimeout(fetchCloud,120);
  }).catch(function(){setTimeout(fetchCloud,800);});
}
var lastT=Date.now();
// 交互
var drag=false,lx=0,ly=0;
cv.addEventListener('mousedown',function(e){drag=true;lx=e.clientX;ly=e.clientY;cv.style.cursor='grabbing';});
window.addEventListener('mouseup',function(){drag=false;cv.style.cursor='grab';});
window.addEventListener('mousemove',function(e){
  if(!drag)return;
  yaw+=(e.clientX-lx)*0.008; pitch+=(e.clientY-ly)*0.006;
  pitch=Math.max(-0.2,Math.min(1.45,pitch)); lx=e.clientX;ly=e.clientY;});
cv.addEventListener('wheel',function(e){e.preventDefault();
  dist*=Math.pow(1.0015,e.deltaY); dist=Math.max(3,Math.min(45,dist));},{passive:false});
cv.addEventListener('dblclick',function(){yaw=-0.6;pitch=0.55;dist=14;});
document.getElementById('pp').onclick=function(){paused=!paused;this.textContent=paused?'继续':'暂停';};
document.getElementById('rs').onclick=function(){yaw=-0.6;pitch=0.55;dist=14;};
fetchCloud();draw();
</script></body></html>"""


class H(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.0"

    def log_message(self, *a):
        pass

    def do_GET(self):
        p = self.path.split("?")[0]
        if p in ("/", "/index.html"):
            body = PAGE
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)
            return
        if p == "/cloud.bin":
            data, total = snapshot()
            self.send_response(200)
            self.send_header("Content-Type", "application/octet-stream")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Total", str(total))
            self.end_headers()
            self.wfile.write(data)
            return
        if p == "/health":
            body = "ok %d\n" % len(ORDER)
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        self.send_response(404)
        self.end_headers()


class S(ThreadingMixIn, HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def main():
    rospy.init_node("cloud3d_live", anonymous=False)
    LISTENER[0] = tf.TransformListener()
    rospy.Subscriber("/camera/depth/points", PointCloud2, on_cloud, queue_size=1)
    rospy.Subscriber("/scan", LaserScan, on_scan, queue_size=1)
    srv = S(("0.0.0.0", 8094), H)
    rospy.loginfo("cloud3d_live on :8094")
    srv.serve_forever()


if __name__ == "__main__":
    main()
