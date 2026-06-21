#!/usr/bin/env bash
#
# backup.sh — 备份这套 RAG 系统的全部本地状态。
#
# 备份内容(全是本地文件,丢了无法恢复):
#   backend/chroma_db/   向量库
#   backend/users.db     账号库(SQLite)
#   docs/                课程文档
#   .env                 密钥与配置
#
# 用法:
#   ./scripts/backup.sh                 # 备份到 ./_backups
#   BACKUP_DEST=/opt/backups ./scripts/backup.sh
#   RETAIN_DAYS=30 ./scripts/backup.sh  # 保留天数(默认 14)
#
# 定时(每天 03:00):
#   echo "0 3 * * * root /opt/course-rag/scripts/backup.sh" | sudo tee /etc/cron.d/course-rag-backup
set -euo pipefail

# 仓库根目录 = 本脚本所在目录的上一级
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEST="${BACKUP_DEST:-$ROOT/_backups}"
RETAIN_DAYS="${RETAIN_DAYS:-14}"
TS="$(date +%Y%m%d-%H%M%S)"
ARCHIVE="$DEST/course-rag-$TS.tar.gz"

mkdir -p "$DEST"

# 只打包存在的项,避免首次运行(还没 users.db / chroma_db)时报错
ITEMS=()
for p in backend/chroma_db backend/users.db docs .env; do
  [ -e "$ROOT/$p" ] && ITEMS+=("$p")
done

if [ "${#ITEMS[@]}" -eq 0 ]; then
  echo "⚠️  没有可备份的数据(chroma_db/users.db/docs/.env 都不存在)。先启动过一次应用?" >&2
  exit 1
fi

echo "→ 备份: ${ITEMS[*]}"
tar -czf "$ARCHIVE" -C "$ROOT" "${ITEMS[@]}"
chmod 600 "$ARCHIVE"   # 含 .env,限权

# 清理过期备份
find "$DEST" -name 'course-rag-*.tar.gz' -mtime "+$RETAIN_DAYS" -delete 2>/dev/null || true

echo "✅ 已备份 → $ARCHIVE ($(du -h "$ARCHIVE" | cut -f1))"
echo "   现有备份: $(find "$DEST" -name 'course-rag-*.tar.gz' | wc -l | tr -d ' ') 个,保留 $RETAIN_DAYS 天"
