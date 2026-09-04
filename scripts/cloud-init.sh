#!/bin/bash
# =============================================================================
# cloud-init.sh – ZERO-TOUCH installer for a fresh Ubuntu VM.
#
# Paste this whole file into the "cloud-init script" box when creating the VM
# (Oracle Cloud: Create instance → Show advanced options → Management →
# Initialization script → Paste cloud-init script).  Edit the two values in the
# CONFIG block first.  The VM installs Docker, clones the repository, deploys the
# 24/7 stack and verifies it – nobody has to SSH into the machine.
#
# Afterwards: the Telegram bot posts "Crypto Signal Bot online" as soon as it is
# added as administrator of a channel; the dashboard is on http://<public-ip>:8501
# (open ports 8000/8501 in the cloud security list – see docs/DEPLOYMENT.md §2).
#
# Also usable on an existing machine:   sudo bash scripts/cloud-init.sh
# =============================================================================

# ------------------------------- CONFIG --------------------------------------
TELEGRAM_BOT_TOKEN="PASTE_TOKEN_FROM_BOTFATHER_HERE"
BINANCE_TESTNET="true"                 # keep true until the owner approves live data
# Optional overrides (leave empty for auto-discovery / defaults)
TELEGRAM_CHANNEL_ID=""
TELEGRAM_ADMIN_CHAT_ID=""
REPO_URL="https://github.com/Acekiller88/cripsignalsep26.git"
REPO_BRANCH="arena/01a06815-cripsignalsep26"
INSTALL_USER="${SUDO_USER:-ubuntu}"    # the login user of the VM (ubuntu / opc)
# -----------------------------------------------------------------------------

set -uo pipefail
export DEBIAN_FRONTEND=noninteractive
LOG=/var/log/crypto-signal-bot-install.log
exec > >(tee -a "$LOG") 2>&1
echo "===== crypto-signal-bot cloud-init started $(date -u '+%F %T UTC') ====="

if [[ "$TELEGRAM_BOT_TOKEN" == "PASTE_TOKEN_FROM_BOTFATHER_HERE" ]]; then
  echo "WARNING: TELEGRAM_BOT_TOKEN not set – the bot will run but only log messages."
  TELEGRAM_BOT_TOKEN=""
fi

id "$INSTALL_USER" >/dev/null 2>&1 || INSTALL_USER="$(getent passwd 1000 | cut -d: -f1)"
HOME_DIR="$(getent passwd "$INSTALL_USER" | cut -d: -f6)"
APP_DIR="$HOME_DIR/crypto-signal-bot"

# ---------------------------------------------------------------- packages ---
for i in 1 2 3 4 5; do
  apt-get update -qq && apt-get install -y -qq git curl ca-certificates python3 iptables-persistent >/dev/null && break
  echo "apt busy/failed (attempt $i) – retrying in 20s"; sleep 20
done

if ! command -v docker >/dev/null 2>&1; then
  for i in 1 2 3; do curl -fsSL https://get.docker.com | sh && break; sleep 15; done
fi
systemctl enable --now docker
usermod -aG docker "$INSTALL_USER" || true

# ------------------------------------------------------------------- swap ----
MEM_MB="$(free -m | awk '/Mem:/{print $2}')"
if [[ "$(free -m | awk '/Swap:/{print $2}')" == "0" && "$MEM_MB" -lt 4000 ]]; then
  fallocate -l 2G /swapfile && chmod 600 /swapfile && mkswap /swapfile && swapon /swapfile
  grep -q '/swapfile' /etc/fstab || echo '/swapfile none swap sw 0 0' >> /etc/fstab
fi

# --------------------------------------------------------------- firewall ----
# Oracle/Ubuntu images ship an iptables INPUT chain that rejects everything but 22.
for p in 8000 8501; do
  iptables -C INPUT -m state --state NEW -p tcp --dport $p -j ACCEPT 2>/dev/null || \
    iptables -I INPUT 5 -m state --state NEW -p tcp --dport $p -j ACCEPT
done
netfilter-persistent save >/dev/null 2>&1 || true

# ------------------------------------------------------------------- code ----
if [[ -d "$APP_DIR/.git" ]]; then
  git -C "$APP_DIR" fetch -q origin && git -C "$APP_DIR" checkout -q "$REPO_BRANCH" && git -C "$APP_DIR" pull -q
else
  for i in 1 2 3; do git clone -q -b "$REPO_BRANCH" "$REPO_URL" "$APP_DIR" && break; sleep 10; done
fi
chown -R "$INSTALL_USER:$INSTALL_USER" "$APP_DIR"
chmod +x "$APP_DIR"/scripts/*.sh

# ----------------------------------------------------------------- deploy ----
cd "$APP_DIR"
export TELEGRAM_BOT_TOKEN TELEGRAM_CHANNEL_ID TELEGRAM_ADMIN_CHAT_ID BINANCE_TESTNET
export DATA_SOURCE=binance
./scripts/deploy.sh
chown "$INSTALL_USER:$INSTALL_USER" .env

# -------------------------------------------------------- daily self-report ---
# Every day at 00:15 UTC the status report is written to /var/log/crypto-signal-bot-daily.log
cat > /etc/cron.d/crypto-signal-bot <<EOF
15 0 * * * root cd $APP_DIR && ./scripts/report_status.sh 7 >> /var/log/crypto-signal-bot-daily.log 2>&1
EOF

PUBIP="$(curl -s -m 5 https://api.ipify.org || hostname -I | awk '{print $1}')"
echo
echo "===== crypto-signal-bot cloud-init finished $(date -u '+%F %T UTC') ====="
echo "Dashboard : http://${PUBIP}:8501"
echo "API       : http://${PUBIP}:8000"
echo "Install log: $LOG   Daily report: /var/log/crypto-signal-bot-daily.log"
