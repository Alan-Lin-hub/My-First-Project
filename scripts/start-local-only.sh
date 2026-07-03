#!/usr/bin/env bash
#
# start-local-only.sh — 只启动本地后端，不启动 ngrok 公网隧道。
#
# 用法:
#   ./scripts/start-local-only.sh
#
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
"$ROOT/scripts/start-with-confirm.sh" --yes --no-ngrok
