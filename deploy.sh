#!/bin/bash
set -e

echo "=== Jatahku Deploy ==="
cd /opt/jatahku/app

# Pull latest
sudo -u jatahku git pull origin main

# Backend
sudo chown -R jatahku:jatahku /opt/jatahku/app/
sudo systemctl restart jatahku

# Frontend
if [ -d "frontend" ]; then
    cd /opt/jatahku/app/frontend
    sudo -u jatahku npm install --silent 2>/dev/null || true
    sudo -u jatahku npm run build
    sudo cp -r dist/* /home/jatahku/web/jatahku.com/public_html/
    sudo cp /home/jatahku/web/jatahku.com/public_html/index.html /home/jatahku/web/jatahku.com/public_html/app.html
    # Preserve landing + legal pages
    for f in landing.html privacy.html terms.html favicon.svg og-image.png og-image.svg; do
        if [ -f "/opt/jatahku/app/$f" ]; then
            sudo cp "/opt/jatahku/app/$f" "/home/jatahku/web/jatahku.com/public_html/$f"
        fi
    done
fi

# Re-register Telegram webhook (sync secret token after restart)
sleep 3
sudo -u jatahku bash -c 'source /opt/jatahku/venv/bin/activate && python3 -c "
from app.core.config import get_settings
import urllib.request, json, urllib.parse
s = get_settings()
if not s.TELEGRAM_BOT_TOKEN or not s.TELEGRAM_WEBHOOK_URL:
    print(\"⚠️  Telegram webhook skip — token/url not configured\")
    exit(0)
data = urllib.parse.urlencode({\"url\": s.TELEGRAM_WEBHOOK_URL, \"secret_token\": s.TELEGRAM_WEBHOOK_SECRET}).encode()
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
