# Crypto Trading Signal Bot 24/7

Automated crypto **futures** signal system: real-time Binance data → technical
analysis → signals with entry / stop-loss / 3 take-profits → Telegram channel →
PostgreSQL history → live performance dashboard. Runs unattended 24/7 in Docker.

| Component | Tech | Port |
|-----------|------|------|
| Signal bot + REST API | Python 3.11 · FastAPI · ccxt (REST + WebSocket) | 8000 |
| Dashboard | Streamlit · Plotly | 8501 |
| Database | PostgreSQL 15 | 5432 (localhost only) |
| Notifications | Telegram Bot API (python-telegram-bot) | – |

> ⚠️ **Signals are informational only.** Start on the Binance Futures **testnet**,
> watch the performance statistics for 1-2 weeks and only then consider going live.

---

## Features

- ✅ Binance USD-M Futures market data – testnet or live – with **WebSocket streaming** and automatic REST fallback, rate-limit handling and exponential back-off
- ✅ Indicators implemented in pure pandas/numpy (no TA-Lib build headaches): RSI 14, MACD 12/26/9, Bollinger 20/2σ, ATR 14, EMA 9/21/50, ADX, volume vs 20-period average
- ✅ Strategy: **≥ 2 of 3** conditions (RSI extreme · MACD crossover · Bollinger breakout) on the closed 15m candle, 1h/4h EMA-trend confirmation feeds the **conviction score**
- ✅ ATR-based levels – SL 2 ATR, TP1/TP2/TP3 = 2/4/6 ATR → **R:R 1:3**
- ✅ Full **signal lifecycle tracking** every 60 s on 1-minute candles: TP1/TP2/TP3 hits, break-even stop after TP1, trailing stop after TP2, expiry (time stop), realised PnL in % and R
- ✅ Risk rules: max active signals, one signal per symbol, cooldown, expiry
- ✅ Telegram: new signal, TP hits, closed result, daily summary, start-up notice
- ✅ PostgreSQL history (`signals`, `signal_events`, `performance`, `bot_status`) via SQLAlchemy with connection pooling and auto-migration
- ✅ Performance: win rate, profit factor, expectancy, total PnL, max drawdown, TP hit rates, streaks, per-symbol / per-side / per-conviction breakdowns, equity curve
- ✅ REST API (Swagger at `/docs`) + health checks; Streamlit dashboard with live status, active signals, history, charts, market snapshot and per-signal drill-down
- ✅ **Backtester** that replays the exact production logic over historical candles
- ✅ Offline **synthetic data source** for demos / CI, 49 automated tests

---

## Project structure

```
crypto-signal-bot/
├── backend/
│   ├── main.py                 # FastAPI app + CLI (run bot, --once, --check, --api-only)
│   ├── bot.py                  # 24/7 orchestrator: screening / monitor / heartbeat / summary loops
│   ├── config.py               # Settings from environment (.env)
│   ├── data_collector.py       # Binance (ccxt REST + WebSocket) and synthetic data sources
│   ├── indicators.py           # RSI, MACD, Bollinger, ATR, EMA, ADX, volume
│   ├── signal_engine.py        # Signal rules, conviction score, entry/SL/TP levels
│   ├── signal_monitor.py       # TP/SL/expiry state machine + live monitor
│   ├── performance_tracker.py  # Win rate, profit factor, expectancy, drawdown …
│   ├── telegram_bot.py         # Telegram notifications & message formatting
│   ├── database.py             # SQLAlchemy models, engine, sessions, migrations
│   ├── backtest.py             # Historical backtester
│   ├── utils.py                # Logging, timeframe/time helpers, retry/backoff
│   ├── tests/                  # pytest suite (49 tests)
│   ├── Dockerfile
│   └── requirements.txt
├── frontend/
│   ├── dashboard.py            # Streamlit dashboard
│   ├── Dockerfile
│   └── requirements.txt
├── docs/
│   └── DEPLOYMENT.md           # Oracle Cloud (free tier) step-by-step guide
├── docker-compose.yml
├── requirements.txt            # backend + frontend + dev tools
├── .env.example
└── README.md
```

---

## Quick start (Docker – recommended)

```bash
git clone <this repo> crypto-signal-bot && cd crypto-signal-bot
cp .env.example .env
nano .env            # TELEGRAM_BOT_TOKEN, TELEGRAM_CHANNEL_ID, (optional) Binance keys
docker compose up -d --build
docker compose logs -f backend
```

