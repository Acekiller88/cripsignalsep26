import asyncio
from datetime import datetime, timedelta

import pandas as pd
import pytest

from database import Side, Signal, SignalEvent, SignalOutcome, SignalStatus
from performance_tracker import PerformanceTracker, compute_stats
from signal_monitor import PositionState, SignalMonitor, state_from_signal, walk_candles


# ---------------------------------------------------------------------------
# PositionState (pure state machine)
# ---------------------------------------------------------------------------
def _state(side=Side.LONG, entry=100.0, atr=2.0):
    d = 1 if side == Side.LONG else -1
    return PositionState(side=side, entry=entry, sl=entry - d * 2 * atr,
                         tps=(entry + d * 2 * atr, entry + d * 4 * atr, entry + d * 6 * atr))


def _candles(rows, start=datetime(2026, 9, 3, 12, 0), minutes=1):
    return pd.DataFrame([
        {"timestamp": start + timedelta(minutes=minutes * i), "open": r[0], "high": r[1], "low": r[2], "close": r[3]}
        for i, r in enumerate(rows)
    ])


def test_long_stop_loss_full(settings):
    st = _state()
    walk_candles(st, _candles([(100, 100.5, 99.5, 100), (99.8, 100, 95.9, 96)]), settings)
    assert st.closed and st.status == SignalStatus.SL_HIT
    assert st.tp_hits == 0
    assert st.realised_pct == pytest.approx(-4.0)
    assert st.outcome() == SignalOutcome.LOSS
    assert st.r_multiple() == pytest.approx(-1.0)


def test_long_all_targets(settings):
    st = _state()
    walk_candles(st, _candles([(100, 104.1, 99.9, 104), (104, 108.2, 103.9, 108), (108, 112.5, 107.9, 112)]), settings)
    assert st.closed and st.status == SignalStatus.TP_HIT and st.tp_hits == 3
    # thirds at +4%, +8%, +12%
    assert st.realised_pct == pytest.approx((4 + 8 + 12) / 3)
    assert st.outcome() == SignalOutcome.WIN
    assert st.r_multiple() == pytest.approx(2.0)
    assert [e["type"] for e in st.events] == ["TP1_HIT", "SL_MOVED", "TP2_HIT", "SL_MOVED", "TP3_HIT"]


def test_long_tp1_then_breakeven_stop(settings):
    st = _state()
    walk_candles(st, _candles([(100, 104.1, 99.9, 104), (104, 104.5, 99.9, 100.5)]), settings)
    assert st.closed and st.status == SignalStatus.TP_HIT and st.tp_hits == 1
    # 1/3 at +4%, 2/3 at 0% (break-even)
    assert st.realised_pct == pytest.approx(4.0 / 3)
    assert st.outcome() == SignalOutcome.WIN
    assert st.current_sl == pytest.approx(100.0)


def test_long_tp2_then_trailing_stop_at_tp1(settings):
    st = _state()
    walk_candles(st, _candles([(100, 108.1, 99.9, 108), (108, 108.5, 103.9, 105)]), settings)
    assert st.closed and st.tp_hits == 2
    assert st.realised_pct == pytest.approx((4 + 8 + 4) / 3)


def test_breakeven_disabled(settings):
    cfg = settings.with_overrides(move_sl_to_breakeven_after_tp1=False)
    st = _state()
    walk_candles(st, _candles([(100, 104.1, 99.9, 104), (104, 104.5, 99.9, 100.5)]), cfg)
    assert not st.closed and st.current_sl == pytest.approx(96.0)


def test_short_targets_and_stop(settings):
    st = _state(side=Side.SHORT)
    walk_candles(st, _candles([(100, 100.1, 95.9, 96)]), settings)  # TP1 (96) hit
    assert st.tp_hits == 1 and not st.closed and st.current_sl == pytest.approx(100.0)
    walk_candles(st, _candles([(96, 100.2, 95.5, 99)]), settings)  # back to entry -> BE stop
    assert st.closed and st.realised_pct == pytest.approx(4.0 / 3)

    st2 = _state(side=Side.SHORT)
    walk_candles(st2, _candles([(100, 104.5, 99, 104)]), settings)
    assert st2.status == SignalStatus.SL_HIT and st2.realised_pct == pytest.approx(-4.0)


