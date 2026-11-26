#!/bin/bash
# 把一个 Linux 机器（实验室服务器 / 树莓派 / 迷你主机）变成 XT-HUB 服务器
# 用法：  bash deploy-linux-server.sh [目标目录，默认 ~/xthub]
set -e
DEST="${1:-$HOME/xthub}"
HERE="$(cd "$(dirname "$0")" && pwd)"

echo "==> 目标目录: $DEST"
mkdir -p "$DEST/dist"
cp -f "$HERE/hub_server.py" "$HERE/robot_stack.py" "$HERE/make3d_html.py" "$DEST/" 2>/dev/null || true
[ -f "$HERE/config.json" ] && cp -f "$HERE/config.json" "$DEST/" || true
[ -f "$HERE/dist/client.zip" ] && cp -f "$HERE/dist/client.zip" "$DEST/dist/" || true

echo "==> 自检 Python"
python3 -c "import sys; print('python', sys.version.split()[0])"

echo "==> 起服务（前台试运行 3 秒）"
cd "$DEST"
timeout 3 python3 hub_server.py --port 8000 || true

echo
echo "==> 安装为 systemd 服务（需要 sudo）"
sudo tee /etc/systemd/system/xt-hub.service >/dev/null <<UNIT
[Unit]
Description=XT-HUB robot collaboration server
After=network.target

[Service]
Type=simple
User=$USER
WorkingDirectory=$DEST
ExecStart=/usr/bin/python3 -u $DEST/hub_server.py --port 8000
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
UNIT

sudo systemctl daemon-reload
sudo systemctl enable xt-hub
sudo systemctl restart xt-hub
sleep 2
echo "==> 状态"
systemctl --no-pager --lines=5 status xt-hub || true
echo
echo "==> 自检"
curl -s "http://127.0.0.1:8000/healthz" && echo
echo "完成。局域网地址：http://$(hostname -I | awk '{print $1}'):8000"
