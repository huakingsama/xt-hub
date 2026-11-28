#!/bin/bash
# 部署实时三维（:8094）到机器人
set -e
IP=${1:-192.168.110.44}
KEY=${2:-$HOME/robot_key}
cd "$(dirname "$0")"
echo "[1/3] 上传文件 ..."
scp -o StrictHostKeyChecking=no -i "$KEY" robot/cloud3d_live.py robot/run_cloud3d_live.sh \
    robot_stack.py "$IP:/home/xtrobot/" 2>/dev/null
scp -o StrictHostKeyChecking=no -i "$KEY" hub_server.py "$IP:/home/xtrobot/xthub/" 2>/dev/null
echo "[2/3] 启动服务 ..."
ssh -o StrictHostKeyChecking=no -i "$KEY" "xtrobot@$IP" \
  'chmod +x ~/run_cloud3d_live.sh; bash ~/run_cloud3d_live.sh; echo xtrobot | sudo -S systemctl restart xt-hub >/dev/null 2>&1; sleep 2'
echo "[3/3] 自检 ..."
ssh -o StrictHostKeyChecking=no -i "$KEY" "xtrobot@$IP" \
  'python3 -c "import urllib.request as u;print(\"8094:\", u.urlopen(\"http://127.0.0.1:8094/health\",timeout=5).read().decode().strip());print(\"8000:\", u.urlopen(\"http://127.0.0.1:8000/healthz\",timeout=5).read().decode().strip())"'
echo "完成：浏览器打开 http://$IP:8000/3d-live"