def test_stop_first_when_candle_touches_both(settings):
    st = _state()
    # one candle spans SL (96) and TP1 (104): conservative -> SL
    walk_candles(st, _candles([(100, 105, 95, 100)]), settings)
    assert st.status == SignalStatus.SL_HIT


def test_expiry_closes_at_market(settings):
    st = _state()
    start = datetime(2026, 9, 1, 0, 0)
    candles = _candles([(100, 101, 99, 100.5)] * 5, start=start, minutes=60)
    walk_candles(st, candles, settings, expires_at=start + timedelta(hours=3))
    assert st.closed and st.status == SignalStatus.EXPIRED
    assert st.realised_pct == pytest.approx(0.5)
    assert st.outcome() == SignalOutcome.WIN


def test_excursions_tracked(settings):
    st = _state()
    walk_candles(st, _candles([(100, 103, 97, 101)]), settings)
    assert st.max_favorable_pct == pytest.approx(3.0)
    assert st.max_adverse_pct == pytest.approx(-3.0)


def test_state_from_signal_restores_partial_progress():
    sig = Signal(symbol="BTCUSDT", side="LONG", entry_price=100, sl_price=96, current_sl=100, tp1_price=104,
                 tp2_price=108, tp3_price=112, timestamp=datetime.utcnow(), status="ACTIVE", tp_hits=1)
    st = state_from_signal(sig)
    assert st.tp_hits == 1 and st.current_sl == 100 and st.realised_pct == pytest.approx(4 / 3)


# ---------------------------------------------------------------------------
# SignalMonitor against the database
# ---------------------------------------------------------------------------
class FakeCollector:
    name = "fake"
    websocket_connected = False

    def __init__(self, candles: pd.DataFrame, last_price: float = 100.0):
        self.candles = candles
        self.last_price = last_price

    async def fetch_candles_since(self, symbol, timeframe, since, limit=1000):
        df = self.candles[self.candles["timestamp"] >= since]
        return df.head(limit).reset_index(drop=True)

    async def get_last_price(self, symbol):
        return self.last_price


class RecordingNotifier:
    def __init__(self):
        self.messages = []

    async def send_tp_update(self, sig, level, new_sl):
        self.messages.append(("tp", sig["id"], level, new_sl))

    async def send_closed(self, sig):
        self.messages.append(("closed", sig["id"], sig["status"], sig["outcome"]))


def _insert_signal(db, **kw):
    now = datetime.utcnow().replace(second=0, microsecond=0)
    defaults = dict(symbol="BTCUSDT", side="LONG", timeframe="15m", entry_price=100.0, sl_price=96.0, current_sl=96.0,
                    tp1_price=104.0, tp2_price=108.0, tp3_price=112.0, timestamp=now - timedelta(minutes=30),
                    candle_time=now - timedelta(minutes=45), status="ACTIVE", tp_hits=0, conviction_score=60)
    defaults.update(kw)
    with db.session() as s:
        sig = Signal(**defaults)
        s.add(sig)
        s.flush()
        return sig.id


