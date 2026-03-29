#!/bin/bash
# Jatahku Full Backup Script (DB + uploads + .env)
# Cron: 0 2 * * * /opt/jatahku/backup.sh >> /var/log/jatahku-backup.log 2>&1

set -euo pipefail

ENV_FILE="/opt/jatahku/.env"
BACKUP_DIR="/opt/jatahku/backups"
UPLOADS_DIR="/home/jatahku/web/jatahku.com/public_html/uploads"
RETAIN_DAYS=7
DATE=$(date +%Y-%m-%d_%H%M)

# Load env vars
if [ -f "$ENV_FILE" ]; then
    export $(grep -E '^(TELEGRAM_BOT_TOKEN|ADMIN_TELEGRAM_ID|DATABASE_URL)=' "$ENV_FILE" | xargs)
fi

# Parse DATABASE_URL: postgresql+asyncpg://user:pass@host:port/dbname
DB_URL="${DATABASE_URL:-}"
DB_URL="${DB_URL/postgresql+asyncpg:\/\//postgresql:\/\/}"
DB_USER=$(echo "$DB_URL" | sed -E 's|postgresql://([^:]+):.*|\1|')
DB_PASS=$(echo "$DB_URL" | sed -E 's|postgresql://[^:]+:([^@]+)@.*|\1|')
DB_HOST=$(echo "$DB_URL" | sed -E 's|.*@([^:/]+)[:/].*|\1|')
DB_PORT=$(echo "$DB_URL" | sed -E 's|.*:([0-9]+)/.*|\1|')
DB_NAME=$(echo "$DB_URL" | sed -E 's|.*/([^?]+).*|\1|')
export PGPASSWORD="$DB_PASS"

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

ERRORS=()

# --- 1. Database ---
DB_FILE="jatahku_db_${DATE}.sql.gz"
DB_PATH="${BACKUP_DIR}/${DB_FILE}"
if pg_dump -h "${DB_HOST:-localhost}" -p "${DB_PORT:-5432}" -U "$DB_USER" "$DB_NAME" | gzip > "$DB_PATH"; then
    DB_SIZE=$(du -sh "$DB_PATH" | cut -f1)
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] DB backup OK: $DB_FILE ($DB_SIZE)"
    find "$BACKUP_DIR" -name "jatahku_db_*.sql.gz" -mtime +${RETAIN_DAYS} -delete
else
    ERRORS+=("Database backup gagal")
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] DB backup FAILED"
fi

# --- 2. Uploads ---
UPLOADS_FILE="jatahku_uploads_${DATE}.tar.gz"
UPLOADS_PATH="${BACKUP_DIR}/${UPLOADS_FILE}"
if [ -d "$UPLOADS_DIR" ]; then
    if tar -czf "$UPLOADS_PATH" -C "$(dirname $UPLOADS_DIR)" "$(basename $UPLOADS_DIR)" 2>/dev/null; then
        UPLOADS_SIZE=$(du -sh "$UPLOADS_PATH" | cut -f1)
        echo "[$(date '+%Y-%m-%d %H:%M:%S')] Uploads backup OK: $UPLOADS_FILE ($UPLOADS_SIZE)"
        find "$BACKUP_DIR" -name "jatahku_uploads_*.tar.gz" -mtime +${RETAIN_DAYS} -delete
    else
        ERRORS+=("Uploads backup gagal")
        echo "[$(date '+%Y-%m-%d %H:%M:%S')] Uploads backup FAILED"
    fi
else
    UPLOADS_SIZE="0 (folder kosong)"
fi

# --- 3. .env ---
ENV_BACKUP="${BACKUP_DIR}/jatahku_env_${DATE}.enc"
if openssl enc -aes-256-cbc -pbkdf2 -pass pass:"${DB_PASS}" -in "$ENV_FILE" -out "$ENV_BACKUP" 2>/dev/null; then
    find "$BACKUP_DIR" -name "jatahku_env_*.enc" -mtime +${RETAIN_DAYS} -delete
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] .env backup OK (encrypted)"
else
    ERRORS+=(".env backup gagal")
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] .env backup FAILED"
fi

DB_COUNT=$(find "$BACKUP_DIR" -name "jatahku_db_*.sql.gz" | wc -l)
TOTAL_SIZE=$(du -sh "$BACKUP_DIR" | cut -f1)

if [ ${#ERRORS[@]} -eq 0 ]; then
    send_tg "✅ <b>Backup Jatahku berhasil</b>
📅 $(date '+%Y-%m-%d %H:%M WIB')

🗄 <b>Database:</b> ${DB_SIZE}
🖼 <b>Uploads:</b> ${UPLOADS_SIZE:-"-"}
🔐 <b>.env:</b> terenkripsi (AES-256)

📁 Lokasi: <code>${BACKUP_DIR}/</code>
🗂 Retensi: ${DB_COUNT}/${RETAIN_DAYS} hari tersimpan
💾 Total ukuran folder: ${TOTAL_SIZE}"
else
    ERROR_MSG=$(printf '%s\n' "${ERRORS[@]}")
    send_tg "❌ <b>Backup Jatahku GAGAL!</b>
📅 $(date '+%Y-%m-%d %H:%M')
⚠️ Error: ${ERROR_MSG}
📁 Lokasi: <code>${BACKUP_DIR}/</code>
🔍 Log: <code>sudo tail -30 /var/log/jatahku-backup.log</code>"
    exit 1
fi
