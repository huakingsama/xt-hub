#!/bin/bash
# 在机器人上安装 systemd 自启（xt-hub + xt-stack），需要 sudo 密码
# 用法：sudo bash install_services.sh
set -e
U=xtrobot
D=/home/$U/xthub

cat > /etc/systemd/system/xt-hub.service <<EOF
[Unit]
Description=XT-HUB multi-user console
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$U
WorkingDirectory=$D
Environment=PYTHONUNBUFFERED=1
ExecStart=/usr/bin/python3 -u $D/hub_server.py --port 8000
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF

cat > /etc/systemd/system/xt-stack.service <<EOF
[Unit]
Description=XT-HUB robot sensor stack manager
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$U
WorkingDirectory=$D
Environment=PYTHONUNBUFFERED=1
ExecStart=/usr/bin/python3 -u $D/robot_stack.py --port 8100
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable xt-hub.service xt-stack.service
# 先停掉手工起的实例，避免端口冲突
pkill -9 -f 'hub_[s]erver.py' 2>/dev/null || true
pkill -9 -f 'robot_[s]tack.py' 2>/dev/null || true
sleep 1
systemctl restart xt-hub.service
systemctl restart xt-stack.service
sleep 4
systemctl --no-pager --lines=0 status xt-hub.service | head -5
systemctl --no-pager --lines=0 status xt-stack.service | head -5
ss -lnt | grep -E ':(8000|8100)' || echo "PORT_MISSING"
