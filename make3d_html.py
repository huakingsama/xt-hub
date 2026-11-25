#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""make3d_html.py - map3d.pcd -> map3d_<ts>.html（纯标准库，车上 python2.7/3.x 都能跑）

不依赖 numpy / PIL：只做"把点云塞进自包含 HTML"，用 canvas 2D 画，拖拽旋转、滚轮缩放。
（静态 PNG 仍可用 PC 上的 make3d.py 生成）

用法:
    python make3d_html.py /home/xtrobot/data/map3d.pcd /home/xtrobot/3d_maps
    python make3d_html.py map3d.pcd out_dir --name mymap
"""
import json
import math
import os
import re
import sys
import time

TPL = """<!doctype html><meta charset=utf-8>
<title>XT-R1 map3d</title>
<style>html,body{margin:0;background:#0a0a0e;color:#c8ccd8;font:13px monospace;overflow:hidden}
#hud{position:fixed;left:12px;top:10px;line-height:1.6}
#hud b{color:#fff}</style>
<canvas id=c></canvas><div id=hud>
<b>XT-R1 3D MAP</b><br><span id=info></span><br>
拖拽=旋转　滚轮=缩放　R=重置<br>
<span style="color:#ff9628">橙 = 雷达</span>　<span style="color:#7ac2ff">蓝-&gt;红 = 深度(高度)</span><br>
X=红 Y=绿 Z=蓝 (原点=起始位置)
</div>
<script>
const P=%s, Z0=%s, Z1=%s;
const cv=document.getElementById('c'), ctx=cv.getContext('2d');
let yaw=0.7, pitch=0.42, sc=90, drag=null;
function fit(){cv.width=innerWidth;cv.height=innerHeight;}
addEventListener('resize',fit); fit();
document.getElementById('info').textContent='points '+P.length;
function col(z,i){
  if(i===2) return '#ff9628';
  let t=Math.max(0,Math.min(1,(z-Z0)/(Z1-Z0)));
  return 'rgb('+Math.round(40+215*Math.pow(t,0.8))+','+Math.round(190-120*t)+','+Math.round(255-200*t)+')';
}
function draw(){
  ctx.fillStyle='#0a0a0e'; ctx.fillRect(0,0,cv.width,cv.height);
  const cy=Math.cos(yaw), sy=Math.sin(yaw), cp=Math.cos(pitch), sp=Math.sin(pitch);
  const W=cv.width/2, H=cv.height/2;
  ctx.strokeStyle='#1e1e28'; ctx.lineWidth=1;
  for(let g=-8; g<=8; g++){
    for(const ab of [[[g,-8,0],[g,8,0]], [[-8,g,0],[8,g,0]]]){
      const pr=(q)=>{const xr=q[0]*cy-q[1]*sy, yr=q[0]*sy+q[1]*cy;
        return [W+xr*sc, H-(q[2]*cp-yr*sp)*sc];};
      const p1=pr(ab[0]), p2=pr(ab[1]); ctx.beginPath(); ctx.moveTo(p1[0],p1[1]); ctx.lineTo(p2[0],p2[1]); ctx.stroke();
    }
  }
  const buf=[];
  for(let i=0;i<P.length;i++){
    const p=P[i], xr=p[0]*cy-p[1]*sy, yr=p[0]*sy+p[1]*cy;
    const d=yr*cp+p[2]*sp;
    buf.push([W+xr*sc, H-(p[2]*cp-yr*sp)*sc, d, p[2], p[3]]);
  }
  buf.sort((a,b)=>b[2]-a[2]);
  for(const b of buf){ ctx.fillStyle=col(b[3],b[4]); ctx.fillRect(b[0],b[1],2,2); }
  const pr=(q)=>{const xr=q[0]*cy-q[1]*sy, yr=q[0]*sy+q[1]*cy;
    return [W+xr*sc, H-(q[2]*cp-yr*sp)*sc];};
  const O=pr([0,0,0]);
  const ax=[[[1.2,0,0],'X','#ff5050'],[[0,1.2,0],'Y','#50ff78'],[[0,0,1.2],'Z','#5a96ff']];
  for(const it of ax){ const q=pr(it[0]); ctx.strokeStyle=it[2]; ctx.lineWidth=3;
    ctx.beginPath(); ctx.moveTo(O[0],O[1]); ctx.lineTo(q[0],q[1]); ctx.stroke();
    ctx.fillStyle=it[2]; ctx.font='16px monospace'; ctx.fillText(it[1],q[0]+5,q[1]-5); }
  ctx.fillStyle='#fff'; ctx.beginPath(); ctx.arc(O[0],O[1],4,0,7); ctx.fill();
}
cv.addEventListener('mousedown',function(e){drag=[e.clientX,e.clientY,yaw,pitch]});
addEventListener('mouseup',function(){drag=null});
addEventListener('mousemove',function(e){ if(!drag)return;
  yaw=drag[2]+(e.clientX-drag[0])*0.008;
  pitch=Math.max(-1.45,Math.min(1.45,drag[3]+(e.clientY-drag[1])*0.006)); draw();});
cv.addEventListener('wheel',function(e){e.preventDefault(); sc*=e.deltaY>0?0.92:1.08; draw();},{passive:false});
addEventListener('keydown',function(e){ if(e.key==='r'||e.key==='R'){yaw=0.7;pitch=0.42;sc=90;draw();}});
draw();
</script>"""


def load(path):
    pts = []
    on = False
    f = open(path, "r")
    try:
        for line in f:
            if not on:
                if line.startswith("DATA"):
                    on = True
                continue
            p = line.split()
            if len(p) >= 3:
                try:
                    x, y, z = float(p[0]), float(p[1]), float(p[2])
                except ValueError:
                    continue
                if not (math.isnan(x) or math.isnan(y) or math.isnan(z)):
                    pts.append((x, y, z, int(float(p[3])) if len(p) > 3 else 1))
    finally:
        f.close()
    return pts


def pct(sorted_vals, q):
    if not sorted_vals:
        return 0.0
    i = int(round((len(sorted_vals) - 1) * q))
    return sorted_vals[max(0, min(len(sorted_vals) - 1, i))]


def build(pcd, out_dir, name=None):
    pts = load(pcd)
    if not pts:
        raise SystemExit("PCD 里没有点: %s" % pcd)
    ox = sum(p[0] for p in pts) / len(pts)
    oy = sum(p[1] for p in pts) / len(pts)
    data = [[round(p[0] - ox, 2), round(p[1] - oy, 2), round(p[2], 2), p[3]] for p in pts]
    zs = sorted(p[2] for p in pts)
    z0, z1 = pct(zs, 0.03), pct(zs, 0.97)
    if z1 - z0 < 0.2:
        z1 = z0 + 0.2

    if not os.path.isdir(out_dir):
        os.makedirs(out_dir)
    nm = name or ("map3d_" + time.strftime("%Y%m%d_%H%M%S"))
    out = os.path.join(out_dir, nm + ".html")
    f = open(out, "w")
    try:
        f.write(TPL % (json.dumps(data, separators=(",", ":")), repr(z0), repr(z1)))
    finally:
        f.close()

    n_lid = len([p for p in pts if p[3] == 2])
    print("WROTE %s  points=%d (lidar %d / depth %d)  size=%d KB"
          % (out, len(data), n_lid, len(data) - n_lid, os.path.getsize(out) // 1024))
    return out


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print(__doc__)
        raise SystemExit(2)
    nm = None
    if "--name" in sys.argv:
        i = sys.argv.index("--name")
        nm = sys.argv[i + 1]
    build(sys.argv[1], sys.argv[2], nm)
