#!/bin/bash
# 启动遥控桥（:8099 位姿/速度/目标点）
source /opt/ros/melodic/setup.bash
[ -f ~/catkin_ws/devel/setup.bash ] && source ~/catkin_ws/devel/setup.bash
cd ~
pkill -9 -f 'teleop_[b]ridge.py' >/dev/null 2>&1
sleep 1
setsid nohup python ~/teleop_bridge.py > /tmp/bridge.log 2>&1 < /dev/null &
sleep 5
if ss -lnt | grep -q 8099; then echo RUNNING_OK; else echo FAILED; tail -6 /tmp/bridge.log; fi
