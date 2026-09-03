"""
Performance statistics.

    win_rate      = wins / closed * 100          (break-even trades are excluded from the denominator)
    profit_factor = gross_profit / gross_loss
    expectancy    = win_rate * avg_win - loss_rate * avg_loss     (% per trade)
    total_pnl     = Σ profit_loss_pct

`compute_stats()` is a pure function over a list of closed signals, so the API
can compute per-symbol / per-side / last-N-days breakdowns with the same code
that maintains the aggregate `performance` table row.
"""
from __future__ import annotations

import logging
import math
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from typing import Dict, Iterable, List, Optional

from sqlalchemy import func

from database import Database, Performance, Signal, SignalOutcome, SignalStatus
from utils import utcnow

logger = logging.getLogger("performance")

LIVE_SOURCES_EXCLUDED = ("backtest",)  # backtest rows never count towards live statistics


def _live(query):
    """Restrict a Signal query to live (non-backtest) signals."""
    return query.filter((Signal.source.is_(None)) | (Signal.source.notin_(LIVE_SOURCES_EXCLUDED)))


@dataclass
class Stats:
    total_signals: int = 0
    active_signals: int = 0
    closed_signals: int = 0
    total_wins: int = 0
    total_losses: int = 0
    total_breakeven: int = 0
    win_rate: float = 0.0
    total_pnl_pct: float = 0.0
    gross_profit_pct: float = 0.0
    gross_loss_pct: float = 0.0
    profit_factor: float = 0.0
    expectancy: float = 0.0
    avg_win_pct: float = 0.0
    avg_loss_pct: float = 0.0
    avg_r: float = 0.0
    best_trade_pct: float = 0.0
    worst_trade_pct: float = 0.0
    max_drawdown_pct: float = 0.0
    current_streak: int = 0
    tp1_hit_rate: float = 0.0
    tp2_hit_rate: float = 0.0
    tp3_hit_rate: float = 0.0
    avg_duration_minutes: float = 0.0

    def to_dict(self) -> dict:
        d = asdict(self)
        # JSON cannot encode inf
        if math.isinf(d["profit_factor"]):
            d["profit_factor"] = None
        return d


def _safe_pf(gross_profit: float, gross_loss: float) -> float:
    if gross_loss > 0:
        return gross_profit / gross_loss
    return float("inf") if gross_profit > 0 else 0.0


def compute_stats(closed: Iterable[Signal], active_count: int = 0, total_count: Optional[int] = None) -> Stats:
    closed = sorted([s for s in closed if s.status in SignalStatus.CLOSED_STATUSES],
                    key=lambda s: (s.closed_at or s.timestamp, s.id or 0))
    st = Stats()
    st.closed_signals = len(closed)
    st.active_signals = active_count
    st.total_signals = total_count if total_count is not None else len(closed) + active_count
    if not closed:
        return st

    pnls = [float(s.profit_loss_pct or 0.0) for s in closed]
    wins = [p for s, p in zip(closed, pnls) if s.outcome == SignalOutcome.WIN]
    losses = [p for s, p in zip(closed, pnls) if s.outcome == SignalOutcome.LOSS]
    st.total_wins = len(wins)
    st.total_losses = len(losses)
    st.total_breakeven = len(closed) - len(wins) - len(losses)

    decisive = st.total_wins + st.total_losses
    st.win_rate = (st.total_wins / decisive * 100.0) if decisive else 0.0
    st.total_pnl_pct = sum(pnls)
    st.gross_profit_pct = sum(p for p in pnls if p > 0)
    st.gross_loss_pct = abs(sum(p for p in pnls if p < 0))
    st.profit_factor = _safe_pf(st.gross_profit_pct, st.gross_loss_pct)
    st.avg_win_pct = (sum(wins) / len(wins)) if wins else 0.0
    st.avg_loss_pct = abs(sum(losses) / len(losses)) if losses else 0.0
    wr = st.win_rate / 100.0
    st.expectancy = wr * st.avg_win_pct - (1.0 - wr) * st.avg_loss_pct if decisive else 0.0
    rs = [float(s.profit_loss_r) for s in closed if s.profit_loss_r is not None]
    st.avg_r = sum(rs) / len(rs) if rs else 0.0
    st.best_trade_pct = max(pnls)
    st.worst_trade_pct = min(pnls)

    # max drawdown of the cumulative PnL curve (in % points)
    peak = 0.0
    cum = 0.0
    mdd = 0.0
    for p in pnls:
        cum += p
        peak = max(peak, cum)
        mdd = max(mdd, peak - cum)
    st.max_drawdown_pct = mdd

    # streak (ignores break-even trades)
    streak = 0
    for s in reversed(closed):
        if s.outcome == SignalOutcome.WIN:
            if streak < 0:
                break
            streak += 1
        elif s.outcome == SignalOutcome.LOSS:
            if streak > 0:
                break
            streak -= 1
    st.current_streak = streak

    n = len(closed)
    st.tp1_hit_rate = sum(1 for s in closed if (s.tp_hits or 0) >= 1) / n * 100.0
    st.tp2_hit_rate = sum(1 for s in closed if (s.tp_hits or 0) >= 2) / n * 100.0
    st.tp3_hit_rate = sum(1 for s in closed if (s.tp_hits or 0) >= 3) / n * 100.0
    durations = [
        (s.closed_at - s.timestamp).total_seconds() / 60.0 for s in closed if s.closed_at and s.timestamp
    ]
    st.avg_duration_minutes = sum(durations) / len(durations) if durations else 0.0
    return st


