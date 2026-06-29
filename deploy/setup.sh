#!/usr/bin/env bash
# One-shot setup for tenderbot on a fresh Ubuntu 22.04/24.04 VPS.
# Run from the project root after cloning/copying the code:
#     bash deploy/setup.sh
# Idempotent — safe to re-run.
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_DIR"
echo ">> project dir: $PROJECT_DIR"

echo ">> [1/5] system packages"
sudo apt-get update -y
sudo apt-get install -y python3-venv python3-pip wget ca-certificates

# Chrome can spike RAM; on a small (<2GB) droplet add swap so it doesn't OOM.
TOTAL_KB=$(awk '/MemTotal/{print $2}' /proc/meminfo)
if [ "${TOTAL_KB:-0}" -lt 2000000 ] && [ ! -f /swapfile ]; then
  echo ">> adding 2G swap (low RAM detected)"
  sudo fallocate -l 2G /swapfile || sudo dd if=/dev/zero of=/swapfile bs=1M count=2048
  sudo chmod 600 /swapfile
  sudo mkswap /swapfile
  sudo swapon /swapfile
  grep -q '/swapfile' /etc/fstab || echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
fi

echo ">> [2/5] Google Chrome (best at passing Cloudflare)"
if ! command -v google-chrome >/dev/null 2>&1; then
  wget -q https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb -O /tmp/chrome.deb
  sudo apt-get install -y /tmp/chrome.deb
  rm -f /tmp/chrome.deb
fi
google-chrome --version || true

echo ">> [3/5] python venv + dependencies"
python3 -m venv .venv
# shellcheck disable=SC1091
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
# Shared libraries Chrome/Chromium need (does not download a browser binary)
python -m playwright install-deps chromium

echo ">> [4/5] config files"
[ -f .env ] || { cp .env.example .env; echo "   created .env (EDIT IT: Telegram token + chat id)"; }
[ -f filters.yaml ] || { cp filters.example.yaml filters.yaml; echo "   created filters.yaml (EDIT your criteria)"; }

echo ">> [5/5] done."
cat <<EOF

Next steps:
  1. Edit secrets:    nano .env          # TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
  2. Edit filters:    nano filters.yaml
  3. Test Telegram:   .venv/bin/python -m tenderbot --test-telegram
  4. Seed silently:   .venv/bin/python -m tenderbot --once
  5. Install service: see deploy/tenderbot.service and the README runbook.
EOF