- Dashboard → <http://localhost:8501>
- API / Swagger → <http://localhost:8000/docs>
- Health → <http://localhost:8000/health>

The database schema is created automatically on first start.

### Configuration essentials (`.env`)

| Variable | Default | Meaning |
|----------|---------|---------|
| `BINANCE_TESTNET` | `true` | `true` = testnet.binancefuture.com, `false` = live market data |
| `BINANCE_API_KEY` / `BINANCE_SECRET` | empty | Optional – public kline data needs no keys |
| `DATA_SOURCE` | `binance` | `synthetic` = offline demo data (no internet) |
| `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHANNEL_ID` | empty | Leave empty to run without Telegram (messages are logged) |
| `TRADING_PAIRS` | `BTCUSDT,ETHUSDT,SOLUSDT,XRPUSDT,DOGEUSDT` | Any USD-M perpetuals |
| `TIMEFRAME` | `15m` | Main timeframe; cycles align to candle close |
| `MIN_CONDITIONS` | `2` | Conditions required out of 3 |
| `MIN_CONVICTION` | `40` | Discard weaker setups (0-100) |
| `REQUIRE_HTF_CONFIRMATION` | `false` | Only trade with the 1h EMA trend |
| `SL_ATR_MULT`, `TP1/2/3_ATR_MULT` | `2 / 2 / 4 / 6` | Level sizing in ATR multiples |
| `MAX_ACTIVE_SIGNALS` | `10` | Portfolio-wide cap |
| `SIGNAL_EXPIRY_HOURS` | `48` | Time stop |
| `ADMIN_TOKEN` | empty | Protects `POST /api/admin/*` |

The full list with explanations is in [`.env.example`](.env.example).

### Telegram setup

