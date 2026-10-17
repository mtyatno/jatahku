#!/bin/bash
set -e

echo "=== Jatahku Deploy ==="
cd /opt/jatahku/app

# Clean files regenerated on the server (dist + lockfiles) so they don't
# block `git pull`. npm install rewrites package-lock.json each deploy;
# the repo lockfile is the source of truth.
# One path per checkout: a path git doesn't track (blog/dist/) makes a combined
# checkout abort without restoring any of the others.
for p in frontend/dist/ blog/dist/ frontend/package-lock.json blog/package-lock.json; do
    sudo -u jatahku git checkout -- "$p" 2>/dev/null || true
done

# Pull latest
sudo -u jatahku git pull origin main

# Migrasi database: deploy TIDAK menjalankan alembic (lihat checklist di AGENTS.md),
# tapi model yang memetakan kolom baru membuat API 500 sampai migrasinya jalan
# (insiden 17 Okt 2026: c5e9a2d7f4b1 `envelopes.is_emergency` tertinggal).
# Bandingkan revisi DB dengan head di repo; tertinggal → peringatan sekarang, dan
# deploy diakhiri gagal setelah semua langkah lain selesai supaya notifikasi
# "Deploy GAGAL" di Telegram terkirim.
ALEMBIC="sudo -u jatahku /opt/jatahku/venv/bin/alembic"
revisi() { $ALEMBIC "$1" 2>/dev/null | grep -oE '^[0-9a-f]+' | sort | xargs || true; }
MIG_DB=$(revisi current)
MIG_HEAD=$(revisi heads)
MIG_PENDING=""
if [ -z "$MIG_HEAD" ]; then
    echo "⚠️  Cek migrasi dilewati — alembic heads tidak terbaca"
elif [ "$MIG_DB" != "$MIG_HEAD" ]; then
    MIG_PENDING=1
    echo "⚠️  MIGRASI BELUM JALAN — database: ${MIG_DB:-kosong}, repo head: $MIG_HEAD"
    $ALEMBIC history -r "${MIG_DB%% *}:heads" 2>/dev/null | grep -v " -> ${MIG_DB%% *}[ ,]" || true
    echo "   Jalankan: cd /opt/jatahku/app && $ALEMBIC upgrade head && sudo systemctl restart jatahku"
else
    echo "✅ Migrasi database mutakhir ($MIG_HEAD)"
fi

# Backend
sudo chown -R jatahku:jatahku /opt/jatahku/app/
sudo systemctl restart jatahku

# Pastikan proses API yang melayani benar-benar menjalankan commit yang baru
# di-pull (/health melaporkan commit-nya, lihat app/core/version.py). Kalau
# tidak, hentikan deploy sebelum frontend baru dipasang — frontend & backend
# tetap di versi yang sama — dan tampilkan log service untuk diagnosis.
EXPECTED=$(sudo -u jatahku git -C /opt/jatahku/app rev-parse HEAD)
RUNNING=""
for i in $(seq 1 30); do
    RUNNING=$(curl -s --max-time 3 http://127.0.0.1:8000/health 2>/dev/null \
        | python3 -c "import sys,json;print(json.load(sys.stdin).get('commit',''))" 2>/dev/null || true)
    if [ "$RUNNING" = "$EXPECTED" ]; then
        break
    fi
    sleep 2
done
if [ "$RUNNING" != "$EXPECTED" ]; then
    echo "❌ API menjalankan '${RUNNING:-tidak menjawab}', seharusnya $EXPECTED"
    sudo systemctl status jatahku --no-pager -n 0 || true
    sudo journalctl -u jatahku -n 40 --no-pager || true
    sudo ss -ltnp 2>/dev/null | grep ':8000' || true
    exit 1
fi
echo "✅ API menjalankan ${EXPECTED:0:7}"

