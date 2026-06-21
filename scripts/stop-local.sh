#!/usr/bin/env bash
#
# stop-local.sh — 停掉后端(uvicorn) 和 公网隧道(cloudflared)。
#
# 用法:  ./scripts/stop-local.sh
set -uo pipefail
PORT=8000

lsof -nP -iTCP:$PORT -sTCP:LISTEN -t 2>/dev/null | xargs kill 2>/dev/null && echo "✅ 已停后端" || echo "· 后端本就没在跑"
pkill -f "ngrok http" 2>/dev/null && echo "✅ 已停隧道" || echo "· 隧道本就没在跑"
