#!/usr/bin/env bash
# =============================================================================
# verify.sh – one-shot verification of a deployed Crypto Signal Bot stack.
#
# Runs every check an operator needs and prints a single copy-paste report
# (between the ===== REPORT ===== markers). Safe to run repeatedly.
#
#   ./scripts/verify.sh            # verify the docker compose stack on this host
#   ./scripts/verify.sh --quick    # skip the backtest (faster)
#
# Exit code 0 = all mandatory checks passed, 1 = something needs attention.
# =============================================================================
set -u
cd "$(dirname "$0")/.."

QUICK=0
[[ "${1:-}" == "--quick" ]] && QUICK=1

API_PORT="${API_PORT:-8000}"
DASH_PORT="${DASH_PORT:-8501}"
API="http://localhost:${API_PORT}"
PASS=0; FAIL=0; WARN=0
declare -a LINES

ok()   { PASS=$((PASS+1)); LINES+=("PASS  $1"); }
bad()  { FAIL=$((FAIL+1)); LINES+=("FAIL  $1"); }
warn() { WARN=$((WARN+1)); LINES+=("WARN  $1"); }
have() { command -v "$1" >/dev/null 2>&1; }

json() { python3 -c "import sys,json; d=json.load(sys.stdin); print($1)" 2>/dev/null; }

compose() {
  if docker compose version >/dev/null 2>&1; then docker compose "$@"; else docker-compose "$@"; fi
}

# ---------------------------------------------------------------- host ------
HOST_INFO="$(uname -srm) | $(nproc 2>/dev/null || echo ?) cpu | $(free -m 2>/dev/null | awk '/Mem:/{print $2" MB RAM, "$7" MB avail"}') | disk $(df -h . 2>/dev/null | awk 'NR==2{print $4" free"}')"
have docker && ok "docker: $(docker --version 2>/dev/null | cut -d, -f1)" || bad "docker not installed"
(docker compose version >/dev/null 2>&1 || have docker-compose) && ok "docker compose available" || bad "docker compose not available"
[[ -f .env ]] && ok ".env present" || bad ".env missing (cp .env.example .env)"

# ------------------------------------------------------------ .env sanity ---
if [[ -f .env ]]; then
  getv() { grep -E "^$1=" .env | tail -1 | cut -d= -f2- | tr -d '"' | tr -d "'" ; }
  TG_TOKEN="$(getv TELEGRAM_BOT_TOKEN)"; TG_CHAT="$(getv TELEGRAM_CHANNEL_ID)"
  TESTNET="$(getv BINANCE_TESTNET)"; SRC="$(getv DATA_SOURCE)"; PGPASS="$(getv POSTGRES_PASSWORD)"
  if [[ -n "$TG_TOKEN" ]]; then ok "telegram token configured$([[ -n "$TG_CHAT" ]] && echo " (channel ${TG_CHAT})" || echo " (channel auto-discovery)")"; else warn "telegram NOT configured (bot runs, messages only logged)"; fi
  [[ "${SRC:-binance}" == "binance" ]] && ok "DATA_SOURCE=binance" || warn "DATA_SOURCE=${SRC} (synthetic = demo data, not real market)"
  [[ "${TESTNET:-true}" == "true" ]] && ok "BINANCE_TESTNET=true (paper mode)" || warn "BINANCE_TESTNET=false (LIVE market data)"
  [[ "$PGPASS" == "crypto_password_123" || -z "$PGPASS" ]] && warn "POSTGRES_PASSWORD is the default – change it" || ok "POSTGRES_PASSWORD customised"
fi

# ------------------------------------------------------------- containers ---
if have docker; then
  PS="$(compose ps --format '{{.Name}} {{.State}} {{.Status}}' 2>/dev/null)"
  for svc in crypto_postgres crypto_backend crypto_dashboard; do
    line="$(echo "$PS" | grep "^$svc " || true)"
    if [[ -z "$line" ]]; then bad "container $svc not found"
    elif echo "$line" | grep -q " running"; then
      if echo "$line" | grep -qi "unhealthy"; then bad "container $svc running but UNHEALTHY"
      else ok "container $svc running ($(echo "$line" | grep -oE '\(.*\)' || echo 'no healthcheck yet'))"; fi
    else bad "container $svc state: $line"; fi
  done
fi

# ------------------------------------------------------------------- API ----
HEALTH="$(curl -s -m 10 "$API/health" || true)"
if [[ -n "$HEALTH" ]]; then
  if echo "$HEALTH" | grep -q '"status":"ok"'; then ok "GET /health -> $HEALTH"; else bad "GET /health -> $HEALTH"; fi
else bad "API not reachable on $API"; fi

