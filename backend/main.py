"""
Application entry point.

    python main.py                 # run the 24/7 bot + REST API (default)
    python main.py --once          # run a single screening cycle and exit
    python main.py --monitor-once  # run a single TP/SL monitoring pass and exit
    python main.py --check         # connectivity self-test (DB, exchange, Telegram)
    python main.py --api-only      # serve the API without the trading loops

The REST API (FastAPI) exposes signals, performance statistics, bot status and
health checks; the Streamlit dashboard and any external tooling consume it.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from typing import Optional

from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from sqlalchemy import desc, func

from bot import SignalBot
from config import Settings, settings
from database import Database, Signal, SignalEvent, SignalStatus, set_database
from performance_tracker import PerformanceTracker
from utils import setup_logging, utcnow

logger = logging.getLogger("main")


async def _wait_for_database(database: Database, attempts: int = 30, delay: float = 3.0) -> None:
    """Create the schema, retrying while PostgreSQL is still starting up."""
    for attempt in range(1, attempts + 1):
        try:
            database.create_tables()
            return
        except Exception as exc:  # pragma: no cover - depends on infra timing
            if attempt >= attempts:
                raise
            logger.warning("Database not ready (attempt %d/%d): %s — retrying in %.0fs",
                           attempt, attempts, str(exc)[:160], delay)
            await asyncio.sleep(delay)


# ---------------------------------------------------------------------------
# Application factory
# ---------------------------------------------------------------------------
def create_app(cfg: Settings = settings, run_bot: bool = True, db: Optional[Database] = None,
               collector=None, notifier=None) -> FastAPI:
    setup_logging(cfg.log_level)
    state: dict = {"bot": None, "db": db}

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        database = state["db"] or Database(cfg.database_url)
        await _wait_for_database(database)
        set_database(database)
        state["db"] = database
        app.state.db = database
        app.state.settings = cfg
        app.state.performance = PerformanceTracker(database)
        bot = None
        if run_bot:
            bot = SignalBot(cfg, database, collector=collector, notifier=notifier)
            state["bot"] = bot
            app.state.bot = bot
            await bot.start()
        else:
            app.state.bot = None
        try:
            yield
        finally:
            if bot is not None:
                await bot.stop()
            database.dispose()

    app = FastAPI(
        title="Crypto Signal Bot API",
        version=cfg.app_version,
        description="24/7 crypto futures signal generation, tracking and performance statistics.",
        lifespan=lifespan,
    )
    app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

    # ------------------------------------------------------------------
    def db_dep() -> Database:
        return app.state.db

    def perf_dep() -> PerformanceTracker:
        return app.state.performance

    def require_admin(x_admin_token: Optional[str] = Header(default=None), token: Optional[str] = Query(default=None)):
        if cfg.admin_token and (x_admin_token or token) != cfg.admin_token:
            raise HTTPException(status_code=401, detail="invalid admin token")
        return True

    # ------------------------------------------------------------------
    # Health / status
    # ------------------------------------------------------------------
    @app.get("/health", tags=["system"])
    def health(database: Database = Depends(db_dep)):
        db_ok = database.ping()
        bot: Optional[SignalBot] = app.state.bot
        healthy = db_ok
        detail = {"database": "ok" if db_ok else "error", "bot": "disabled"}
        if bot is not None:
            st = bot.status()
            detail["bot"] = "running" if st["running"] else "stopped"
            stale_after = max(3 * cfg.timeframe_seconds, 1800)
            last = bot.last_cycle_finished or bot.started_at
            if last and (utcnow() - last).total_seconds() > stale_after:
                detail["bot"] = "stale"
                healthy = False
            if not st["running"]:
                healthy = False
        status_code = 200 if healthy else 503
        return JSONResponse({"status": "ok" if healthy else "degraded", **detail, "time": utcnow().isoformat()},
                            status_code=status_code)

    @app.get("/api/status", tags=["system"])
    def api_status(database: Database = Depends(db_dep)):
        bot: Optional[SignalBot] = app.state.bot
        with database.session() as session:
            row = database.get_or_create_status(session)
            persisted = row.to_dict()
            active = session.query(func.count(Signal.id)).filter(Signal.status == SignalStatus.ACTIVE).scalar() or 0
            total = session.query(func.count(Signal.id)).scalar() or 0
        live = bot.status() if bot is not None else None
        return {"live": live, "persisted": persisted, "active_signals": int(active), "total_signals": int(total),
                "server_time": utcnow().isoformat()}

    @app.get("/api/config", tags=["system"])
    def api_config():
        return cfg.public_dict()

    # ------------------------------------------------------------------
    # Signals
    # ------------------------------------------------------------------
    @app.get("/api/signals", tags=["signals"])
    def list_signals(
        status: Optional[str] = Query(default=None, description="ACTIVE, TP_HIT, SL_HIT, EXPIRED or CLOSED"),
        symbol: Optional[str] = None,
        side: Optional[str] = None,
        source: Optional[str] = Query(default=None, description="binance, synthetic, backtest or 'live' (= not backtest)"),
        days: Optional[int] = Query(default=None, ge=1, le=3650),
        limit: int = Query(default=100, ge=1, le=1000),
        offset: int = Query(default=0, ge=0),
        database: Database = Depends(db_dep),
    ):
        with database.session() as session:
            q = session.query(Signal)
            if status:
                status = status.upper()
                if status == "CLOSED":
                    q = q.filter(Signal.status.in_(SignalStatus.CLOSED_STATUSES))
                else:
                    q = q.filter(Signal.status == status)
            if symbol:
                q = q.filter(Signal.symbol == symbol.upper())
            if side:
                q = q.filter(Signal.side == side.upper())
            if source:
                if source.lower() == "live":
                    q = q.filter((Signal.source.is_(None)) | (Signal.source != "backtest"))
                else:
                    q = q.filter(Signal.source == source.lower())
            if days:
                q = q.filter(Signal.timestamp >= utcnow() - timedelta(days=days))
            total = q.count()
            rows = q.order_by(desc(Signal.timestamp), desc(Signal.id)).offset(offset).limit(limit).all()
            return {"total": total, "limit": limit, "offset": offset, "items": [r.to_dict() for r in rows]}

    @app.get("/api/signals/active", tags=["signals"])
    def active_signals(database: Database = Depends(db_dep)):
        bot: Optional[SignalBot] = app.state.bot
        with database.session() as session:
            rows = session.query(Signal).filter(Signal.status == SignalStatus.ACTIVE).order_by(Signal.timestamp).all()
            items = [r.to_dict() for r in rows]
        # attach unrealised PnL using the latest known price
        if bot is not None:
            for item in items:
                snap = bot.last_market.get(item["symbol"])
                price = snap.get("close") if snap else None
                if price:
                    direction = 1 if item["side"] == "LONG" else -1
                    item["last_price"] = price
                    item["unrealised_pct"] = round(direction * (price - item["entry_price"]) / item["entry_price"] * 100, 4)
        return {"count": len(items), "items": items}

    @app.get("/api/signals/{signal_id}", tags=["signals"])
    def get_signal(signal_id: int, database: Database = Depends(db_dep)):
        with database.session() as session:
            sig = session.get(Signal, signal_id)
            if sig is None:
                raise HTTPException(status_code=404, detail="signal not found")
            events = session.query(SignalEvent).filter(SignalEvent.signal_id == signal_id).order_by(SignalEvent.created_at).all()
            return {**sig.to_dict(), "events": [e.to_dict() for e in events]}

    # ------------------------------------------------------------------
    # Performance
    # ------------------------------------------------------------------
    @app.get("/api/performance", tags=["performance"])
    def performance(perf: PerformanceTracker = Depends(perf_dep)):
        latest = perf.latest()
        if latest is None:
            latest = perf.update().to_dict()
        return latest

    @app.get("/api/performance/breakdown", tags=["performance"])
    def performance_breakdown(days: Optional[int] = Query(default=None, ge=1, le=3650),
                              perf: PerformanceTracker = Depends(perf_dep)):
        return perf.breakdown(days=days)

    @app.get("/api/performance/equity", tags=["performance"])
    def performance_equity(days: Optional[int] = Query(default=None, ge=1, le=3650),
                           perf: PerformanceTracker = Depends(perf_dep)):
        return {"points": perf.equity_curve(days=days)}

    @app.get("/api/performance/daily", tags=["performance"])
    def performance_daily(date: Optional[str] = None, perf: PerformanceTracker = Depends(perf_dep)):
        day = datetime.fromisoformat(date) if date else None
        return perf.daily_summary(day)

    # ------------------------------------------------------------------
    # Market / diagnostics
    # ------------------------------------------------------------------
    @app.get("/api/market", tags=["market"])
    def market():
        bot: Optional[SignalBot] = app.state.bot
        if bot is None:
            return {"items": {}}
        return {"items": bot.last_market, "evaluations": bot.last_evaluations}

    # ------------------------------------------------------------------
    # Admin
    # ------------------------------------------------------------------
    @app.post("/api/admin/run-cycle", tags=["admin"])
    async def admin_run_cycle(force: bool = False, _: bool = Depends(require_admin)):
        bot: Optional[SignalBot] = app.state.bot
        if bot is None:
            raise HTTPException(status_code=400, detail="bot not running in this process")
        return await bot.run_cycle(force=force)

    @app.post("/api/admin/run-monitor", tags=["admin"])
    async def admin_run_monitor(_: bool = Depends(require_admin)):
        bot: Optional[SignalBot] = app.state.bot
        if bot is None:
            raise HTTPException(status_code=400, detail="bot not running in this process")
        return await bot.run_monitor()

    @app.post("/api/admin/test-telegram", tags=["admin"])
    async def admin_test_telegram(_: bool = Depends(require_admin)):
        bot: Optional[SignalBot] = app.state.bot
        if bot is None:
            raise HTTPException(status_code=400, detail="bot not running in this process")
        ok, info = await bot.notifier.test_connection()
        message_id = None
        if ok:
            message_id = await bot.notifier.send_text("✅ Test message from Crypto Signal Bot", disable_notification=True)
        return {"ok": ok and message_id is not None, "info": info, "message_id": message_id}

    @app.post("/api/admin/recompute-performance", tags=["admin"])
    def admin_recompute(_: bool = Depends(require_admin), perf: PerformanceTracker = Depends(perf_dep)):
        return perf.update().to_dict()

    # ------------------------------------------------------------------
    @app.get("/", response_class=HTMLResponse, include_in_schema=False)
    def index():
        return f"""<!doctype html><html><head><meta charset='utf-8'><title>Crypto Signal Bot API</title>
