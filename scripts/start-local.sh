#!/usr/bin/env bash
#
# start-local.sh — 本机一键启动：后端(uvicorn) + 公网隧道(ngrok 固定域名)。
#
# 做的事:
#   1. 停掉旧的 uvicorn(8000) 和 ngrok
#   2. 启动后端,绑 0.0.0.0:8000(本机 + 局域网可访问)
#   3. 等后端返回 200
#   4. 启动 ngrok 隧道(固定域名),打印公网 HTTPS 地址
#
# 用法:  ./scripts/start-local.sh
# 关闭:  ./scripts/stop-local.sh
#
# 公网域名固定为 NGROK_DOMAIN(下面),重启不变。
# 注意:本机设了代理(127.0.0.1:7890),ngrok 免费版不能走代理,
#      所以启动 ngrok 时用 env -u 去掉所有 *_proxy 变量。
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PORT=8000
UV="$(command -v uv || echo "$HOME/.local/bin/uv")"
NGROK="$HOME/.local/bin/ngrok"
NGROK_DOMAIN="engraving-exile-fester.ngrok-free.dev"

echo "→ [1/4] 停掉旧进程"
lsof -nP -iTCP:$PORT -sTCP:LISTEN -t 2>/dev/null | xargs kill 2>/dev/null && echo "   已停旧后端" || echo "   无旧后端"
pkill -f "ngrok http" 2>/dev/null && echo "   已停旧隧道" || echo "   无旧隧道"
sleep 1

echo "→ [2/4] 启动后端 (0.0.0.0:$PORT)"
cd "$ROOT/backend"
nohup "$UV" run uvicorn app:app --host 0.0.0.0 --port $PORT > /tmp/rag_server.log 2>&1 &
cd "$ROOT"

echo "→ [3/4] 等后端就绪..."
ok=0
for i in $(seq 1 40); do
  if [ "$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:$PORT/ 2>/dev/null)" = "200" ]; then ok=1; break; fi
  sleep 2
done
if [ "$ok" != "1" ]; then echo "❌ 后端没起来,看日志: tail -50 /tmp/rag_server.log"; exit 1; fi
echo "   ✅ 后端就绪"

LAN_IP="$(ipconfig getifaddr en0 2>/dev/null || true)"

if [ ! -x "$NGROK" ]; then
  echo "→ [4/4] 未装 ngrok,跳过公网隧道(仅本机/局域网可用)"
else
  echo "→ [4/4] 启动公网隧道 (ngrok 固定域名,去代理)..."
  nohup env -u HTTP_PROXY -u HTTPS_PROXY -u http_proxy -u https_proxy -u ALL_PROXY -u all_proxy \
    "$NGROK" http --url="$NGROK_DOMAIN" $PORT > /tmp/ngrok.log 2>&1 &
  URL=""
  for i in $(seq 1 30); do
    URL="$(curl -s http://127.0.0.1:4040/api/tunnels 2>/dev/null | python3 -c 'import sys,json;d=json.load(sys.stdin);print(d["tunnels"][0]["public_url"]) if d.get("tunnels") else None' 2>/dev/null || true)"
    [ -n "$URL" ] && break
    sleep 2
  done
  [ -z "$URL" ] && URL="https://$NGROK_DOMAIN"   # 兜底:域名固定的,直接用
fi

echo
echo "================ 启动完成 ================"
echo "  本机:    http://localhost:$PORT"
[ -n "${LAN_IP:-}" ] && echo "  局域网:  http://$LAN_IP:$PORT"
[ -n "${URL:-}" ] && echo "  公网:    $URL" || { [ -x "$CF" ] && echo "  公网:    (地址未生成,看 tail -20 /tmp/cloudflared.log)"; }
echo "  登录:    admin / 你设置的密码"
echo "=========================================="
