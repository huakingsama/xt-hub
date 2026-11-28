#!/bin/bash
# 实时三维点云服务（:8094）
source /opt/ros/melodic/setup.bash
[ -f ~/catkin_ws/devel/setup.bash ] && source ~/catkin_ws/devel/setup.bash
cd ~
pkill -9 -f 'cloud3d_liv[e].py' >/dev/null 2>&1
sleep 1
setsid nohup python ~/cloud3d_live.py > /tmp/cloud3d_live.log 2>&1 < /dev/null &
sleep 3
ss -lnt | grep -q 8094 && echo RUNNING_OK || echo FAILED
