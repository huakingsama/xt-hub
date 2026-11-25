#!/bin/bash
# 在机器人上安装 / 升级 XT-HUB（多人协作控制台）
# 用法：bash install.sh            （默认端口 8000）
set -e
PORT="${1:-8000}"
DIR=/home/xtrobot/hub
SUDO_PW="${SUDO_PW:-1234}"

echo "[1/4] 复制文件到 $DIR"
mkdir -p "$DIR"
cp -f "$(dirname "$0")/hub_server.py" "$DIR/"
cp -f "$(dirname "$0")/robot_stack.py" "$DIR/" 2>/dev/null || true

echo "[2/4] 写 systemd 单元 xt-hub.service"
echo "$SUDO_PW" | sudo -S tee /etc/systemd/system/xt-hub.service >/dev/null <<EOF
[Unit]
Description=XT-R1 collaboration hub (multi-user robot console)
After=network.target

[Service]
Type=simple
User=xtrobot
WorkingDirectory=$DIR
ExecStart=/usr/bin/python3 $DIR/hub_server.py --port $PORT
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF

echo "[2b/4] 写 systemd 单元 xt-stack.service（传感器栈管理器）"
if [ -f "$DIR/robot_stack.py" ]; then
echo "$SUDO_PW" | sudo -S tee /etc/systemd/system/xt-stack.service >/dev/null <<EOF
[Unit]
Description=XT-R1 sensor stack manager (lidar / depth / mapping / view services)
After=network.target

[Service]
Type=simple
User=xtrobot
WorkingDirectory=$DIR
ExecStart=/usr/bin/python3 $DIR/robot_stack.py --port 8100
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF
fi

echo "[3/4] 启用并重启服务"
echo "$SUDO_PW" | sudo -S systemctl daemon-reload
echo "$SUDO_PW" | sudo -S systemctl enable xt-hub >/dev/null 2>&1 || true
echo "$SUDO_PW" | sudo -S systemctl restart xt-hub
if [ -f "$DIR/robot_stack.py" ]; then
  echo "$SUDO_PW" | sudo -S systemctl enable xt-stack >/dev/null 2>&1 || true
  echo "$SUDO_PW" | sudo -S systemctl restart xt-stack
fi

echo "[4/4] 自检"
sleep 2
systemctl is-active xt-hub || true
systemctl is-active xt-stack 2>/dev/null || echo "xt-stack: 未安装（可选）"
IP=$(hostname -I | awk '{print $1}')
echo "-----------------------------------------------------"
echo " 控制台: http://$IP:$PORT"
echo " 首次账号: admin / admin123   (登录后立刻到 /admin 改密码)"
echo "-----------------------------------------------------"