def test_monitor_closes_signal_and_notifies(settings, db):
    now = datetime.utcnow().replace(second=0, microsecond=0)
    sid = _insert_signal(db)
    candles = pd.DataFrame([
        {"timestamp": now - timedelta(minutes=20), "open": 100, "high": 104.2, "low": 99.5, "close": 104, "volume": 1},
        {"timestamp": now - timedelta(minutes=10), "open": 104, "high": 108.3, "low": 103.9, "close": 108, "volume": 1},
        {"timestamp": now - timedelta(minutes=5), "open": 108, "high": 109, "low": 103.5, "close": 104, "volume": 1},
    ])
    notifier = RecordingNotifier()
    mon = SignalMonitor(settings, db, FakeCollector(candles), notifier)
    counters = asyncio.run(mon.run_once())
    assert counters["checked"] == 1 and counters["closed"] == 1 and counters["tp_hits"] == 2
    with db.session() as s:
        sig = s.get(Signal, sid)
        assert sig.status == SignalStatus.TP_HIT and sig.outcome == SignalOutcome.WIN and sig.tp_hits == 2
        assert sig.profit_loss_pct == pytest.approx((4 + 8 + 4) / 3, abs=1e-3)
        assert sig.exit_price == pytest.approx(104.0)
        assert sig.tp1_hit_at is not None and sig.tp2_hit_at is not None and sig.closed_at is not None
        events = [e.event_type for e in s.query(SignalEvent).filter_by(signal_id=sid).all()]
        assert "TP1_HIT" in events and "TP2_HIT" in events and "SL_HIT" in events
    assert notifier.messages == [("closed", sid, "TP_HIT", "WIN")]


def test_monitor_partial_progress_persists_and_resumes(settings, db):
    now = datetime.utcnow().replace(second=0, microsecond=0)
    sid = _insert_signal(db)
    first = pd.DataFrame([
        {"timestamp": now - timedelta(minutes=20), "open": 100, "high": 104.2, "low": 99.5, "close": 104, "volume": 1},
    ])
    notifier = RecordingNotifier()
    mon = SignalMonitor(settings, db, FakeCollector(first), notifier)
    asyncio.run(mon.run_once())
    with db.session() as s:
        sig = s.get(Signal, sid)
        assert sig.status == "ACTIVE" and sig.tp_hits == 1 and sig.current_sl == pytest.approx(100.0)
        assert sig.last_checked_at == now - timedelta(minutes=19)
    assert notifier.messages == [("tp", sid, 1, 100.0)]

    # second pass: new candle drops to break-even
    second = pd.concat([first, pd.DataFrame([
        {"timestamp": now - timedelta(minutes=10), "open": 104, "high": 104.5, "low": 99.9, "close": 101, "volume": 1},
    ])])
    mon.collector = FakeCollector(second)
    asyncio.run(mon.run_once())
    with db.session() as s:
        sig = s.get(Signal, sid)
        assert sig.status == SignalStatus.TP_HIT and sig.tp_hits == 1
        assert sig.profit_loss_pct == pytest.approx(4 / 3, abs=1e-3)


def test_monitor_expires_old_signal(settings, db):
    now = datetime.utcnow()
    sid = _insert_signal(db, timestamp=now - timedelta(hours=settings.signal_expiry_hours + 1),
                         candle_time=now - timedelta(hours=settings.signal_expiry_hours + 1))
    mon = SignalMonitor(settings, db, FakeCollector(pd.DataFrame(columns=["timestamp", "open", "high", "low", "close", "volume"]), last_price=101.0))
    asyncio.run(mon.run_once())
    with db.session() as s:
        sig = s.get(Signal, sid)
        assert sig.status == SignalStatus.EXPIRED and sig.exit_price == pytest.approx(101.0)
        assert sig.profit_loss_pct == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# Performance
# ---------------------------------------------------------------------------
def _closed(pnl, outcome, tp_hits=0, r=None, ts=None):
    ts = ts or datetime(2026, 9, 1)
    return Signal(symbol="BTCUSDT", side="LONG", entry_price=1, sl_price=1, tp1_price=1, tp2_price=1, tp3_price=1,
                  timestamp=ts, closed_at=ts + timedelta(hours=2), status="TP_HIT" if pnl > 0 else "SL_HIT",
                  outcome=outcome, profit_loss_pct=pnl, profit_loss_r=r, tp_hits=tp_hits)