# Frontend
if [ -d "frontend" ]; then
    cd /opt/jatahku/app/frontend
    sudo -u jatahku npm install --silent 2>/dev/null || true
    sudo -u jatahku npm run build
    sudo cp -r dist/* /home/jatahku/web/jatahku.com/public_html/
    sudo cp /home/jatahku/web/jatahku.com/public_html/index.html /home/jatahku/web/jatahku.com/public_html/app.html
    # Landing + legal pages: versi repo yang dipasang (perubahan landing harus tayang).
    # Backup hanya cadangan bila file repo hilang/kosong, dan diperbarui setiap kali
    # versi repo terpasang.
    restore_file() {
        local f="$1"
        local src="/opt/jatahku/app/$f"
        local backup="/opt/jatahku/backups/$f"
        local dest="/home/jatahku/web/jatahku.com/public_html/$f"
        if [ -f "$src" ] && [ -s "$src" ]; then
            sudo cp "$src" "$dest"
        elif [ -f "$backup" ] && [ -s "$backup" ]; then
            sudo cp "$backup" "$dest"
        fi
        if [ -f "$dest" ] && [ -s "$dest" ]; then
            sudo mkdir -p /opt/jatahku/backups
            sudo cp "$dest" "$backup"
        fi
    }
    # favicon.svg is owned by frontend/public now — restoring it would put the old icon back
    for f in landing.html privacy.html terms.html og-image.png og-image.svg; do
        restore_file "$f"
    done
fi

# Blog: dibangun di CI (job deploy-blog di deploy.yml) lalu di-SCP ke /tmp/blog-dist-new/.
if [ -d "/tmp/blog-dist-new" ]; then
    rsync -a --delete /tmp/blog-dist-new/ /home/jatahku/web/blog.jatahku.com/public_html/
    rm -rf /tmp/blog-dist-new/
    echo "✅ Blog terpasang"
else
    echo "⚠️  Blog dilewati — /tmp/blog-dist-new tidak ada"
fi

# Re-register Telegram webhook (sync secret token after restart)
cd /opt/jatahku/app   # python -c mengimpor paket app dari sini
sleep 3
sudo -u jatahku bash -c 'source /opt/jatahku/venv/bin/activate && python3 -c "
from app.core.config import get_settings
import urllib.request, json, urllib.parse
s = get_settings()
if not s.TELEGRAM_BOT_TOKEN or not s.TELEGRAM_WEBHOOK_URL:
    print(\"⚠️  Telegram webhook skip — token/url not configured\")
    exit(0)
params = {\"url\": s.TELEGRAM_WEBHOOK_URL}
if s.TELEGRAM_WEBHOOK_SECRET:
    params[\"secret_token\"] = s.TELEGRAM_WEBHOOK_SECRET
data = urllib.parse.urlencode(params).encode()
req = urllib.request.Request(f\"https://api.telegram.org/bot{s.TELEGRAM_BOT_TOKEN}/setWebhook\", data=data)
r = json.loads(urllib.request.urlopen(req).read())
print(\"✅ Webhook registered\" if r.get(\"ok\") else f\"⚠️  Webhook error: {r}\")
" 2>/dev/null || echo "⚠️  Webhook registration failed"' || true

# Health check
sleep 5
HEALTH_RESPONSE=$(curl -s https://api.jatahku.com/health 2>/dev/null || echo '{"status":"error"}')
STATUS=$(echo "$HEALTH_RESPONSE" | python3 -c "import sys,json;print(json.load(sys.stdin).get('status','unknown'))" 2>/dev/null || echo "unknown")
if [ "$STATUS" = "healthy" ]; then
    echo "✅ Deploy success — API healthy"
else
    echo "⚠️ Deploy warning — API status: $STATUS"
fi

if [ -n "$MIG_PENDING" ]; then
    echo "❌ Kode baru sudah terpasang, tapi migrasi database belum jalan (database: ${MIG_DB:-kosong}, head: $MIG_HEAD)."
    echo "   Jalankan: cd /opt/jatahku/app && $ALEMBIC upgrade head && sudo systemctl restart jatahku"
    exit 2
fi
