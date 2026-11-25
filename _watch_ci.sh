#!/usr/bin/env bash
# 轮询 GitHub Actions 直到结束
API="https://api.github.com/repos/huakingsama/xt-hub/actions/runs?per_page=1"
for i in $(seq 1 60); do
    j=$(curl -s -m 15 "$API")
    st=$(echo "$j" | grep -o '"status": *"[a-z]*"' | head -1 | sed 's/.*"\([a-z]*\)"$/\1/')
    cc=$(echo "$j" | grep -o '"conclusion": *"[a-z]*"' | head -1 | sed 's/.*"\([a-z]*\)"$/\1/')
    url=$(echo "$j" | grep -o '"html_url": *"[^"]*actions/runs/[0-9]*"' | head -1 | sed 's/.*"\(http[^"]*\)"$/\1/')
    echo "[$(date +%H:%M:%S)] run $i: status=$st conclusion=$cc"
    if [ "$st" = "completed" ]; then
        echo "RUN_URL=$url"
        echo "RESULT=$cc"
        if [ "$cc" = "success" ]; then
            echo "--- release assets ---"
            curl -s -m 15 "https://api.github.com/repos/huakingsama/xt-hub/releases/tags/v1.0.0" \
              | grep -o '"browser_download_url": *"[^"]*"' | sed 's/.*"\(http[^"]*\)"$/\1/'
        fi
        exit 0
    fi
    sleep 15
done
echo "RESULT=TIMEOUT"
