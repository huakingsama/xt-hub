#!/bin/bash
# 启动 UVC 彩色发布（/rgb_view），供 cam_server 的 :8090/rgb 使用
source /opt/ros/melodic/setup.bash
[ -f ~/catkin_ws/devel/setup.bash ] && source ~/catkin_ws/devel/setup.bash
pkill -9 -f 'rgb_pu[b].py' >/dev/null 2>&1
sleep 1
setsid nohup python ~/rgb_pub.py _device:=/dev/video0 _width:=640 _height:=480 _fps:=15 _topic:=/rgb_view > /tmp/rgbpub.log 2>&1 < /dev/null &
sleep 5
echo "--- log ---"; tail -4 /tmp/rgbpub.log
echo "--- hz ---"; timeout 6 rostopic hz /rgb_view 2>&1 | grep -E "average rate|no new" | head -2
