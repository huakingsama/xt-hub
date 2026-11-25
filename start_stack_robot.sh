#!/bin/bash
# 在机器人上启动传感器栈管理服务 robot_stack.py（端口 8100）
cd "$HOME/xthub" || exit 1

if [ "$1" = "stop" ]; then
    pkill -9 -f 'robot_[s]tack.py' 2>/dev/null
    sleep 1
    echo "stack stopped"
    exit 0
fi

pkill -9 -f 'robot_[s]tack.py' 2>/dev/null
sleep 1
setsid nohup python3 -u robot_stack.py --port 8100 > "$HOME/xthub/stack.log" 2>&1 < /dev/null &
sleep 4

if ss -lnt 2>/dev/null | grep -q ':8100'; then
    echo "OK  robot_stack 在 http://$(hostname -I | awk '{print $1}'):8100"
    curl -s -m 5 http://127.0.0.1:8100/health || true
    echo
else
    echo "FAILED"
    tail -20 "$HOME/xthub/stack.log"
fi
