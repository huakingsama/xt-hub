#!/usr/bin/env bash
# 打一个单文件分发包 xthub.pyz（任何 python3 都能直接跑，无需 pip）
set -e
cd "$(dirname "$0")"

rm -rf build_pyz
mkdir -p build_pyz
cp hub_server.py build_pyz/__main__.py
cp LICENSE build_pyz/ 2>/dev/null || true

python3 -m zipapp build_pyz -o xthub.pyz -p "/usr/bin/env python3"
chmod +x xthub.pyz

echo "built: xthub.pyz ($(wc -c < xthub.pyz) bytes)"
echo "run:   python3 xthub.pyz --demo --dry-run --port 18300"