def test_compute_stats_formulas():
    trades = [
        _closed(6.0, "WIN", 3, 1.5, datetime(2026, 9, 1)),
        _closed(-4.0, "LOSS", 0, -1.0, datetime(2026, 9, 2)),
        _closed(2.0, "WIN", 1, 0.5, datetime(2026, 9, 3)),
        _closed(-4.0, "LOSS", 0, -1.0, datetime(2026, 9, 4)),
        _closed(8.0, "WIN", 3, 2.0, datetime(2026, 9, 5)),
    ]
    st = compute_stats(trades, active_count=2)
    assert st.closed_signals == 5 and st.active_signals == 2 and st.total_signals == 7
    assert st.total_wins == 3 and st.total_losses == 2
    assert st.win_rate == pytest.approx(60.0)
    assert st.total_pnl_pct == pytest.approx(8.0)
    assert st.gross_profit_pct == pytest.approx(16.0) and st.gross_loss_pct == pytest.approx(8.0)
    assert st.profit_factor == pytest.approx(2.0)
    assert st.avg_win_pct == pytest.approx(16 / 3) and st.avg_loss_pct == pytest.approx(4.0)
    assert st.expectancy == pytest.approx(0.6 * 16 / 3 - 0.4 * 4.0)
    assert st.avg_r == pytest.approx((1.5 - 1 + 0.5 - 1 + 2) / 5)
    assert st.max_drawdown_pct == pytest.approx(6.0)  # 6, 2, 4, 0, 8 -> peak 6, trough 0
    assert st.current_streak == 1
    assert st.tp1_hit_rate == pytest.approx(60.0) and st.tp3_hit_rate == pytest.approx(40.0)
    assert st.avg_duration_minutes == pytest.approx(120.0)
    assert st.best_trade_pct == 8.0 and st.worst_trade_pct == -4.0


def test_compute_stats_empty_and_no_losses():
    st = compute_stats([])
    assert st.win_rate == 0 and st.profit_factor == 0 and st.expectancy == 0
    st2 = compute_stats([_closed(3.0, "WIN")])
    assert st2.profit_factor == float("inf")
    assert st2.to_dict()["profit_factor"] is None  # JSON safe


def test_performance_tracker_persists(db):
    with db.session() as s:
        s.add(_closed(6.0, "WIN", 3, 1.5))
        s.add(_closed(-4.0, "LOSS", 0, -1.0, ts=datetime(2026, 9, 2)))
        s.add(Signal(symbol="ETHUSDT", side="SHORT", entry_price=1, sl_price=1, tp1_price=1, tp2_price=1, tp3_price=1,
                     timestamp=datetime(2026, 9, 3), status="ACTIVE"))
    tracker = PerformanceTracker(db)
    stats = tracker.update()
    assert stats.total_signals == 3 and stats.active_signals == 1 and stats.closed_signals == 2
    latest = tracker.latest()
    assert latest["win_rate"] == pytest.approx(50.0)
    assert latest["total_pnl_pct"] == pytest.approx(2.0)
    assert latest["profit_factor"] == pytest.approx(1.5)
    assert latest["last_updated"] is not None
    # second update overwrites the same row
    tracker.update()
    with db.session() as s:
        from database import Performance
        assert s.query(Performance).count() == 1
    bd = tracker.breakdown()
    assert "BTCUSDT" in bd["by_symbol"] and bd["by_side"]["LONG"]["closed_signals"] == 2
    assert bd["by_symbol"]["ETHUSDT"]["active_signals"] == 1
    curve = tracker.equity_curve()
    assert [p["cumulative_pnl_pct"] for p in curve] == [6.0, 2.0]


def test_backtest_rows_are_excluded_from_live_stats(db):
    with db.session() as s:
        s.add(_closed(6.0, "WIN", 3, 1.5))
        bt = _closed(-4.0, "LOSS", 0, -1.0, ts=datetime(2026, 9, 2))
        bt.source = "backtest"
        s.add(bt)
    tracker = PerformanceTracker(db)
    stats = tracker.update()
    assert stats.closed_signals == 1 and stats.total_losses == 0 and stats.total_pnl_pct == pytest.approx(6.0)
    assert len(tracker.equity_curve()) == 1
