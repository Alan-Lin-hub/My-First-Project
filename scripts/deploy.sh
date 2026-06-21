#!/usr/bin/env bash
#
# deploy.sh — 拉取最新代码并安全重启。
#
# 做的事(按顺序):
#   1. 先跑 backup.sh(更新前留个还原点)
#   2. git pull
#   3. uv sync(同步依赖)
#   4. 重启服务: 有 systemd 单元就 systemctl restart,否则提示手动重启
#   5. 健康检查: 轮询本地 8000 端口直到 200
#
# 用法:
#   ./scripts/deploy.sh                       # 默认操作 systemd 单元 course-rag
#   SERVICE=course-rag ./scripts/deploy.sh    # 指定 systemd 单元名
#   SKIP_BACKUP=1 ./scripts/deploy.sh         # 跳过更新前备份
#   PORT=8000 ./scripts/deploy.sh             # 健康检查端口(默认 8000)
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SERVICE="${SERVICE:-course-rag}"
PORT="${PORT:-8000}"
cd "$ROOT"

# 找 uv(可能不在 PATH)
UV="$(command -v uv || echo "$HOME/.local/bin/uv")"
[ -x "$UV" ] || { echo "❌ 找不到 uv。先安装: curl -LsSf https://astral.sh/uv/install.sh | sh" >&2; exit 1; }

# 1. 更新前备份
if [ "${SKIP_BACKUP:-0}" != "1" ]; then
  echo "→ [1/5] 更新前备份"
  "$ROOT/scripts/backup.sh" || echo "⚠️  备份失败(可能首次部署还没数据),继续。"
else
  echo "→ [1/5] 跳过备份(SKIP_BACKUP=1)"
fi

# 2. 拉代码
echo "→ [2/5] git pull"
git pull --ff-only

# 3. 同步依赖
echo "→ [3/5] uv sync"
"$UV" sync

# 4. 重启
echo "→ [4/5] 重启服务"
if command -v systemctl >/dev/null 2>&1 && systemctl list-unit-files 2>/dev/null | grep -q "^${SERVICE}.service"; then
  sudo systemctl restart "$SERVICE"
  echo "   systemctl restart $SERVICE 已执行"
else
  echo "   ⚠️  未发现 systemd 单元 '$SERVICE'。请手动重启你的进程,例如:"
  echo "      cd backend && $UV run uvicorn app:app --host 127.0.0.1 --port $PORT --workers 1"
fi

# 5. 健康检查
echo "→ [5/5] 健康检查 http://127.0.0.1:$PORT/"
for i in $(seq 1 30); do
  code="$(curl -s -o /dev/null -w '%{http_code}' "http://127.0.0.1:$PORT/" 2>/dev/null || echo 000)"
  if [ "$code" = "200" ]; then
    echo "✅ 部署完成,服务正常 (HTTP 200)"
    exit 0
  fi
  sleep 2
done

echo "❌ 健康检查超时(60s 内未返回 200)。排查: journalctl -u $SERVICE -n 50 --no-pager" >&2
exit 1
