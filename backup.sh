#!/bin/bash
# Jatahku DB Backup Script
# Cron: 0 2 * * * /opt/jatahku/backup.sh >> /var/log/jatahku-backup.log 2>&1

set -euo pipefail

ENV_FILE="/opt/jatahku/.env"
BACKUP_DIR="/opt/jatahku/backups"
DB_NAME="jatahku_db"
RETAIN_DAYS=7
DATE=$(date +%Y-%m-%d_%H%M)
FILENAME="jatahku_db_${DATE}.sql.gz"
FILEPATH="${BACKUP_DIR}/${FILENAME}"

# Load env vars
if [ -f "$ENV_FILE" ]; then
    export $(grep -E '^(TELEGRAM_BOT_TOKEN|ADMIN_TELEGRAM_ID)=' "$ENV_FILE" | xargs)
fi

send_tg() {
    local msg="$1"
    if [ -n "${TELEGRAM_BOT_TOKEN:-}" ] && [ -n "${ADMIN_TELEGRAM_ID:-}" ]; then
        curl -s -X POST "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" \
            -d chat_id="${ADMIN_TELEGRAM_ID}" \
            -d text="${msg}" \
            -d parse_mode="HTML" > /dev/null 2>&1 || true
    fi
}

mkdir -p "$BACKUP_DIR"

echo "[$(date '+%Y-%m-%d %H:%M:%S')] Starting backup..."

if pg_dump -U jatahku "$DB_NAME" | gzip > "$FILEPATH"; then
    SIZE=$(du -sh "$FILEPATH" | cut -f1)
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Backup OK: $FILENAME ($SIZE)"

    # Delete old backups
    find "$BACKUP_DIR" -name "jatahku_db_*.sql.gz" -mtime +${RETAIN_DAYS} -delete
    COUNT=$(find "$BACKUP_DIR" -name "jatahku_db_*.sql.gz" | wc -l)

    send_tg "✅ <b>Backup Jatahku berhasil</b>
📦 File: <code>${FILENAME}</code>
📏 Size: ${SIZE}
🗂 Total backup tersimpan: ${COUNT} file"
else
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Backup FAILED!"
    send_tg "❌ <b>Backup Jatahku GAGAL!</b>
📅 Waktu: $(date '+%Y-%m-%d %H:%M')
⚠️ Cek log: <code>sudo tail -20 /var/log/jatahku-backup.log</code>"
    exit 1
fi
