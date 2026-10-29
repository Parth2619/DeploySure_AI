#!/usr/bin/env bash
# Sets up DeploySure on a fresh Ubuntu 22.04 or 24.04 server. Run as the normal user (ubuntu), not root:
#   bash ~/deploysure/deploy/setup.sh
# Expects the deploysure folder in the home directory. Asks for the web password and the Groq key.
set -euo pipefail

APP_DIR="$HOME/deploysure"
[ -d "$APP_DIR" ] || { echo "Put the deploysure folder in $HOME first."; exit 1; }

sudo apt-get update
sudo apt-get install -y python3 python3-venv python3-pip git nginx apache2-utils

cd "$APP_DIR"
python3 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -r requirements.txt
.venv/bin/python -m playwright install --with-deps chromium   # the browser checks need it

# The demo repos have their own history, so rebuild the live one here.
cd "$HOME"
[ -d "$APP_DIR/demo_apps/tinyshop_live" ] || "$APP_DIR/.venv/bin/python" -m deploysure.demo_apps.build_tinyshop live "$APP_DIR/demo_apps/tinyshop_live"

# The Groq key goes in a file only root and the service can read, never in the code.
read -rsp "Groq API key (leave empty to run without AI): " KEY; echo
printf 'GROQ_API_KEY=%s\n' "$KEY" | sudo tee /etc/deploysure.env >/dev/null
sudo chmod 600 /etc/deploysure.env

# One shared password for the whole site. DeploySure runs the code of what it analyzes, so it must never be open.
read -rp "Web login name: " WEB_USER
sudo htpasswd -c /etc/nginx/deploysure.htpasswd "$WEB_USER"

sed "s|__USER__|$USER|g; s|__APP_DIR__|$APP_DIR|g; s|__PARENT_DIR__|$(dirname "$APP_DIR")|g""$APP_DIR/deploy/deploysure.service" | sudo tee /etc/systemd/system/deploysure.service >/dev/null
sudo cp "$APP_DIR/deploy/nginx-deploysure.conf" /etc/nginx/sites-available/deploysure
sudo ln -sf /etc/nginx/sites-available/deploysure /etc/nginx/sites-enabled/deploysure
sudo rm -f /etc/nginx/sites-enabled/default

sudo systemctl daemon-reload
sudo systemctl enable --now deploysure
sudo nginx -t && sudo systemctl reload nginx
echo "Done. Open http://<this server's public IP>/ and log in with the name and password you chose."
