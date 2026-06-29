#!/usr/bin/env bash
#
# start-with-confirm.sh — 代码变更后，先询问再启动本地服务。
#
# 作用:
#   1. 检查当前仓库是否有未提交改动，或当前提交是否和上次启动时不同。
#   2. 如果检测到变更，询问是否启动服务；确认后调用 start-local.sh。
#   3. 启动成功后，记录当前提交号，避免重复询问。
#
# 用法:
#   ./scripts/start-with-confirm.sh
#   ./scripts/start-with-confirm.sh --force
#
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
STATE_DIR="$ROOT/.service-state"
STATE_FILE="$STATE_DIR/last-started-commit"
FORCE=0

if [[ "${1:-}" == "--force" ]]; then
  FORCE=1
fi

mkdir -p "$STATE_DIR"
cd "$ROOT"

CURRENT_HEAD="$(git rev-parse --short HEAD 2>/dev/null || echo unknown)"
HAS_UNCOMMITTED=0
if ! git diff --quiet --ignore-submodules -- || ! git diff --cached --quiet --ignore-submodules --; then
  HAS_UNCOMMITTED=1
fi

LAST_STARTED_HEAD=""
if [[ -f "$STATE_FILE" ]]; then
  LAST_STARTED_HEAD="$(cat "$STATE_FILE")"
fi

NEEDS_CONFIRM=0
if [[ "$FORCE" -eq 0 ]]; then
  if [[ "$HAS_UNCOMMITTED" -eq 1 ]]; then
    NEEDS_CONFIRM=1
  elif [[ -n "$LAST_STARTED_HEAD" && "$LAST_STARTED_HEAD" != "$CURRENT_HEAD" ]]; then
    NEEDS_CONFIRM=1
  fi
fi

if [[ "$NEEDS_CONFIRM" -eq 1 ]]; then
  echo "检测到代码变更或首次启动。"
  read -r -p "是否启动服务？[y/N] " answer
  case "$answer" in
    [Yy]|[Yy][Ee][Ss])
      ;;
    *)
      echo "已取消启动。"
      exit 0
      ;;
  esac
fi

echo "→ 启动服务..."
"$ROOT/scripts/start-local.sh"
echo "$CURRENT_HEAD" > "$STATE_FILE"
echo "已记录本次启动提交: $CURRENT_HEAD"
