# Operator guide (for the GPT operator)

This document is written for an AI operator (GPT) that has shell access to a
machine with internet and Docker, and that executes tasks handed over from the
developer agent (Arena) via the project owner. The developer has **no** access
to Binance, Telegram or Docker from its sandbox; the operator has. The owner does
not want to do anything manually – he only relays messages.

## Roles

| Who | Does | Does not |
|-----|------|----------|
| **Developer (Arena agent)** | writes/fixes code, tests, decides parameters, interprets reports | run Docker, reach Binance/Telegram |
| **Operator (GPT)** | runs the scripts below on a real machine, pastes the reports back verbatim | edit code, change strategy parameters, use API keys with trading permissions |
| **Owner** | relays messages, owns accounts/credentials, approves going live | – |

## Ground rules for the operator

1. **Only run the commands given.** Do not modify files under `backend/` or
   `frontend/`. If something fails, report it – do not patch it.
2. **Always paste the full block between `===== REPORT =====` and
   `===== END REPORT =====` verbatim.** The developer parses those.
   If a command fails before printing a report, paste the last 40 lines of output.
3. **Never put secrets in chat.** Tokens/keys go directly into `.env` on the machine
   (or are passed as environment variables to `deploy.sh`). In reports, mask them.
4. Binance keys are **not required** – the bot only reads public market data.
   If keys are used anyway, they must be **read-only** (no trading / withdrawal).
5. Keep `BINANCE_TESTNET=true` until the owner explicitly approves going live.
6. `DATA_SOURCE` must be `binance` on the server (`synthetic` is demo data only).

## Machine requirements

- Ubuntu 22.04/24.04 (x86_64 or ARM64), 2 GB RAM (1 GB + swap works), 10 GB disk
- Outbound internet to `fapi.binance.com`, `testnet.binancefuture.com`,
  `fstream.binance.com`, `api.telegram.org`, Docker Hub, PyPI, GitHub
- **Region matters:** Binance returns HTTP 451 from the US and some other
  jurisdictions. Oracle Cloud Singapore / Tokyo / Frankfurt / Amsterdam work.
- Recommended: Oracle Cloud Always-Free `VM.Standard.A1.Flex` (2 OCPU / 12 GB);
  see `docs/DEPLOYMENT.md` for the click-path and firewall rules.

## Task catalogue

Each task is one command. Run them in order the first time.

### T0 – get the code

```bash
git clone -b arena/01a06815-cripsignalsep26 https://github.com/Acekiller88/cripsignalsep26.git crypto-signal-bot
cd crypto-signal-bot && chmod +x scripts/*.sh
git log --oneline -1
```
Report: the commit line.

### T1 – validate against the real exchange (no Docker needed)

```bash
BACKTEST_DAYS=60 ./scripts/smoke_local.sh
```
What it does: creates a venv, runs the 58 unit tests, checks Binance **testnet**
and **live** connectivity (read-only), runs one screening cycle, tests the
WebSocket stream, and runs a 60-day backtest plus four parameter variants on
live history. Takes 3-8 minutes.
Report: the REPORT block. If it contains `HTTP 451`, the server region is blocked
– the script automatically falls back to testnet history for the backtest (marked
"indicative only"); report it, the developer will ask the owner for another region.

Reference run (GitHub Actions runner, US region, 2026-09-03): testnet `ALL OK`,
live `HTTP 451`, WebSocket OK, 60-day testnet backtest 422 signals / WR 51.7% /
PF 1.14 – i.e. `summary: PASS=6 WARN=0 FAIL=1` is the expected result from a
blocked region, and `PASS=7 FAIL=0` from an allowed one.

### T2 – validate Telegram

```bash
TELEGRAM_BOT_TOKEN='<token>' TELEGRAM_CHANNEL_ID='<id>' ./scripts/telegram_test.sh
```
Report: the REPORT block (mask the token). If the channel id is unknown, run it
with only the token after posting any message in the channel – it lists the chat
ids it can see.

