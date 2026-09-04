#!/usr/bin/env bash
# =============================================================================
# deploy.sh – install Docker (if needed), configure .env, build and start the
# stack, then run the verification. Idempotent: re-run to upgrade.
#
#   ./scripts/deploy.sh                     # interactive-free, uses env vars below if set
#
# Optional environment variables (written into .env when provided):
#   TELEGRAM_BOT_TOKEN, TELEGRAM_CHANNEL_ID, BINANCE_TESTNET (true|false),
#   BINANCE_API_KEY, BINANCE_SECRET, POSTGRES_PASSWORD, ADMIN_TOKEN, MIN_CONVICTION …
#   (any KEY present in .env.example can be passed this way)
# =============================================================================
set -euo pipefail
cd "$(dirname "$0")/.."

log() { echo -e "\n\033[1;36m▶ $*\033[0m"; }

# ---------------------------------------------------------------- docker ----
if ! command -v docker >/dev/null 2>&1; then
  log "Installing Docker"
  curl -fsSL https://get.docker.com | sudo sh
  sudo usermod -aG docker "$USER" || true
  sudo systemctl enable --now docker
fi
DOCKER="docker"
if ! docker info >/dev/null 2>&1; then DOCKER="sudo docker"; fi
if $DOCKER compose version >/dev/null 2>&1; then COMPOSE="$DOCKER compose"; else
  log "Installing docker compose plugin"
  sudo apt-get update -qq && sudo apt-get install -y -qq docker-compose-plugin
  COMPOSE="$DOCKER compose"
fi

# ------------------------------------------------------------------ swap ----
if [[ "$(free -m | awk '/Swap:/{print $2}')" == "0" ]] && [[ "$(free -m | awk '/Mem:/{print $2}')" -lt 4000 ]]; then
  log "Adding 2 GB swap (small VM)"
  sudo fallocate -l 2G /swapfile && sudo chmod 600 /swapfile && sudo mkswap /swapfile && sudo swapon /swapfile
  grep -q '/swapfile' /etc/fstab || echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab >/dev/null
fi

# -------------------------------------------------------------- firewall ----
if command -v iptables >/dev/null 2>&1 && sudo iptables -L INPUT -n 2>/dev/null | grep -q "REJECT"; then
  log "Opening ports 8000/8501 in iptables (Oracle images block them by default)"
  for p in 8000 8501; do
    sudo iptables -C INPUT -m state --state NEW -p tcp --dport $p -j ACCEPT 2>/dev/null || \
      sudo iptables -I INPUT 6 -m state --state NEW -p tcp --dport $p -j ACCEPT
  done
  command -v netfilter-persistent >/dev/null 2>&1 && sudo netfilter-persistent save >/dev/null 2>&1 || true
fi

# ------------------------------------------------------------------ .env ----
log "Configuring .env"
[[ -f .env ]] || cp .env.example .env
set_kv() {  # set_kv KEY VALUE  (replace or append)
  local k="$1" v="$2"
  if grep -qE "^${k}=" .env; then sed -i "s|^${k}=.*|${k}=${v}|" .env; else echo "${k}=${v}" >> .env; fi
}
# generate a strong DB password on first deploy if still default
if grep -qE '^POSTGRES_PASSWORD=crypto_password_123$' .env && [[ -z "${POSTGRES_PASSWORD:-}" ]]; then
  POSTGRES_PASSWORD="$(head -c 24 /dev/urandom | base64 | tr -dc 'A-Za-z0-9' | head -c 24)"
fi
[[ -z "${ADMIN_TOKEN:-}" ]] && grep -qE '^ADMIN_TOKEN=$' .env && ADMIN_TOKEN="$(head -c 24 /dev/urandom | base64 | tr -dc 'A-Za-z0-9' | head -c 32)"
for key in $(grep -oE '^[A-Z_]+=' .env.example | tr -d '='); do
  val="${!key:-}"
  [[ -n "$val" ]] && set_kv "$key" "$val"
done
# keep DATABASE_URL consistent with the postgres password for host-side tools
PGP="$(grep -E '^POSTGRES_PASSWORD=' .env | cut -d= -f2-)"
set_kv DATABASE_URL "postgresql://crypto_user:${PGP}@localhost:5432/crypto_signals"
chmod 600 .env
echo "  TELEGRAM token: $([[ -n "$(grep -E '^TELEGRAM_BOT_TOKEN=' .env | cut -d= -f2-)" ]] && echo yes || echo no)   channel: $(v="$(grep -E '^TELEGRAM_CHANNEL_ID=' .env | cut -d= -f2-)"; [[ -n "$v" ]] && echo "$v" || echo auto-discover)"
echo "  BINANCE_TESTNET: $(grep -E '^BINANCE_TESTNET=' .env | cut -d= -f2-)   DATA_SOURCE: $(grep -E '^DATA_SOURCE=' .env | cut -d= -f2-)"

# ------------------------------------------------------------- build/run ----
log "Building and starting containers"
$COMPOSE pull postgres
$COMPOSE up -d --build --remove-orphans

log "Waiting for services"
for i in $(seq 1 60); do
  if curl -fsS -m 3 http://localhost:8000/health >/dev/null 2>&1; then break; fi
  sleep 3
done
sleep 5
$COMPOSE ps

log "Verification"
chmod +x scripts/*.sh
./scripts/verify.sh --quick || true

PUBIP="$(curl -s -m 5 https://api.ipify.org 2>/dev/null || hostname -I | awk '{print $1}')"
log "Done"
echo "  Dashboard : http://${PUBIP}:8501"
echo "  API docs  : http://${PUBIP}:8000/docs"
echo "  Logs      : $COMPOSE logs -f backend"
echo "  Status    : ./scripts/report_status.sh"