class PerformanceTracker:
    def __init__(self, db: Database):
        self.db = db

    # ------------------------------------------------------------------
    def update(self) -> Stats:
        """Recompute aggregate statistics and upsert the single `performance` row."""
        with self.db.session() as session:
            closed = _live(session.query(Signal).filter(Signal.status.in_(SignalStatus.CLOSED_STATUSES))).all()
            active = _live(session.query(func.count(Signal.id)).filter(Signal.status == SignalStatus.ACTIVE)).scalar() or 0
            total = _live(session.query(func.count(Signal.id))).scalar() or 0
            stats = compute_stats(closed, active_count=int(active), total_count=int(total))

            perf = session.query(Performance).order_by(Performance.id).first()
            if perf is None:
                perf = Performance()
                session.add(perf)
            for key, value in asdict(stats).items():
                if key == "profit_factor" and math.isinf(value):
                    value = 999.0  # store a large finite number instead of inf
                setattr(perf, key, value)
            perf.last_updated = utcnow()
        return stats

    # ------------------------------------------------------------------
    def latest(self) -> Optional[dict]:
        with self.db.session() as session:
            perf = session.query(Performance).order_by(Performance.id).first()
            return perf.to_dict() if perf else None

    def breakdown(self, days: Optional[int] = None) -> Dict[str, dict]:
        """Per-symbol, per-side and per-conviction-bucket statistics."""
        with self.db.session() as session:
            q = _live(session.query(Signal).filter(Signal.status.in_(SignalStatus.CLOSED_STATUSES)))
            if days:
                q = q.filter(Signal.closed_at >= utcnow() - timedelta(days=days))
            closed: List[Signal] = q.all()
            active: List[Signal] = _live(session.query(Signal).filter(Signal.status == SignalStatus.ACTIVE)).all()

        def group(key_fn):
            groups: Dict[str, List[Signal]] = {}
            for s in closed:
                groups.setdefault(key_fn(s), []).append(s)
            active_groups: Dict[str, int] = {}
            for s in active:
                k = key_fn(s)
                active_groups[k] = active_groups.get(k, 0) + 1
            keys = sorted(set(groups) | set(active_groups))
            return {k: compute_stats(groups.get(k, []), active_count=active_groups.get(k, 0)).to_dict() for k in keys}

        def conviction_bucket(s: Signal) -> str:
            c = s.conviction_score or 0
            if c >= 80:
                return "80-100"
            if c >= 65:
                return "65-79"
            return "<65"

        return {
            "overall": compute_stats(closed, active_count=len(active)).to_dict(),
            "by_symbol": group(lambda s: s.symbol),
            "by_side": group(lambda s: s.side),
            "by_conviction": group(conviction_bucket),
            "by_status": {
                k: v for k, v in sorted(
                    ((st, sum(1 for s in closed if s.status == st)) for st in SignalStatus.CLOSED_STATUSES)
                )
            },
        }

    def equity_curve(self, days: Optional[int] = None) -> List[dict]:
        with self.db.session() as session:
            q = _live(session.query(Signal).filter(Signal.status.in_(SignalStatus.CLOSED_STATUSES)))
            if days:
                q = q.filter(Signal.closed_at >= utcnow() - timedelta(days=days))
            closed = q.order_by(Signal.closed_at, Signal.id).all()
        cum = 0.0
        points = []
        for s in closed:
            cum += float(s.profit_loss_pct or 0.0)
            points.append({
                "time": (s.closed_at or s.timestamp).isoformat(),
                "signal_id": s.id,
                "symbol": s.symbol,
                "pnl_pct": s.profit_loss_pct,
                "cumulative_pnl_pct": round(cum, 4),
            })
        return points

    def daily_summary(self, day: Optional[datetime] = None) -> dict:
        """Statistics for one UTC day (defaults to yesterday) – used for the Telegram digest."""
        day = (day or (utcnow() - timedelta(days=1))).replace(hour=0, minute=0, second=0, microsecond=0)
        end = day + timedelta(days=1)
        with self.db.session() as session:
            closed = _live(session.query(Signal).filter(
                Signal.status.in_(SignalStatus.CLOSED_STATUSES), Signal.closed_at >= day, Signal.closed_at < end
            )).all()
            opened = _live(session.query(func.count(Signal.id)).filter(
                Signal.timestamp >= day, Signal.timestamp < end
            )).scalar() or 0
            active = _live(session.query(func.count(Signal.id)).filter(Signal.status == SignalStatus.ACTIVE)).scalar() or 0
            stats = compute_stats(closed, active_count=int(active))
        return {"day": day.date().isoformat(), "opened": int(opened), "closed": stats.to_dict()}