<style>body{{font-family:system-ui,sans-serif;max-width:720px;margin:40px auto;padding:0 16px;color:#222}}
code{{background:#f3f3f3;padding:2px 6px;border-radius:4px}} li{{margin:6px 0}}</style></head>
<body><h1>🤖 Crypto Signal Bot API v{cfg.app_version}</h1>
<p>Data source: <b>{'synthetic' if cfg.is_synthetic else ('Binance Futures testnet' if cfg.binance_testnet else 'Binance Futures LIVE')}</b>
· Pairs: {', '.join(cfg.trading_pairs)} · Timeframe: {cfg.timeframe}</p>
<ul>
<li><a href='/docs'>Interactive API docs (Swagger)</a></li>
<li><a href='/health'>/health</a> · <a href='/api/status'>/api/status</a> · <a href='/api/config'>/api/config</a></li>
<li><a href='/api/signals/active'>/api/signals/active</a> · <a href='/api/signals?limit=50'>/api/signals</a></li>
<li><a href='/api/performance'>/api/performance</a> · <a href='/api/performance/breakdown'>/api/performance/breakdown</a>
· <a href='/api/performance/equity'>/api/performance/equity</a></li>
<li><a href='/api/market'>/api/market</a></li>
</ul><p>The Streamlit dashboard runs separately (default port 8501).</p></body></html>"""

    return app


# ---------------------------------------------------------------------------
# CLI helpers
# ---------------------------------------------------------------------------
async def _run_once(cfg: Settings, monitor: bool = False) -> int:
    database = Database(cfg.database_url)
    database.create_tables()
    set_database(database)
    bot = SignalBot(cfg, database)
    await bot.collector.start(list(cfg.trading_pairs))
    try:
        if monitor:
            result = await bot.run_monitor()
        else:
            result = await bot.run_cycle()
        print(json.dumps(result, indent=2, default=str))
    finally:
        await bot.collector.close()
        await bot.notifier.close()
        database.dispose()
    return 0


async def _check(cfg: Settings) -> int:
    from data_collector import create_data_collector
    from telegram_bot import TelegramNotifier

    ok_all = True
    print(f"Crypto Signal Bot v{cfg.app_version} — self test")
    print(f"  data source     : {cfg.data_source} (testnet={cfg.binance_testnet})")
    print(f"  pairs / tf      : {', '.join(cfg.trading_pairs)} / {cfg.timeframe}")

    # Database
    try:
        database = Database(cfg.database_url)
        database.create_tables()
        ok = database.ping()
        with database.session() as session:
            n = session.query(func.count(Signal.id)).scalar()
        print(f"  database        : {'OK' if ok else 'FAIL'} ({n} signals stored)")
        database.dispose()
        ok_all &= ok
    except Exception as exc:
        print(f"  database        : FAIL — {exc}")
        ok_all = False

    # Exchange
    collector = create_data_collector(cfg)
    try:
        ok, info = await collector.check_connection()
        print(f"  exchange        : {'OK' if ok else 'FAIL'} — {info}")
        ok_all &= ok
        if ok:
            df = await collector.get_klines(cfg.trading_pairs[0], cfg.timeframe, limit=50)
            print(f"  klines          : {len(df)} candles for {cfg.trading_pairs[0]} "
                  f"(last close {df['close'].iloc[-1] if len(df) else 'n/a'} @ {df['timestamp'].iloc[-1] if len(df) else 'n/a'})")
    except Exception as exc:
        print(f"  exchange        : FAIL — {exc}")
        ok_all = False
    finally:
        await collector.close()

    # Telegram
    stored = {}
    try:
        database = Database(cfg.database_url)
        with database.session() as session:
            row = database.get_or_create_status(session)
            stored = {"channel_id": row.telegram_channel_id, "admin_chat_id": row.telegram_admin_chat_id}
        database.dispose()
    except Exception:
        pass
    notifier = TelegramNotifier(cfg, **stored)
    if notifier.enabled:
        ok, info = await notifier.test_connection()
        print(f"  telegram        : {'OK' if ok else 'FAIL'} — {info}")
        if ok and notifier.channel_id:
            mid = await notifier.send_text("✅ Crypto Signal Bot self-test: Telegram connection works", disable_notification=True)
            print(f"  telegram send   : {'OK' if mid else 'FAIL'} (message id {mid}, chat {notifier.channel_id})")
            ok = ok and mid is not None
        elif ok:
            print(f"  telegram send   : SKIPPED — {notifier.discovery_hint}")
        ok_all &= ok
    else:
        print("  telegram        : not configured (skipped)")
    await notifier.close()
    print("RESULT:", "ALL OK" if ok_all else "PROBLEMS FOUND")
    return 0 if ok_all else 1


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Crypto Signal Bot")
    parser.add_argument("--once", action="store_true", help="run one screening cycle and exit")
    parser.add_argument("--monitor-once", action="store_true", help="run one monitoring pass and exit")
    parser.add_argument("--check", action="store_true", help="connectivity self-test and exit")
    parser.add_argument("--api-only", action="store_true", help="serve the API without the bot loops")
    parser.add_argument("--host", default=settings.api_host)
    parser.add_argument("--port", type=int, default=settings.api_port)
    args = parser.parse_args(argv)

    setup_logging(settings.log_level)
    if args.check:
        return asyncio.run(_check(settings))
    if args.once or args.monitor_once:
        return asyncio.run(_run_once(settings, monitor=args.monitor_once))

    import uvicorn

    app = create_app(settings, run_bot=not args.api_only)
    uvicorn.run(app, host=args.host, port=args.port, log_level=settings.log_level.lower(), access_log=False)
    return 0


# `uvicorn main:app` support
app = create_app(settings, run_bot=os.getenv("BOT_ENABLED", "true").lower() not in ("0", "false", "no"))

if __name__ == "__main__":
    sys.exit(main())
