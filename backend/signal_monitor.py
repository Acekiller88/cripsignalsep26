"""
Signal lifecycle monitoring: TP / SL / expiry detection and PnL realisation.

Position model ("scale-out in thirds") – the de-facto standard for 3-target
signals and the one used to compute realised PnL:

    * 1/3 of the position is closed at TP1, TP2 and TP3 respectively.
    * After TP1 the stop is moved to break-even (entry) – configurable.
    * After TP2 the stop is trailed to TP1.
    * If the stop is hit, the remaining fraction is closed at the stop.
    * If the signal expires (default 48 h) the remainder is closed at market.

`walk_candles()` is a pure function used both by the live monitor (with fresh
1-minute candles) and by the backtester, so live tracking and backtests are
guaranteed to use identical rules.  When a candle touches both the stop and a
target we conservatively assume the stop was hit first.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

import pandas as pd

from config import Settings
from database import Database, Side, Signal, SignalOutcome, SignalStatus
from utils import timeframe_to_seconds, utcnow

logger = logging.getLogger("monitor")

TP_LEVELS = ("tp1_price", "tp2_price", "tp3_price")
PARTIAL_FRACTION = 1.0 / 3.0
BREAKEVEN_EPS_PCT = 0.01  # |PnL| below this is classified as BREAKEVEN


# ---------------------------------------------------------------------------
# Pure state machine
# ---------------------------------------------------------------------------
@dataclass
class PositionState:
    side: str
    entry: float
    sl: float
    tps: Tuple[float, float, float]
    tp_hits: int = 0
    current_sl: float = 0.0
    realised_pct: float = 0.0        # PnL already banked from partial closes (% of full position)
    closed_fraction: float = 0.0
    max_favorable_pct: float = 0.0
    max_adverse_pct: float = 0.0
    events: List[dict] = field(default_factory=list)  # {type, price, time}
    closed: bool = False
    status: Optional[str] = None
    exit_price: Optional[float] = None
    closed_at: Optional[datetime] = None
    tp_hit_times: Dict[int, datetime] = field(default_factory=dict)

    def __post_init__(self):
        if not self.current_sl:
            self.current_sl = self.sl

    # --- helpers ---------------------------------------------------------
    def pct(self, price: float) -> float:
        d = 1.0 if self.side == Side.LONG else -1.0
        return d * (price - self.entry) / self.entry * 100.0

    @property
    def sl_pct(self) -> float:
        return abs(self.entry - self.sl) / self.entry * 100.0

    @property
    def total_pct(self) -> float:
        return self.realised_pct

    def r_multiple(self) -> float:
        return self.realised_pct / self.sl_pct if self.sl_pct > 0 else 0.0

    def outcome(self) -> str:
        if abs(self.realised_pct) < BREAKEVEN_EPS_PCT:
            return SignalOutcome.BREAKEVEN
        return SignalOutcome.WIN if self.realised_pct > 0 else SignalOutcome.LOSS

    # --- transitions -----------------------------------------------------
    def _bank(self, price: float, fraction: float) -> None:
        self.realised_pct += self.pct(price) * fraction
        self.closed_fraction = min(1.0, self.closed_fraction + fraction)

    def _close(self, price: float, status: str, when: datetime, event_type: str) -> None:
        remaining = max(0.0, 1.0 - self.closed_fraction)
        if remaining > 0:
            self._bank(price, remaining)
        self.closed = True
        self.status = status
        self.exit_price = price
        self.closed_at = when
        self.events.append({"type": event_type, "price": price, "time": when})

    def apply_candle(self, high: float, low: float, close: float, when: datetime, settings: Settings) -> None:
        """Process one closed candle (chronological order required)."""
        if self.closed:
            return
        is_long = self.side == Side.LONG
        best = high if is_long else low
        worst = low if is_long else high
        self.max_favorable_pct = max(self.max_favorable_pct, self.pct(best))
        self.max_adverse_pct = min(self.max_adverse_pct, self.pct(worst))

        stop_touched = (low <= self.current_sl) if is_long else (high >= self.current_sl)
        if stop_touched:
            # conservative: the stop is assumed to trigger before any target in the same candle
            if self.tp_hits == 0:
                self._close(self.current_sl, SignalStatus.SL_HIT, when, "SL_HIT")
            else:
                self._close(self.current_sl, SignalStatus.TP_HIT, when, "SL_HIT")
            return

        # Targets, in order; several may be hit within a single candle
        while self.tp_hits < 3 and not self.closed:
            target = self.tps[self.tp_hits]
            hit = (high >= target) if is_long else (low <= target)
            if not hit:
                break
            self.tp_hits += 1
            self.tp_hit_times[self.tp_hits] = when
            if self.tp_hits == 3:
                self._close(target, SignalStatus.TP_HIT, when, "TP3_HIT")
                break
            self.events.append({"type": f"TP{self.tp_hits}_HIT", "price": target, "time": when})
            self._bank(target, PARTIAL_FRACTION)
            if self.tp_hits == 1 and settings.move_sl_to_breakeven_after_tp1:
                self._move_sl(self.entry, when, "break-even")
            elif self.tp_hits == 2:
                self._move_sl(self.tps[0], when, "TP1 (trailing)")

    def _move_sl(self, new_sl: float, when: datetime, label: str) -> None:
        is_long = self.side == Side.LONG
        improves = new_sl > self.current_sl if is_long else new_sl < self.current_sl
        if improves:
            self.current_sl = new_sl
            self.events.append({"type": "SL_MOVED", "price": new_sl, "time": when, "label": label})

    def expire(self, price: float, when: datetime) -> None:
        if not self.closed:
            self._close(price, SignalStatus.EXPIRED, when, "EXPIRED")


def state_from_signal(signal: Signal) -> PositionState:
    """Rebuild the state machine from a persisted signal."""
    st = PositionState(
        side=signal.side,
        entry=float(signal.entry_price),
        sl=float(signal.sl_price),
        tps=(float(signal.tp1_price), float(signal.tp2_price), float(signal.tp3_price)),
        tp_hits=int(signal.tp_hits or 0),
        current_sl=float(signal.current_sl or signal.sl_price),
        max_favorable_pct=float(signal.max_favorable_pct or 0.0),
        max_adverse_pct=float(signal.max_adverse_pct or 0.0),
    )
    # banked PnL from partial closes already taken
    for i in range(st.tp_hits):
        st._bank(st.tps[i], PARTIAL_FRACTION)
    return st


def walk_candles(state: PositionState, candles: pd.DataFrame, settings: Settings,
                 expires_at: Optional[datetime] = None) -> PositionState:
    """Feed candles (columns timestamp/high/low/close) through the state machine."""
    if candles is None or candles.empty:
        return state
    tf_seconds = 60
    if len(candles) >= 2:
        tf_seconds = int((candles["timestamp"].iloc[1] - candles["timestamp"].iloc[0]).total_seconds()) or 60
    for row in candles.itertuples(index=False):
        ts = row.timestamp.to_pydatetime() if isinstance(row.timestamp, pd.Timestamp) else row.timestamp
        candle_close_time = ts + timedelta(seconds=tf_seconds)
        if expires_at is not None and candle_close_time > expires_at and not state.closed:
            state.expire(float(row.close), candle_close_time)
            break
        state.apply_candle(float(row.high), float(row.low), float(row.close), candle_close_time, settings)
        if state.closed:
            break
    return state


# ---------------------------------------------------------------------------
# Live monitor
# ---------------------------------------------------------------------------
class SignalMonitor:
    """Periodically checks active signals against fresh 1-minute candles."""

    def __init__(self, settings: Settings, db: Database, collector, notifier=None):
        self.s = settings
        self.db = db
        self.collector = collector
        self.notifier = notifier
        self.check_timeframe = "1m"

    async def run_once(self) -> Dict[str, int]:
        """Check every active signal once. Returns counters for logging/tests."""
        counters = {"checked": 0, "tp_hits": 0, "closed": 0, "errors": 0}
        with self.db.session() as session:
            active: List[Signal] = (
                session.query(Signal).filter(Signal.status == SignalStatus.ACTIVE).order_by(Signal.id).all()
            )
        if not active:
            return counters

        by_symbol: Dict[str, List[Signal]] = {}
        for sig in active:
            by_symbol.setdefault(sig.symbol, []).append(sig)

        now = utcnow()
        for symbol, signals in by_symbol.items():
            start = min(self._monitor_start(sig) for sig in signals)
            try:
                candles = await self._fetch_candles(symbol, start, now)
            except Exception as exc:
                counters["errors"] += 1
                logger.warning("Monitor: could not fetch %s candles: %s", symbol, str(exc)[:160])
                continue
            for sig in signals:
                try:
                    result = await self._process_signal(sig.id, candles, now)
                    counters["checked"] += 1
                    counters["tp_hits"] += result.get("tp_hits", 0)
                    counters["closed"] += 1 if result.get("closed") else 0
                except Exception as exc:
                    counters["errors"] += 1
                    logger.exception("Monitor: error processing signal #%s: %s", sig.id, exc)
        return counters

    # ------------------------------------------------------------------
    def _monitor_start(self, sig: Signal) -> datetime:
        if sig.last_checked_at:
            return sig.last_checked_at
        if sig.candle_time:
            return sig.candle_time + timedelta(seconds=timeframe_to_seconds(sig.timeframe or self.s.timeframe))
        return sig.timestamp.replace(second=0, microsecond=0)

    async def _fetch_candles(self, symbol: str, start: datetime, now: datetime) -> pd.DataFrame:
        """Closed 1m candles with open time in [start, now)."""
        frames = []
        cursor = start
        # Binance returns at most 1500 candles per call; loop if the bot was down for a while.
        for _ in range(20):
            df = await self.collector.fetch_candles_since(symbol, self.check_timeframe, cursor, limit=1000)
            if df is None or df.empty:
                break
            frames.append(df)
            last_open = df["timestamp"].iloc[-1].to_pydatetime()
            if len(df) < 1000 or last_open >= now:
                break
            cursor = last_open + timedelta(minutes=1)
        if not frames:
            return pd.DataFrame(columns=["timestamp", "open", "high", "low", "close", "volume"])
        candles = pd.concat(frames, ignore_index=True).drop_duplicates("timestamp").sort_values("timestamp")
        closed = candles["timestamp"] + timedelta(minutes=1) <= now
        return candles[closed & (candles["timestamp"] >= start)].reset_index(drop=True)

    async def _process_signal(self, signal_id: int, candles: pd.DataFrame, now: datetime) -> dict:
        result = {"tp_hits": 0, "closed": False}
        notifications: List[Tuple[str, dict]] = []
        with self.db.session() as session:
            sig: Optional[Signal] = session.get(Signal, signal_id)
            if sig is None or sig.status != SignalStatus.ACTIVE:
                return result
            start = self._monitor_start(sig)
            mine = candles[candles["timestamp"] >= start]
            expires_at = sig.timestamp + timedelta(hours=self.s.signal_expiry_hours)

            state = state_from_signal(sig)
            tp_before = state.tp_hits
            sl_before = state.current_sl
            if not mine.empty:
                walk_candles(state, mine, self.s, expires_at=expires_at)
                sig.last_checked_at = mine["timestamp"].iloc[-1].to_pydatetime() + timedelta(minutes=1)
            if not state.closed and now >= expires_at:
                last_price = float(mine["close"].iloc[-1]) if not mine.empty else None
                if last_price is None:
                    last_price = await self.collector.get_last_price(sig.symbol)
                if last_price is not None:
                    state.expire(last_price, now)

            # --- persist state -------------------------------------------
            sig.max_favorable_pct = state.max_favorable_pct
            sig.max_adverse_pct = state.max_adverse_pct
            for ev in state.events:
                et = ev["type"]
                self.db.add_event(session, sig, et, ev.get("price"), ev.get("label", ""), ev.get("time"))
                if et.startswith("TP") and et.endswith("_HIT"):
                    level = int(et[2])
                    setattr(sig, f"tp{level}_hit_at", ev["time"])
            if state.tp_hits != tp_before:
                sig.tp_hits = state.tp_hits
                result["tp_hits"] = state.tp_hits - tp_before
            if state.current_sl != sl_before:
                sig.current_sl = state.current_sl

            if state.closed:
                sig.status = state.status
                sig.exit_price = state.exit_price
                sig.closed_at = state.closed_at
                sig.profit_loss_pct = round(state.realised_pct, 4)
                sig.profit_loss_r = round(state.r_multiple(), 3)
                sig.outcome = state.outcome()
                result["closed"] = True
                logger.info("Signal #%s %s %s closed: %s %s %+.2f%% (%.2fR)", sig.id, sig.symbol, sig.side,
                            sig.status, sig.outcome, sig.profit_loss_pct, sig.profit_loss_r)
                notifications.append(("closed", sig.to_dict()))
            else:
                for level in range(tp_before + 1, state.tp_hits + 1):
                    logger.info("Signal #%s %s %s hit TP%d", sig.id, sig.symbol, sig.side, level)
                    notifications.append(("tp", {"signal": sig.to_dict(), "level": level,
                                                 "new_sl": state.current_sl if state.current_sl != sl_before else None}))
        # --- notify outside of the DB transaction -------------------------
        if self.notifier is not None:
            for kind, payload in notifications:
                try:
                    if kind == "closed":
                        await self.notifier.send_closed(payload)
                    elif kind == "tp" and self.s.notify_tp_updates:
                        await self.notifier.send_tp_update(payload["signal"], payload["level"], payload["new_sl"])
                except Exception as exc:  # never let Telegram break monitoring
                    logger.warning("Telegram notification failed: %s", str(exc)[:160])
        return result
