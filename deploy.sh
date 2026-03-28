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

# Health check
sleep 5
HEALTH_RESPONSE=$(curl -s https://api.jatahku.com/health 2>/dev/null || echo '{"status":"error"}')
STATUS=$(echo "$HEALTH_RESPONSE" | python3 -c "import sys,json;print(json.load(sys.stdin).get('status','unknown'))" 2>/dev/null || echo "unknown")
if [ "$STATUS" = "healthy" ]; then
    echo "✅ Deploy success — API healthy"
else
    echo "⚠️ Deploy warning — API status: $STATUS"
fi
