#!/usr/bin/env bash
# =============================================================================
# smoke_local.sh – verify the code against the REAL exchange without Docker.
#
# Creates a virtualenv, installs dependencies, runs the test-suite, checks
# Binance connectivity (testnet + live, read-only market data), runs one
# screening cycle and a backtest, and prints a copy-paste report.
#
#   ./scripts/smoke_local.sh                 # default: 30-day backtest
#   BACKTEST_DAYS=90 ./scripts/smoke_local.sh
#
# Requirements: python3 (3.10+), internet access. No API keys needed.
# =============================================================================
set -u
cd "$(dirname "$0")/.."
ROOT="$(pwd)"
DAYS="${BACKTEST_DAYS:-30}"
PY="${PYTHON:-python3}"
VENV="$ROOT/.venv-smoke"
declare -a LINES; PASS=0; FAIL=0; WARN=0
ok()   { PASS=$((PASS+1)); LINES+=("PASS  $1"); }
bad()  { FAIL=$((FAIL+1)); LINES+=("FAIL  $1"); }
warn() { WARN=$((WARN+1)); LINES+=("WARN  $1"); }
info() { LINES+=("INFO  $1"); }
section() { echo; echo "──── $1"; }

section "python & venv"
$PY --version || { echo "python3 not found"; exit 1; }
[[ -d "$VENV" ]] || $PY -m venv "$VENV"
# shellcheck disable=SC1091
source "$VENV/bin/activate"
pip install -q --upgrade pip >/dev/null 2>&1
if pip install -q -r backend/requirements-dev.txt; then ok "dependencies installed ($(python --version 2>&1))"; else bad "pip install failed"; fi

section "unit tests (offline)"
cd backend
TEST_OUT="$(python -m pytest -q 2>&1 | tail -3)"
echo "$TEST_OUT"
if echo "$TEST_OUT" | grep -qE "^[0-9]+ passed" && ! echo "$TEST_OUT" | grep -q failed; then ok "pytest: $(echo "$TEST_OUT" | grep -oE '[0-9]+ passed')"; else bad "pytest failures – see output above"; fi

run_check() {  # $1 label, rest = env assignments
  local label="$1"; shift
  local out
  out="$(env "$@" DATABASE_URL="sqlite:///$ROOT/smoke_$label.db" TELEGRAM_BOT_TOKEN="${TELEGRAM_BOT_TOKEN:-}" TELEGRAM_CHANNEL_ID="${TELEGRAM_CHANNEL_ID:-}" timeout 180 python main.py --check 2>&1 | grep -vE '^\s*$')"
  echo "$out"
  if echo "$out" | grep -q "RESULT: ALL OK"; then ok "--check [$label]"; else
    if echo "$out" | grep -qiE "451|restricted location|Service unavailable from a restricted"; then bad "--check [$label]: Binance blocks this server's region (HTTP 451) – deploy in another region (e.g. Singapore/Tokyo/Frankfurt)"
    else bad "--check [$label] reported problems"; fi
  fi
  info "self-test [$label]:"$'\n'"$(echo "$out" | sed 's/^/  /')"
}

section "binance TESTNET connectivity (read-only)"
run_check testnet DATA_SOURCE=binance BINANCE_TESTNET=true ENABLE_WEBSOCKET=false

section "binance LIVE market data connectivity (read-only, no keys)"
run_check live DATA_SOURCE=binance BINANCE_TESTNET=false ENABLE_WEBSOCKET=false

section "one screening cycle on testnet (JSON summary)"
ONCE="$(DATA_SOURCE=binance BINANCE_TESTNET=true ENABLE_WEBSOCKET=false DATABASE_URL="sqlite:///$ROOT/smoke_testnet.db" LOG_LEVEL=INFO timeout 300 python main.py --once 2>&1)"
echo "$ONCE" | tail -60
if echo "$ONCE" | grep -q '"duration_s"'; then ok "--once completed on testnet"; else bad "--once failed on testnet"; fi
info "cycle log:"$'\n'"$(echo "$ONCE" | grep -E 'close=|NEW SIGNAL|blocked|skipping|WARNING|ERROR' | sed 's/^/  /' | head -20)"

section "websocket smoke (live endpoint, 40 s)"
WS_OUT="$(DATA_SOURCE=binance BINANCE_TESTNET=false ENABLE_WEBSOCKET=true DATABASE_URL="sqlite:///$ROOT/smoke_ws.db" timeout 60 python - <<'EOF' 2>&1
import asyncio, time
from config import settings
from data_collector import BinanceDataCollector
async def main():
    c = BinanceDataCollector(settings)
    await c.start(["BTCUSDT", "ETHUSDT"])
    t0 = time.time(); connected = False
    while time.time() - t0 < 40:
        await asyncio.sleep(2)
        if c.websocket_connected:
            connected = True; break
    st = c.stats()
    print("WS_CONNECTED" if connected else "WS_NOT_CONNECTED", "after", round(time.time()-t0,1), "s; cached:", st["cached_streams"])
    if connected:
        p = await c.get_last_price("BTCUSDT"); print("last BTC price via ws cache:", p)
    await c.close()
asyncio.run(main())
EOF
)"
echo "$WS_OUT" | tail -5
if echo "$WS_OUT" | grep -q WS_CONNECTED; then ok "websocket stream connected (live)"; else warn "websocket did not connect within 40 s (REST fallback will be used): $(echo "$WS_OUT" | tail -1)"; fi

section "backtest ${DAYS} days on LIVE history (default parameters)"
BT="$(DATA_SOURCE=binance BINANCE_TESTNET=false ENABLE_WEBSOCKET=false DATABASE_URL="sqlite:///$ROOT/smoke_live.db" LOG_LEVEL=WARNING timeout 900 python backtest.py --days "$DAYS" 2>&1 | grep -vE '^\S+ \| ')"
echo "$BT"
if echo "$BT" | grep -q "BACKTEST"; then ok "backtest completed"; info "backtest (${DAYS}d, live history):"$'\n'"$(echo "$BT" | sed 's/^/  /')"; else bad "backtest failed"; fi

section "backtest variants (for tuning)"
for v in "--min-conviction 60" "--require-htf" "--require-htf --min-conviction 60" "--sl-atr 1.5"; do
  R="$(DATA_SOURCE=binance BINANCE_TESTNET=false ENABLE_WEBSOCKET=false DATABASE_URL="sqlite:///$ROOT/smoke_live.db" LOG_LEVEL=WARNING timeout 900 python backtest.py --days "$DAYS" $v 2>&1 | grep -E 'Signals  |Win rate|Total PnL|Profit factor|Expectancy' | tr -s ' ' | tr '\n' ';')"
  echo "  [$v] $R"; info "variant [$v]: $R"
done

cd "$ROOT"
echo
echo "===== REPORT ====="
echo "host: $(uname -srm) | $(python --version 2>&1) | $(date -u '+%Y-%m-%d %H:%M:%S UTC')"
echo "commit: $(git rev-parse --short HEAD 2>/dev/null || echo n/a)  branch: $(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo n/a)"
echo "public ip / region hint: $(curl -s -m 5 https://ipinfo.io/json 2>/dev/null | tr -d '\n' | head -c 200)"
printf '%s\n' "${LINES[@]}"
echo "summary: PASS=$PASS WARN=$WARN FAIL=$FAIL"
echo "===== END REPORT ====="
[[ $FAIL -eq 0 ]]
