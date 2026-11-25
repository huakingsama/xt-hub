#!/bin/bash
# 在机器人上启动 XT-HUB（可用 start_hub_robot.sh stop 停止）
cd "$HOME/xthub" || exit 1

stop_hub() {
    pkill -9 -f 'hub_[s]erver.py' 2>/dev/null
    sleep 1
}

case "$1" in
stop)
    stop_hub
    echo "hub stopped"
    exit 0
    ;;
restart)
    stop_hub
    ;;
esac

if ss -lnt 2>/dev/null | grep -q ':8000'; then
    echo "8000 已在监听，不重复启动"
else
    setsid nohup python3 -u hub_server.py --port 8000 > "$HOME/xthub/hub.log" 2>&1 < /dev/null &
    sleep 4
fi

if ss -lnt 2>/dev/null | grep -q ':8000'; then
    echo "OK  hub 在 http://$(hostname -I | awk '{print $1}'):8000"
else
    echo "FAILED"
    tail -20 "$HOME/xthub/hub.log"
fi
