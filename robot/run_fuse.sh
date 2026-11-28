#!/bin/bash
# 启动融合画面服务（:8093/fuse.png）—— 必须带 ROS 环境，否则 import rospy 失败
source /opt/ros/melodic/setup.bash
[ -f ~/catkin_ws/devel/setup.bash ] && source ~/catkin_ws/devel/setup.bash
cd ~
pkill -9 -f 'fuse_[v]iew.py' >/dev/null 2>&1
sleep 1
setsid nohup python ~/fuse_view.py > ~/fuse.log 2>&1 < /dev/null &
sleep 5
if ss -lnt | grep -q 8093; then echo RUNNING_OK; else echo FAILED; tail -6 ~/fuse.log; fi