### T3 – deploy the 24/7 stack

```bash
TELEGRAM_BOT_TOKEN='<token>' TELEGRAM_CHANNEL_ID='<id>' BINANCE_TESTNET=true ./scripts/deploy.sh
```
Installs Docker if missing, writes `.env` (generates a strong DB password and
an `ADMIN_TOKEN`), opens ports 8000/8501 in iptables, builds the images, starts
`postgres` + `backend` + `dashboard`, waits for health, runs `verify.sh --quick`.
Any other `.env` key can be passed the same way (e.g. `MIN_CONVICTION=60`).
Report: the REPORT block + the three URLs printed at the end. Also confirm a
"bot online" message arrived in the Telegram channel.

### T4 – full verification (after T3, and after every change)

```bash
./scripts/verify.sh
```
Report: the REPORT block.

### T5 – daily status (every 24 h during the 1-2 week testnet observation)

```bash
./scripts/report_status.sh 7
```
Report: the REPORT block. The developer tracks win rate, profit factor,
expectancy, error counts and WebSocket stability from these.

### T6 – apply an update from the developer

```bash
cd crypto-signal-bot && git pull && docker compose up -d --build && sleep 60 && ./scripts/verify.sh --quick
```
Report: the REPORT block.

### T7 – change a parameter (only when instructed, e.g. `MIN_CONVICTION=60`)

```bash
sed -i 's/^MIN_CONVICTION=.*/MIN_CONVICTION=60/' .env && docker compose up -d backend && sleep 60 && ./scripts/verify.sh --quick
```

### T8 – backtest with specific parameters (when asked)

```bash
docker exec -e BINANCE_TESTNET=false crypto_backend python backtest.py --days 90 --min-conviction 60 --require-htf
```
Report: everything from the `BACKTEST` header to the closing `====` line.

### T9 – go live (only after explicit owner approval)

```bash
sed -i 's/^BINANCE_TESTNET=.*/BINANCE_TESTNET=false/' .env && docker compose up -d backend && sleep 60 && ./scripts/verify.sh --quick
```
The start-up Telegram message must now say **LIVE**.

### Useful commands

```bash
docker compose ps                          # container states
docker compose logs --since 30m backend    # recent bot log
docker compose restart backend             # restart the bot
docker compose down                        # stop everything (data is kept in the volume)
docker compose exec postgres pg_dump -U crypto_user crypto_signals | gzip > backup_$(date +%F).sql.gz
```

## What "healthy" looks like

- `GET /health` → `{"status":"ok","database":"ok","bot":"running"}`
- Backend log every 15 minutes: `──── Screening cycle #N started ────`, one
  `close=… rsi=…` line per symbol, `Cycle finished in X s`
- `websocket connected` in `verify.sh` (REST fallback is acceptable but report it)
- Telegram: start-up message, then signals as they occur (there may be hours or
  days without a signal – that is normal for a 2-of-3 mean-reversion setup)
- Dashboard header: `Bot: ONLINE`, heartbeat < 60 s

## Troubleshooting quick table

| Report shows | Meaning / action |
|--------------|------------------|
| `HTTP 451` / `restricted location` | Region blocked by Binance → new VM region |
| `NetworkError` on load_markets, everything else OK | Outbound firewall/DNS → check `curl -I https://fapi.binance.com/fapi/v1/ping` |
| Telegram `Chat not found` | id needs `-100` prefix, or bot not in channel |
| Telegram `Forbidden: bot is not a member` | Add bot as channel admin |
| `unsupported symbols: …` | Pair not listed on that endpoint (testnet lists fewer pairs); bot skips it – report it |
| `bot: stale` in /health | Loop stuck → `docker compose restart backend`, report logs |
| container `unhealthy` | `docker compose logs --tail 100 <name>` and report |
