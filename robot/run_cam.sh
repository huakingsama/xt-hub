#!/bin/bash
# 启动相机画面服务（:8090/rgb /depth /ir）
# 说明：/rgb 依赖 rgb_pub.py 往 /rgb_view 发 UVC 彩色帧，必须一起拉起
source /opt/ros/melodic/setup.bash
[ -f ~/catkin_ws/devel/setup.bash ] && source ~/catkin_ws/devel/setup.bash
cd ~

# 1) 彩色发布（UVC /dev/video0 -> /rgb_view）
pkill -9 -f 'rgb_pu[b].py' >/dev/null 2>&1
sleep 1
setsid nohup python ~/rgb_pub.py _device:=/dev/video0 _width:=640 _height:=480 _fps:=15 _topic:=/rgb_view > /tmp/rgbpub.log 2>&1 < /dev/null &

# 2) 深度伪彩（有 depth/image_raw 才有效）
pkill -9 -f 'depth_colo[r].py' >/dev/null 2>&1
setsid nohup python ~/depth_color.py > /tmp/depthcolor.log 2>&1 < /dev/null &

# 3) 画面 HTTP 服务
pkill -9 -f 'cam_serve[r].py' >/dev/null 2>&1
sleep 1
setsid nohup python ~/cam_server.py > /tmp/cam_server.log 2>&1 < /dev/null &
sleep 5

if ss -lnt | grep -q 8090; then echo RUNNING_OK; else echo FAILED; tail -6 /tmp/cam_server.log; fi
