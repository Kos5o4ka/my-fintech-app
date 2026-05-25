#!/bin/bash
# pg_dump бэкап базы myapp_db.
# Хранит последние 7 дней, запускается по крону.
set -euo pipefail

DB_URL="postgresql://admin_user:Y8il6HCiHR6eT34kPL@localhost/myapp_db"
BACKUP_DIR="/root/db_backups"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
FILE="$BACKUP_DIR/myapp_db_$TIMESTAMP.sql.gz"

mkdir -p "$BACKUP_DIR"

pg_dump "$DB_URL" | gzip > "$FILE"
echo "[$(date)] Backup saved: $FILE ($(du -sh "$FILE" | cut -f1))"

# Удалить бэкапы старше 7 дней
find "$BACKUP_DIR" -name "myapp_db_*.sql.gz" -mtime +7 -delete
echo "[$(date)] Old backups cleaned."
