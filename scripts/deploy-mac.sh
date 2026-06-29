#!/usr/bin/env bash
# Mac 版自动部署脚本（由 GitHub Actions self-hosted runner 在 push main 后调用）。
# 在真实部署目录原地操作，不动 chroma_db / users.db / .env。
# uvicorn 与 ngrok 由 launchd 托管，这里只重启它们（kickstart -k）。
set -euo pipefail

APP_DIR="/Users/linsen/开发工具/My-First-Project"
UV="/Users/linsen/.local/bin/uv"
UID_NUM="$(id -u)"

cd "$APP_DIR"

echo "[1/4] 拉取最新代码 (main)"
git fetch origin main
git pull --ff-only origin main

echo "[2/4] 同步依赖"
"$UV" sync

echo "[3/4] 重启 launchd 服务 (API + ngrok)"
launchctl kickstart -k "gui/${UID_NUM}/com.courserag.api"
launchctl kickstart -k "gui/${UID_NUM}/com.courserag.ngrok"

echo "[4/4] 健康检查 (最多 30 次 ×2s)"
for i in $(seq 1 30); do
  if curl -fsS http://127.0.0.1:8000/ >/dev/null 2>&1; then
    echo "✅ 部署成功，服务健康 (第 ${i} 次探测)"
    exit 0
  fi
  sleep 2
done

echo "❌ 健康检查失败：服务在 60s 内未恢复 200"
exit 1