STATUS="$(curl -s -m 10 "$API/api/status" || true)"
if [[ -n "$STATUS" ]]; then
  g() { echo "$STATUS" | python3 scripts/report_lib.py get "$1"; }
  CYCLES="$(g live.cycles_completed)"; SRC_LIVE="$(g live.data_source.source)"; WS="$(g live.data_source.websocket_connected)"
  ENDPOINT="$(g live.data_source.endpoint)"; RESTFAIL="$(g live.data_source.rest_failures)"; LASTERR="$(g live.last_error)"
  TG_SENT="$(g live.telegram.sent)"; TG_FAIL="$(g live.telegram.failed)"; TG_ERR="$(g live.telegram.last_error)"
  TG_READY="$(g live.telegram.ready)"; TG_CHAN="$(g live.telegram.channel_id)"; TG_HINT="$(g live.telegram.hint)"
  UNSUP="$(g live.data_source.unsupported_symbols)"
  ACTIVE="$(g active_signals)"; TOTAL="$(g total_signals)"
  [[ "${CYCLES:-0}" -ge 1 ]] 2>/dev/null && ok "bot cycles completed: $CYCLES (source=$SRC_LIVE endpoint=$ENDPOINT)" || warn "no screening cycle completed yet (wait ~1 min after start)"
  [[ "$WS" == "True" ]] && ok "websocket connected" || warn "websocket not connected (REST fallback in use)"
  [[ -z "$RESTFAIL" || "$RESTFAIL" == "0" ]] && ok "no REST failures" || warn "REST failures: $RESTFAIL"
  [[ -z "$LASTERR" ]] && ok "no bot errors" || warn "last bot error: $LASTERR"
  [[ -z "$UNSUP" || "$UNSUP" == "[]" ]] || warn "symbols not listed on this endpoint (skipped): $UNSUP"
  if [[ -n "${TG_TOKEN:-}" ]]; then
    if [[ "$TG_READY" == "True" ]]; then
      [[ -z "$TG_FAIL" || "$TG_FAIL" == "0" ]] && ok "telegram: channel ${TG_CHAN}, ${TG_SENT:-0} sent, 0 failed" || bad "telegram failures: $TG_FAIL ($TG_ERR)"
    else warn "telegram: no channel yet – ${TG_HINT:-add the bot as administrator of your channel}"; fi
  fi
  LINES+=("INFO  signals: total=$TOTAL active=$ACTIVE")
  LINES+=("INFO  bot status:"$'\n'"$(echo "$STATUS" | python3 scripts/report_lib.py status)")
fi

MARKET="$(curl -s -m 10 "$API/api/market" || true)"
[[ -n "$MARKET" ]] && LINES+=("INFO  market snapshot:"$'\n'"$(echo "$MARKET" | python3 scripts/report_lib.py market)")

PERF="$(curl -s -m 10 "$API/api/performance" || true)"
[[ -n "$PERF" ]] && LINES+=("INFO  performance:"$'\n'"$(echo "$PERF" | python3 scripts/report_lib.py performance)")

# ------------------------------------------------------------- dashboard ----
DASH="$(curl -s -m 10 -o /dev/null -w '%{http_code}' "http://localhost:${DASH_PORT}/_stcore/health" || true)"
[[ "$DASH" == "200" ]] && ok "dashboard healthy on :$DASH_PORT" || bad "dashboard not healthy on :$DASH_PORT (http $DASH)"

# ------------------------------------------------------ in-container checks -
if have docker && docker ps --format '{{.Names}}' | grep -q '^crypto_backend$'; then
  CHECK="$(docker exec crypto_backend python main.py --check 2>&1 | grep -vE '^\s*$' | tail -12)"
  if echo "$CHECK" | grep -q "RESULT: ALL OK"; then ok "main.py --check: ALL OK"; else bad "main.py --check reported problems"; fi
  LINES+=("INFO  self-test output:"$'\n'"$(echo "$CHECK" | sed 's/^/  /')")
  if [[ $QUICK -eq 0 ]]; then
    BT="$(docker exec crypto_backend python backtest.py --days 30 2>/dev/null | grep -E 'BACKTEST|Signals|Win rate|Total PnL|Profit factor|Expectancy|TP1/TP2' | sed 's/^/  /')"
    [[ -n "$BT" ]] && LINES+=("INFO  30-day backtest (current .env parameters):"$'\n'"$BT") || warn "backtest produced no output (exchange unreachable?)"
  fi
  LOGS="$(docker logs --tail 15 crypto_backend 2>&1 | sed 's/^/  /')"
  LINES+=("INFO  last backend log lines:"$'\n'"$LOGS")
fi

# ----------------------------------------------------------------- report ---
echo
echo "===== REPORT ====="
echo "host: $HOST_INFO"
echo "time: $(date -u '+%Y-%m-%d %H:%M:%S UTC')  commit: $(git rev-parse --short HEAD 2>/dev/null || echo n/a)  branch: $(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo n/a)"
printf '%s\n' "${LINES[@]}"
echo "summary: PASS=$PASS WARN=$WARN FAIL=$FAIL"
echo "===== END REPORT ====="
[[ $FAIL -eq 0 ]]
