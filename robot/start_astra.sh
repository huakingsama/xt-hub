#!/bin/bash
# 启动 Astra 深度相机（深度 + RGB），ROS melodic
source /opt/ros/melodic/setup.bash
[ -f ~/catkin_ws/devel/setup.bash ] && source ~/catkin_ws/devel/setup.bash

pkill -9 -f 'astra_camera_no[d]e' >/dev/null 2>&1
pkill -9 -f 'uvc_camera_no[d]e' >/dev/null 2>&1
sleep 1

setsid nohup roslaunch astra_launch astra.launch > /tmp/astra.log 2>&1 < /dev/null &
sleep 6

echo "--- astra 进程 ---"
pgrep -af 'astra_camera_no[d]e' | head -2
echo "--- 相机话题 ---"
timeout 5 rostopic list 2>/dev/null | grep -iE 'camera/(depth|rgb)' | head -6