1. Talk to [@BotFather](https://t.me/BotFather) → `/newbot` → copy the **token**.
2. Create a channel and add the bot as **administrator** (needs "Post messages").
3. Channel id: public channel → `@channel_name`; private channel → `-100xxxxxxxxxx`
   (forward a post from the channel to [@userinfobot](https://t.me/userinfobot) or open the
   channel in Telegram Web – the number in the URL prefixed with `-100`).
4. Put both values in `.env`, restart, then verify:
   `docker compose exec backend python main.py --check` (sends a test message).

---

## Running without Docker (development)

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env            # set DATABASE_URL to your PostgreSQL (or sqlite:///signals.db for a quick try)

cd backend
python main.py --check          # DB / exchange / Telegram self-test
python main.py --once           # one screening cycle, prints JSON summary
python main.py                  # 24/7 bot + API on :8000
python -m pytest                # 49 tests (uses SQLite + synthetic data, no network)

cd ../frontend
streamlit run dashboard.py      # dashboard on :8501 (reads DATABASE_URL / API_URL)
```

No internet / no exchange access? Use `DATA_SOURCE=synthetic` – the whole stack runs on
deterministic simulated prices, which is also what the test-suite uses.

---

## Strategy

Evaluated once per **closed** 15-minute candle, per symbol:

| | LONG | SHORT |
|---|---|---|
| RSI(14) | `< 30` | `> 70` |
| MACD(12,26,9) | line crossed **above** signal within the last 3 candles | crossed **below** |
| Bollinger(20, 2σ) | close **below** lower band | close **above** upper band |

A signal needs **≥ 2 of 3** (`MIN_CONDITIONS`).
Conviction score = 55 (2 conditions) or 75 (3) ± higher-timeframe trend agreement
(1h ±10, 4h ±5) + volume spike (+5) + RSI extreme (+5) + momentum turning (+3) +
confirming candle (+3) – strong opposing trend (−5). Signals below `MIN_CONVICTION` are dropped.

Levels (ATR 14): `SL = entry ∓ 2·ATR`, `TP1/2/3 = entry ± 2/4/6·ATR` → R:R at TP3 = **1:3**.
Entry zone shown in Telegram = entry ± 0.25 ATR.

### Position model used for PnL

Scale-out in thirds: ⅓ closed at each TP. After TP1 the stop moves to break-even,
after TP2 it trails to TP1. A candle touching both stop and target counts as **stop first**
(conservative). Open signals are force-closed at market after `SIGNAL_EXPIRY_HOURS`.
PnL is reported as unleveraged % of entry and in R-multiples.

### Metrics

```
win_rate       = wins / (wins + losses) × 100
profit_factor  = gross_profit / gross_loss
expectancy     = win_rate·avg_win − (1 − win_rate)·avg_loss      (% per trade)
total_pnl      = Σ profit_loss_pct
```
plus max drawdown, average R, TP1/2/3 hit rates, streaks and average duration.

---

## Backtesting & tuning

```bash
cd backend
python backtest.py --days 60                          # all pairs, current .env parameters
python backtest.py --days 90 --symbols BTCUSDT,ETHUSDT --min-conviction 60 --require-htf
python backtest.py --days 60 --write-db               # store as source=backtest (excluded from live stats)
```

The backtester uses the identical `SignalEngine` and position state machine as the
live bot, so what you measure is what you will get (minus slippage/fees).
Tune thresholds in `.env` (`RSI_*`, `MIN_CONVICTION`, `REQUIRE_HTF_CONFIRMATION`,
`SL_ATR_MULT`, …) and re-run. The mean-reversion rule-set in the brief is a starting
point – validate it on real testnet/live history before trusting it.

---

## REST API

| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | 200 when DB reachable and bot loop is fresh (503 otherwise) |
| GET | `/api/status` | Live bot status + persisted heartbeat |
| GET | `/api/config` | Effective (non-secret) configuration |
| GET | `/api/signals` | History; filters `status`, `symbol`, `side`, `source`, `days`, `limit`, `offset` |
| GET | `/api/signals/active` | Active signals incl. unrealised PnL |
| GET | `/api/signals/{id}` | One signal with its event trail |
| GET | `/api/performance` | Aggregate statistics |
| GET | `/api/performance/breakdown?days=30` | By symbol / side / conviction |
| GET | `/api/performance/equity` | Cumulative PnL curve |
| GET | `/api/performance/daily?date=YYYY-MM-DD` | Daily digest |
| GET | `/api/market` | Latest indicator snapshot & evaluation per symbol |
| POST | `/api/admin/run-cycle` | Trigger a screening cycle now (`X-Admin-Token`) |
| POST | `/api/admin/run-monitor` | Trigger a TP/SL check now |
| POST | `/api/admin/test-telegram` | Send a Telegram test message |
| POST | `/api/admin/recompute-performance` | Recalculate statistics |

Interactive docs: `/docs`.

---

## Database schema

`signals` – one row per signal: symbol, side, timeframe, entry (+ zone), SL (initial and
current), TP1-3, risk/reward, timestamps, status (`ACTIVE`/`TP_HIT`/`SL_HIT`/`EXPIRED`),
outcome (`WIN`/`LOSS`/`BREAKEVEN`), `profit_loss_pct`, `profit_loss_r`, conviction,
TP hit counters/timestamps, MFE/MAE, indicator snapshot (RSI, MACD, BB, ATR, volume ratio,
1h/4h trend), conditions, reasons, Telegram message id, source.

`signal_events` – audit trail (`CREATED`, `TP1_HIT`, `SL_MOVED`, `SL_HIT`, `EXPIRED`, …).

`performance` – single row with all aggregate metrics, refreshed after every cycle and
every closed signal.

`bot_status` – heartbeat, last/next cycle, counters, last error (used by the dashboard
and `/health`).

Tables are created automatically; new columns are added on upgrade.

---

## Operations

```bash
docker compose ps                         # container state + health
docker compose logs -f backend            # bot log (one line per symbol per cycle)
docker compose exec backend python main.py --check
docker compose restart backend
docker compose pull && docker compose up -d --build   # upgrade
docker compose exec postgres pg_dump -U crypto_user crypto_signals | gzip > backup_$(date +%F).sql.gz
```

Deployment on Oracle Cloud (Always-Free VM), firewall, backups, HTTPS and going live:
see **[docs/DEPLOYMENT.md](docs/DEPLOYMENT.md)**.

---

## Going live checklist

1. Run on testnet (`BINANCE_TESTNET=true`) for 1-2 weeks; review `/api/performance/breakdown`.
2. Backtest 60-90 days of **live** market history (`BINANCE_TESTNET=false python backtest.py`)
   – testnet order-books are thin and testnet prices can diverge from the real market.
3. Tune `MIN_CONVICTION`, `REQUIRE_HTF_CONFIRMATION`, ATR multipliers; re-test.
4. Switch `BINANCE_TESTNET=false` (market data only – the bot never places orders).
5. Set `ADMIN_TOKEN`, keep PostgreSQL bound to localhost, enable backups.

## License

MIT
