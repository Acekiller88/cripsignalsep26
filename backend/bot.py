"""
Orchestrator: the 24/7 loops.

    screening loop  – aligned to candle close of the main timeframe:
                      fetch data → indicators → signal engine → risk filters →
                      persist → Telegram → performance update
    monitor loop    – every `monitor_interval` seconds: check active signals
                      against fresh 1-minute candles (TP/SL/expiry)
    summary loop    – daily Telegram digest
    heartbeat       – bot_status row for the dashboard / health checks
"""
from __future__ import annotations

import asyncio
import logging
import time
import traceback
from datetime import datetime, timedelta
from typing import Dict, List, Optional

import pandas as pd
from sqlalchemy import func

from config import Settings
from data_collector import create_data_collector
from database import Database, Signal, SignalStatus
from indicators import calculate_all_indicators, latest_snapshot, min_candles_required
from performance_tracker import PerformanceTracker
from signal_engine import Evaluation, SignalEngine
from signal_monitor import SignalMonitor
from telegram_bot import TelegramNotifier
from utils import current_candle_open, seconds_until_next_candle, utcnow

logger = logging.getLogger("bot")


class SignalBot:
    def __init__(self, settings: Settings, db: Database, collector=None, notifier=None):
        self.s = settings
        self.db = db
        self.collector = collector or create_data_collector(settings)
        self.notifier = notifier or TelegramNotifier(settings, persist_callback=self._persist_telegram_destinations,
                                                     **self._stored_telegram_destinations())
        self.engine = SignalEngine(settings)
        self.monitor = SignalMonitor(settings, db, self.collector, self.notifier)
        self.performance = PerformanceTracker(db)

        self.started_at: Optional[datetime] = None
        self.cycles_completed = 0
        self.signals_generated = 0
        self.last_cycle_started: Optional[datetime] = None
        self.last_cycle_finished: Optional[datetime] = None
        self.last_cycle_duration: Optional[float] = None
        self.next_cycle_at: Optional[datetime] = None
        self.last_monitor_at: Optional[datetime] = None
        self.last_error: Optional[str] = None
        self.last_error_at: Optional[datetime] = None
        self.last_evaluations: Dict[str, dict] = {}
        self.last_market: Dict[str, dict] = {}
        self._processed_candles: Dict[str, datetime] = {}
        self._tasks: List[asyncio.Task] = []
        self._stop = asyncio.Event()
        self._cycle_lock = asyncio.Lock()
        self._monitor_lock = asyncio.Lock()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    async def start(self) -> None:
        self.started_at = utcnow()
        self.db.create_tables()
        await self.collector.start(list(self.s.trading_pairs))
        ok, info = await self.collector.check_connection()
        logger.info("Data source %s: %s", self.collector.name, info)
        if getattr(self.notifier, "enabled", False):
            tg_ok, tg_info = await self.notifier.test_connection()
            logger.info("Telegram: %s", tg_info if tg_ok else f"unavailable ({tg_info})")
        self._write_status(started=True)
        if self.s.notify_startup:
            try:
                await self.notifier.send_startup(info if ok else f"data source problem: {info}")
            except Exception as exc:  # pragma: no cover
                logger.warning("Startup notification failed: %s", exc)
        self._tasks = [
            asyncio.create_task(self._screening_loop(), name="screening"),
            asyncio.create_task(self._monitor_loop(), name="monitor"),
            asyncio.create_task(self._heartbeat_loop(), name="heartbeat"),
        ]
        if getattr(self.notifier, "enabled", False):
            self._tasks.append(asyncio.create_task(self._telegram_loop(), name="telegram"))
        if self.s.daily_summary_hour_utc >= 0:
            self._tasks.append(asyncio.create_task(self._summary_loop(), name="summary"))
        logger.info("🚀 Crypto Signal Bot v%s started — %d pairs, %s timeframe, source=%s",
                    self.s.app_version, len(self.s.trading_pairs), self.s.timeframe, self.collector.name)

    async def stop(self) -> None:
        self._stop.set()
        for t in self._tasks:
            t.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()
        await self.collector.close()
        await self.notifier.close()
        logger.info("Bot stopped")

    async def run_forever(self) -> None:
        await self.start()
        try:
            await self._stop.wait()
        finally:
            await self.stop()

    # ------------------------------------------------------------------
    # Loops
    # ------------------------------------------------------------------
    async def _screening_loop(self) -> None:
        if self.s.run_cycle_on_startup:
            await self._safe_cycle()
        while not self._stop.is_set():
            wait = seconds_until_next_candle(self.s.timeframe, delay=self.s.candle_close_delay_seconds)
            if self.s.screening_interval != self.s.timeframe_seconds:
                wait = float(self.s.screening_interval)
            self.next_cycle_at = utcnow() + timedelta(seconds=wait)
            logger.info("Next screening cycle in %.0fs (at %s UTC)", wait, self.next_cycle_at.strftime("%H:%M:%S"))
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=wait)
                break
            except asyncio.TimeoutError:
                pass
            await self._safe_cycle()

    async def _safe_cycle(self) -> None:
        try:
            await self.run_cycle()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self._record_error(f"cycle: {exc}")
            logger.error("Screening cycle failed: %s\n%s", exc, traceback.format_exc())

    async def _monitor_loop(self) -> None:
        # small offset so the monitor doesn't collide with the screening cycle
        await asyncio.sleep(15)
        while not self._stop.is_set():
            try:
                await self.run_monitor()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self._record_error(f"monitor: {exc}")
                logger.error("Monitor failed: %s\n%s", exc, traceback.format_exc())
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=self.s.monitor_interval)
                break
            except asyncio.TimeoutError:
                pass

    async def _heartbeat_loop(self) -> None:
        while not self._stop.is_set():
            try:
                self._write_status()
            except Exception as exc:  # pragma: no cover
                logger.warning("Heartbeat failed: %s", exc)
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=30)
                break
            except asyncio.TimeoutError:
                pass

    async def _telegram_loop(self) -> None:
        """Discover channel/admin chat when not configured and alert the owner on persistent errors."""
        announced = False
        error_alert_at: Optional[datetime] = None
        while not self._stop.is_set():
            try:
                had_channel = bool(self.notifier.channel_id)
                await self.notifier.discover_destinations()
                if self.notifier.channel_id and not had_channel and self.s.notify_startup and not announced:
                    announced = True
                    ok, info = await self.collector.check_connection()
                    await self.notifier.send_startup(info if ok else f"data source problem: {info}")
                # operational alert (at most once per 6 h) when the last cycle failed
                if self.last_error and self.last_error_at and (
                        error_alert_at is None or (utcnow() - error_alert_at).total_seconds() > 6 * 3600):
                    error_alert_at = utcnow()
                    await self.notifier.send_admin(f"⚠️ <b>Bot error</b> at {self.last_error_at:%Y-%m-%d %H:%M} UTC:\n"
                                                   f"<code>{self.last_error[:400]}</code>")
            except Exception as exc:  # pragma: no cover
                logger.warning("Telegram maintenance failed: %s", str(exc)[:160])
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=60)
                break
            except asyncio.TimeoutError:
                pass

    async def _summary_loop(self) -> None:
        while not self._stop.is_set():
            now = utcnow()
            target = now.replace(hour=self.s.daily_summary_hour_utc, minute=5, second=0, microsecond=0)
            if target <= now:
                target += timedelta(days=1)
            wait = (target - now).total_seconds()
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=wait)
                break
            except asyncio.TimeoutError:
                pass
            try:
                await self.send_daily_summary()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning("Daily summary failed: %s", exc)

    # ------------------------------------------------------------------
    # Screening cycle
    # ------------------------------------------------------------------
    async def run_cycle(self, force: bool = False) -> Dict[str, object]:
        """One full screening pass over all pairs. Returns a summary dict."""
        async with self._cycle_lock:
            t0 = time.time()
            self.last_cycle_started = utcnow()
            logger.info("──── Screening cycle #%d started (%s) ────", self.cycles_completed + 1, self.s.timeframe)
            summary = {"started": self.last_cycle_started.isoformat(), "symbols": {}, "signals": []}
            new_signals: List[int] = []
            unsupported = set(getattr(self.collector, "unsupported_symbols", []) or [])
            for symbol in self.s.trading_pairs:
                if symbol in unsupported:
                    summary["symbols"][symbol] = {"skipped": "symbol_not_listed_on_exchange"}
                    continue
                try:
                    outcome = await self._screen_symbol(symbol, force=force)
                    summary["symbols"][symbol] = outcome
                    if outcome.get("signal_id"):
                        new_signals.append(outcome["signal_id"])
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    self._record_error(f"{symbol}: {exc}")
                    logger.error("Error screening %s: %s\n%s", symbol, exc, traceback.format_exc())
                    summary["symbols"][symbol] = {"error": str(exc)[:200]}

            # Notify after the DB work is done
            for signal_id in new_signals:
                await self._notify_new_signal(signal_id)
            summary["signals"] = new_signals

            try:
                stats = self.performance.update()
                summary["performance"] = stats.to_dict()
            except Exception as exc:
                self._record_error(f"performance: {exc}")
                logger.error("Performance update failed: %s", exc)

            self.cycles_completed += 1
            self.last_cycle_finished = utcnow()
            self.last_cycle_duration = time.time() - t0
            self._write_status()
            logger.info("──── Cycle finished in %.1fs — %d new signal(s) ────", self.last_cycle_duration, len(new_signals))
            summary["duration_s"] = round(self.last_cycle_duration, 2)
            return summary

    async def _screen_symbol(self, symbol: str, force: bool = False) -> dict:
        min_needed = min_candles_required(
            macd_slow=self.s.macd_slow, macd_signal=self.s.macd_signal, ema_periods=self.s.ema_periods,
            bb_period=self.s.bb_period,
        )
        raw = await self.collector.get_klines(symbol, self.s.timeframe, limit=self.s.kline_limit, closed_only=True)
        if raw is None or len(raw) < min_needed:
            logger.warning("%s: only %d candles (need %d) — skipping", symbol, 0 if raw is None else len(raw), min_needed)
            return {"skipped": "not_enough_candles", "candles": 0 if raw is None else len(raw)}

        df = calculate_all_indicators(
            raw, rsi_period=self.s.rsi_period, macd_fast=self.s.macd_fast, macd_slow=self.s.macd_slow,
            macd_signal=self.s.macd_signal, bb_period=self.s.bb_period, bb_std=self.s.bb_std,
            atr_period=self.s.atr_period, ema_periods=self.s.ema_periods, volume_avg_period=self.s.volume_avg_period,
        )
        if len(df) < 3:
            return {"skipped": "indicators_not_ready", "candles": len(raw)}
        last_candle = df["timestamp"].iloc[-1].to_pydatetime()
        snapshot = latest_snapshot(df)
        self.last_market[symbol] = snapshot

        # Each closed candle is evaluated exactly once
        if not force and self._processed_candles.get(symbol) == last_candle:
            return {"skipped": "candle_already_processed", "candle_time": last_candle.isoformat()}
        self._processed_candles[symbol] = last_candle

        htf_frames: Dict[str, pd.DataFrame] = {}
        for tf in self.s.confirmation_timeframes:
            try:
                htf_raw = await self.collector.get_klines(symbol, tf, limit=max(120, min_needed), closed_only=True)
                if htf_raw is not None and len(htf_raw) >= min_needed:
                    htf_frames[tf] = calculate_all_indicators(htf_raw, ema_periods=self.s.ema_periods)
            except Exception as exc:
                logger.warning("%s: could not load %s confirmation data: %s", symbol, tf, str(exc)[:120])

        evaluation: Evaluation = self.engine.evaluate(symbol, df, htf_frames)
        self.last_evaluations[symbol] = evaluation.to_dict() | {"evaluated_at": utcnow().isoformat()}
        row = df.iloc[-1]
        logger.info(
            "%s close=%.6g rsi=%.1f macd=%.4g/%.4g bb=[%.6g, %.6g] atr=%.4g | L%d S%d %s",
            symbol, row["close"], row["rsi"], row["macd"], row["macd_signal"], row["bb_lower"], row["bb_upper"],
            row["atr"], evaluation.long_score, evaluation.short_score,
            f"→ {evaluation.candidate.side} candidate" if evaluation.candidate else f"({evaluation.rejected_reason})",
        )
        if evaluation.candidate is None:
            return {"candle_time": last_candle.isoformat(), "long_score": evaluation.long_score,
                    "short_score": evaluation.short_score, "rejected": evaluation.rejected_reason}

        blocked = self._risk_block_reason(symbol, evaluation.candidate.side)
        if blocked:
            logger.info("%s: %s candidate blocked by risk rule: %s", symbol, evaluation.candidate.side, blocked)
            self.last_evaluations[symbol]["rejected_reason"] = blocked
            return {"candle_time": last_candle.isoformat(), "candidate": evaluation.candidate.side, "blocked": blocked}

        signal_id = self._persist_signal(evaluation)
        self.signals_generated += 1
        logger.info("✅ NEW SIGNAL #%d %s %s entry=%.6g sl=%.6g tp=%.6g/%.6g/%.6g conviction=%.0f%%",
                    signal_id, symbol, evaluation.candidate.side, evaluation.candidate.entry_price,
                    evaluation.candidate.sl_price, evaluation.candidate.tp1_price, evaluation.candidate.tp2_price,
                    evaluation.candidate.tp3_price, evaluation.candidate.conviction_score)
        return {"candle_time": last_candle.isoformat(), "signal_id": signal_id, "side": evaluation.candidate.side}

    # ------------------------------------------------------------------
    # Risk filters & persistence
    # ------------------------------------------------------------------
    def _risk_block_reason(self, symbol: str, side: str) -> Optional[str]:
        with self.db.session() as session:
            active_total = session.query(func.count(Signal.id)).filter(Signal.status == SignalStatus.ACTIVE).scalar() or 0
            if active_total >= self.s.max_active_signals:
                return f"max_active_signals ({active_total}/{self.s.max_active_signals})"
            if self.s.one_signal_per_symbol:
                active_symbol = session.query(Signal).filter(
                    Signal.symbol == symbol, Signal.status == SignalStatus.ACTIVE
                ).first()
                if active_symbol is not None:
                    return f"active_signal_exists (#{active_symbol.id} {active_symbol.side})"
            if self.s.signal_cooldown_minutes > 0:
                since = utcnow() - timedelta(minutes=self.s.signal_cooldown_minutes)
                recent = session.query(Signal).filter(
                    Signal.symbol == symbol, Signal.status.in_(SignalStatus.CLOSED_STATUSES),
                    Signal.closed_at >= since,
                ).order_by(Signal.closed_at.desc()).first()
                if recent is not None:
                    return f"cooldown (last signal #{recent.id} closed {recent.closed_at:%H:%M} UTC)"
                recent_open = session.query(Signal).filter(
                    Signal.symbol == symbol, Signal.timestamp >= since
                ).first()
                if recent_open is not None:
                    return f"cooldown (signal #{recent_open.id} opened {recent_open.timestamp:%H:%M} UTC)"
        return None

    def _persist_signal(self, evaluation: Evaluation) -> int:
        candidate = evaluation.candidate
        assert candidate is not None
        with self.db.session() as session:
            model = self.engine.to_model(candidate, source=self.collector.name)
            session.add(model)
            session.flush()
            self.db.add_event(session, model, "CREATED", candidate.entry_price,
                              f"{candidate.side} · {', '.join(candidate.conditions)} · conviction {candidate.conviction_score:.0f}%")
            return int(model.id)

    async def _notify_new_signal(self, signal_id: int) -> None:
        with self.db.session() as session:
            sig = session.get(Signal, signal_id)
            payload = sig.to_dict() if sig else None
        if payload is None:
            return
        try:
            message_id = await self.notifier.send_signal(payload)
        except Exception as exc:
            logger.warning("Telegram send failed for signal #%d: %s", signal_id, exc)
            return
        if message_id:
            with self.db.session() as session:
                sig = session.get(Signal, signal_id)
                if sig:
                    sig.telegram_message_id = message_id

    # ------------------------------------------------------------------
    # Monitor / summary
    # ------------------------------------------------------------------
    async def run_monitor(self) -> Dict[str, int]:
        async with self._monitor_lock:
            counters = await self.monitor.run_once()
            self.last_monitor_at = utcnow()
            if counters.get("closed") or counters.get("tp_hits"):
                try:
                    self.performance.update()
                except Exception as exc:
                    logger.error("Performance update failed: %s", exc)
            if counters.get("checked"):
                logger.debug("Monitor: %s", counters)
            return counters

    async def send_daily_summary(self) -> None:
        summary = self.performance.daily_summary()
        overall = self.performance.latest()
        await self.notifier.send_daily_summary(summary, overall)
        logger.info("Daily summary sent for %s", summary["day"])

    # ------------------------------------------------------------------
    # Status
    # ------------------------------------------------------------------
    def _record_error(self, message: str) -> None:
        self.last_error = message[:500]
        self.last_error_at = utcnow()

    def _stored_telegram_destinations(self) -> dict:
        """Chat ids discovered by a previous run (kept in bot_status)."""
        try:
            self.db.create_tables()
            with self.db.session() as session:
                row = self.db.get_or_create_status(session)
                return {"channel_id": row.telegram_channel_id, "admin_chat_id": row.telegram_admin_chat_id}
        except Exception as exc:  # pragma: no cover - DB not ready yet; discovery will run again
            logger.debug("Could not read stored Telegram destinations: %s", exc)
            return {}

    def _persist_telegram_destinations(self, channel_id: Optional[str], admin_chat_id: Optional[str]) -> None:
        with self.db.session() as session:
            row = self.db.get_or_create_status(session)
            row.telegram_channel_id = channel_id
            row.telegram_admin_chat_id = admin_chat_id

    def _write_status(self, started: bool = False) -> None:
        with self.db.session() as session:
            status = self.db.get_or_create_status(session)
            if started:
                status.started_at = self.started_at
            status.last_heartbeat = utcnow()
            status.last_cycle_started = self.last_cycle_started
            status.last_cycle_finished = self.last_cycle_finished
            status.last_cycle_duration_s = self.last_cycle_duration
            status.next_cycle_at = self.next_cycle_at
            status.last_monitor_at = self.last_monitor_at
            status.cycles_completed = self.cycles_completed
            status.signals_generated = self.signals_generated
            status.last_error = self.last_error
            status.last_error_at = self.last_error_at
            status.data_source = self.collector.name
            status.websocket_connected = bool(getattr(self.collector, "websocket_connected", False))
            status.version = self.s.app_version

    def status(self) -> dict:
        now = utcnow()
        return {
            "version": self.s.app_version,
            "running": not self._stop.is_set() and bool(self._tasks),
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "uptime_seconds": (now - self.started_at).total_seconds() if self.started_at else 0,
            "cycles_completed": self.cycles_completed,
            "signals_generated": self.signals_generated,
            "last_cycle_started": self.last_cycle_started.isoformat() if self.last_cycle_started else None,
            "last_cycle_finished": self.last_cycle_finished.isoformat() if self.last_cycle_finished else None,
            "last_cycle_duration_s": self.last_cycle_duration,
            "next_cycle_at": self.next_cycle_at.isoformat() if self.next_cycle_at else None,
            "last_monitor_at": self.last_monitor_at.isoformat() if self.last_monitor_at else None,
            "current_candle_open": current_candle_open(self.s.timeframe).isoformat(),
            "last_error": self.last_error,
            "last_error_at": self.last_error_at.isoformat() if self.last_error_at else None,
            "data_source": self.collector.stats() if hasattr(self.collector, "stats") else {"source": self.collector.name},
            "telegram": self.notifier.stats(),
            "processed_candles": {k: v.isoformat() for k, v in self._processed_candles.items()},
        }
