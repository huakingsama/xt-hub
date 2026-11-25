#!/usr/bin/env bash
# 等 GitHub 授权 + 仓库就绪，然后自动推送
cd /d/A_dsh/SLAM/release/xthub || exit 1

log() { echo "[$(date +%H:%M:%S)] $*"; }

for i in $(seq 1 90); do
    out=$(timeout 15 ssh -T -o BatchMode=yes -o StrictHostKeyChecking=accept-new git@github.com 2>&1)
    if echo "$out" | grep -q "successfully authenticated"; then
        log "ssh auth OK: $(echo "$out" | head -1)"
        if git ls-remote origin >/dev/null 2>&1; then
            log "repo reachable, pushing ..."
            if git push -u origin main 2>&1 | tail -5; then
                log "PUSH_DONE main"
                git tag -f v1.0.0 >/dev/null 2>&1
                git push -f origin v1.0.0 2>&1 | tail -3
                log "TAG_DONE v1.0.0 (CI will build xthub.exe)"
                log "RESULT=SUCCESS"
                exit 0
            else
                log "push failed"
                log "RESULT=PUSH_FAILED"
                exit 2
            fi
        else
            log "auth ok but repo git@github.com:huakingsama/xt-hub.git not found yet ($i)"
        fi
    else
        log "waiting for ssh key authorization ($i/90) :: $(echo "$out" | tail -1)"
    fi
    sleep 10
done

log "RESULT=TIMEOUT"
exit 3
