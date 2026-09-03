"""
Historical backtester.

Replays the exact production logic (indicators → SignalEngine → walk_candles
position model) over historical candles so the strategy can be evaluated and
parameters tuned before running live.

    python backtest.py --days 60                           # all configured pairs
    python backtest.py --days 90 --symbols BTCUSDT,ETHUSDT --min-conviction 60
    python backtest.py --days 60 --write-db                # persist results as source="backtest"
    DATA_SOURCE=synthetic python backtest.py --days 30     # offline

Signals are evaluated on the main-timeframe candles; exits are simulated on
the *same* timeframe candles (conservative: stop-first when a candle touches
both stop and target).  Only one open signal per symbol at a time, mirroring
the live risk rules.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, List, Optional

import pandas as pd

from config import Settings, settings
from data_collector import create_data_collector
from database import Database, Signal, SignalStatus, set_database
from indicators import calculate_all_indicators, min_candles_required
from performance_tracker import compute_stats
from signal_engine import SignalEngine
from signal_monitor import PositionState
from utils import setup_logging, timeframe_to_seconds

logger = logging.getLogger("backtest")


@dataclass
class BacktestTrade:
    symbol: str
    side: str
    entry_time: datetime
    entry_price: float
    sl_price: float
    tp1_price: float
    tp2_price: float
    tp3_price: float
    conviction: float
    conditions: List[str]
    status: str = SignalStatus.ACTIVE
    outcome: Optional[str] = None
    exit_time: Optional[datetime] = None
    exit_price: Optional[float] = None
    pnl_pct: float = 0.0
    pnl_r: float = 0.0
    tp_hits: int = 0
    max_favorable_pct: float = 0.0
    max_adverse_pct: float = 0.0
    htf_1h: str = "NEUTRAL"

    def to_signal(self) -> Signal:
        """Lightweight ORM-like object for compute_stats / DB persistence."""
        return Signal(
            symbol=self.symbol, side=self.side, timeframe="bt", entry_price=self.entry_price,
            sl_price=self.sl_price, current_sl=self.sl_price, tp1_price=self.tp1_price, tp2_price=self.tp2_price,
            tp3_price=self.tp3_price, timestamp=self.entry_time, candle_time=self.entry_time,
            status=self.status, outcome=self.outcome, profit_loss_pct=self.pnl_pct, profit_loss_r=self.pnl_r,
            conviction_score=self.conviction, closed_at=self.exit_time, exit_price=self.exit_price,
            tp_hits=self.tp_hits, max_favorable_pct=self.max_favorable_pct, max_adverse_pct=self.max_adverse_pct,
            conditions=",".join(self.conditions), htf_trend_1h=self.htf_1h, source="backtest",
        )


@dataclass
class BacktestResult:
    settings: Settings
    trades: List[BacktestTrade] = field(default_factory=list)
    candles_evaluated: int = 0
    candidates: int = 0

    def stats(self) -> dict:
        closed = [t.to_signal() for t in self.trades if t.status != SignalStatus.ACTIVE]
        return compute_stats(closed, active_count=sum(1 for t in self.trades if t.status == SignalStatus.ACTIVE)).to_dict()

    def by_symbol(self) -> Dict[str, dict]:
        out = {}
        for sym in sorted({t.symbol for t in self.trades}):
            closed = [t.to_signal() for t in self.trades if t.symbol == sym and t.status != SignalStatus.ACTIVE]
            out[sym] = compute_stats(closed).to_dict()
        return out


def _htf_slice(htf: pd.DataFrame, upto: datetime, tf: str) -> Optional[pd.DataFrame]:
    """Higher-timeframe rows whose candle *closed* at or before `upto` (no look-ahead)."""
    if htf is None or htf.empty:
        return None
    closes = htf["timestamp"] + timedelta(seconds=timeframe_to_seconds(tf))
    sub = htf[closes <= upto]
    return sub if len(sub) else None


def run_backtest_frames(cfg: Settings, frames: Dict[str, pd.DataFrame],
                        htf_frames: Optional[Dict[str, Dict[str, pd.DataFrame]]] = None,
                        warmup: Optional[int] = None) -> BacktestResult:
    """Backtest over pre-loaded raw OHLCV frames {symbol: df}. htf_frames = {symbol: {"1h": df, ...}}."""
    engine = SignalEngine(cfg)
    result = BacktestResult(settings=cfg)
    htf_frames = htf_frames or {}
    warmup = warmup or (min_candles_required(macd_slow=cfg.macd_slow, macd_signal=cfg.macd_signal,
                                             ema_periods=cfg.ema_periods, bb_period=cfg.bb_period) + 60)
    tf_seconds = timeframe_to_seconds(cfg.timeframe)

    for symbol, raw in frames.items():
        if raw is None or len(raw) <= warmup:
            logger.warning("%s: not enough history (%d candles)", symbol, 0 if raw is None else len(raw))
            continue
        df = calculate_all_indicators(
            raw, rsi_period=cfg.rsi_period, macd_fast=cfg.macd_fast, macd_slow=cfg.macd_slow,
            macd_signal=cfg.macd_signal, bb_period=cfg.bb_period, bb_std=cfg.bb_std, atr_period=cfg.atr_period,
            ema_periods=cfg.ema_periods, volume_avg_period=cfg.volume_avg_period,
        )
        htf_ind = {}
        for tf, hdf in (htf_frames.get(symbol) or {}).items():
            if hdf is not None and len(hdf) > 60:
                htf_ind[tf] = calculate_all_indicators(hdf, ema_periods=cfg.ema_periods)

        open_trade: Optional[BacktestTrade] = None
        open_state: Optional[PositionState] = None
        cooldown_until: Optional[datetime] = None
        start_idx = max(3, min(len(df) - 1, warmup - (len(raw) - len(df))))
        lookback = 400  # rows passed to the engine (enough for MACD lookback etc.)

        for i in range(start_idx, len(df)):
            row = df.iloc[i]
            candle_open = row["timestamp"].to_pydatetime()
            candle_close_time = candle_open + timedelta(seconds=tf_seconds)

            # 1) update the open position with this candle
            if open_trade is not None and open_state is not None:
                expires_at = open_trade.entry_time + timedelta(hours=cfg.signal_expiry_hours)
                if candle_close_time > expires_at:
                    open_state.expire(float(row.close), candle_close_time)
                else:
                    open_state.apply_candle(float(row.high), float(row.low), float(row.close), candle_close_time, cfg)
                if open_state.closed:
                    open_trade.status = open_state.status or SignalStatus.EXPIRED
                    open_trade.outcome = open_state.outcome()
                    open_trade.exit_time = open_state.closed_at
                    open_trade.exit_price = open_state.exit_price
                    open_trade.pnl_pct = round(open_state.realised_pct, 4)
                    open_trade.pnl_r = round(open_state.r_multiple(), 3)
                    open_trade.tp_hits = open_state.tp_hits
                    open_trade.max_favorable_pct = open_state.max_favorable_pct
                    open_trade.max_adverse_pct = open_state.max_adverse_pct
                    cooldown_until = candle_close_time + timedelta(minutes=cfg.signal_cooldown_minutes)
                    open_trade, open_state = None, None
                continue  # one signal per symbol at a time

            if cooldown_until is not None and candle_close_time < cooldown_until:
                continue

            # 2) evaluate this candle as the "latest closed candle"
            window = df.iloc[max(0, i - lookback + 1): i + 1]
            result.candles_evaluated += 1
            htf_now = {}
            for tf, hdf in htf_ind.items():
                sl = _htf_slice(hdf, candle_close_time, tf)
                if sl is not None:
                    htf_now[tf] = sl
            ev = engine.evaluate(symbol, window, htf_now)
            if ev.candidate is None:
                continue
            c = ev.candidate
            result.candidates += 1
            open_trade = BacktestTrade(
                symbol=symbol, side=c.side, entry_time=candle_close_time, entry_price=c.entry_price,
                sl_price=c.sl_price, tp1_price=c.tp1_price, tp2_price=c.tp2_price, tp3_price=c.tp3_price,
                conviction=c.conviction_score, conditions=list(c.conditions), htf_1h=c.htf_trend_1h,
            )
            open_state = PositionState(side=c.side, entry=c.entry_price, sl=c.sl_price,
                                       tps=(c.tp1_price, c.tp2_price, c.tp3_price))
            result.trades.append(open_trade)

        if open_trade is not None and open_state is not None:
            # still open at the end of the data: record unrealised state
            open_trade.tp_hits = open_state.tp_hits
            open_trade.max_favorable_pct = open_state.max_favorable_pct
            open_trade.max_adverse_pct = open_state.max_adverse_pct

    result.trades.sort(key=lambda t: t.entry_time)
    return result


async def load_history(cfg: Settings, symbols: List[str], days: int) -> (Dict[str, pd.DataFrame], Dict[str, Dict[str, pd.DataFrame]]):
    collector = create_data_collector(cfg)
    frames: Dict[str, pd.DataFrame] = {}
    htf: Dict[str, Dict[str, pd.DataFrame]] = {}
    try:
        await collector.start(symbols)
        since = datetime.utcnow() - timedelta(days=days)
        for symbol in symbols:
            frames[symbol] = await _fetch_range(collector, symbol, cfg.timeframe, since)
            htf[symbol] = {}
            for tf in cfg.confirmation_timeframes:
                htf[symbol][tf] = await _fetch_range(collector, symbol, tf, since - timedelta(days=15))
            logger.info("%s: %d %s candles loaded", symbol, len(frames[symbol]), cfg.timeframe)
    finally:
        await collector.close()
    return frames, htf


async def _fetch_range(collector, symbol: str, timeframe: str, since: datetime) -> pd.DataFrame:
    parts = []
    cursor = since
    tf = timedelta(seconds=timeframe_to_seconds(timeframe))
    for _ in range(200):
        df = await collector.fetch_candles_since(symbol, timeframe, cursor, limit=1000)
        if df is None or df.empty:
            break
        parts.append(df)
        last = df["timestamp"].iloc[-1].to_pydatetime()
        if len(df) < 1000 or last + tf >= datetime.utcnow():
            break
        cursor = last + tf
    if not parts:
        return pd.DataFrame(columns=["timestamp", "open", "high", "low", "close", "volume"])
    out = pd.concat(parts, ignore_index=True).drop_duplicates("timestamp").sort_values("timestamp")
    # closed candles only
    out = out[out["timestamp"] + tf <= datetime.utcnow()]
    return out.reset_index(drop=True)


def print_report(result: BacktestResult, days: int) -> None:
    st = result.stats()
    pf = st["profit_factor"]
    print("\n" + "=" * 72)
    print(f" BACKTEST — {days} days · {result.settings.timeframe} · {', '.join(sorted({t.symbol for t in result.trades}) or result.settings.trading_pairs)}")
    print("=" * 72)
    print(f" Candles evaluated : {result.candles_evaluated}")
    print(f" Signals           : {len(result.trades)}  (closed {st['closed_signals']}, still open {st['active_signals']})")
    print(f" Wins / Losses / BE: {st['total_wins']} / {st['total_losses']} / {st['total_breakeven']}")
    print(f" Win rate          : {st['win_rate']:.1f}%")
    print(f" Total PnL         : {st['total_pnl_pct']:+.2f}%  (unleveraged, scale-out thirds)")
    print(f" Profit factor     : {'∞' if pf is None else f'{pf:.2f}'}")
    print(f" Expectancy        : {st['expectancy']:+.3f}% per trade   avg R: {st['avg_r']:+.2f}")
    print(f" Avg win / loss    : {st['avg_win_pct']:+.2f}% / -{st['avg_loss_pct']:.2f}%")
    print(f" Max drawdown      : {st['max_drawdown_pct']:.2f}%")
    print(f" TP1/TP2/TP3 hit   : {st['tp1_hit_rate']:.0f}% / {st['tp2_hit_rate']:.0f}% / {st['tp3_hit_rate']:.0f}%")
    print(f" Avg duration      : {st['avg_duration_minutes'] / 60:.1f} h")
    print("-" * 72)
    print(f" {'Symbol':<10}{'Trades':>7}{'WinRate':>9}{'PnL%':>10}{'PF':>7}{'Exp%':>8}")
    for sym, s in result.by_symbol().items():
        pf_s = "∞" if s["profit_factor"] is None else f"{s['profit_factor']:.2f}"
        print(f" {sym:<10}{s['closed_signals']:>7}{s['win_rate']:>8.1f}%{s['total_pnl_pct']:>+10.2f}{pf_s:>7}{s['expectancy']:>+8.2f}")
    print("-" * 72)
    for t in result.trades[-15:]:
        print(f" {t.entry_time:%Y-%m-%d %H:%M} {t.symbol:<9}{t.side:<6}{t.entry_price:>12.6g} → "
              f"{(t.exit_price or 0):>12.6g}  {t.status:<8}{(t.outcome or '-'):<9}{t.pnl_pct:>+7.2f}%  TP{t.tp_hits}  conv {t.conviction:.0f}")
    print("=" * 72 + "\n")


def write_to_db(result: BacktestResult, cfg: Settings, source: str = "backtest") -> int:
    """Persist closed backtest trades. Rows with the same `source` are replaced.

    source="backtest" (default) keeps them out of the live statistics; any other
    value (e.g. "synthetic" for a demo database) makes them count as live history.
    """
    db = Database(cfg.database_url)
    db.create_tables()
    set_database(db)
    n = 0
    with db.session() as session:
        session.query(Signal).filter(Signal.source == source).delete(synchronize_session=False)
        for t in result.trades:
            if t.status == SignalStatus.ACTIVE:
                continue
            s = t.to_signal()
            s.timeframe = cfg.timeframe
            s.source = source
            session.add(s)
            n += 1
    db.dispose()
    if source != "backtest":
        from performance_tracker import PerformanceTracker
        db2 = Database(cfg.database_url)
        PerformanceTracker(db2).update()
        db2.dispose()
    return n


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Backtest the signal strategy")
    parser.add_argument("--days", type=int, default=60)
    parser.add_argument("--symbols", type=str, default=None, help="comma separated, default: configured pairs")
    parser.add_argument("--min-conviction", type=float, default=None)
    parser.add_argument("--min-conditions", type=int, default=None)
    parser.add_argument("--sl-atr", type=float, default=None)
    parser.add_argument("--require-htf", action="store_true")
    parser.add_argument("--write-db", action="store_true", help="store closed trades in the DB (source=backtest)")
    parser.add_argument("--source", type=str, default="backtest",
                        help="source label for --write-db (use 'synthetic' to seed a demo database)")
    parser.add_argument("--json", action="store_true", help="print JSON instead of the text report")
    args = parser.parse_args(argv)

    setup_logging(settings.log_level)
    cfg = settings
    overrides = {}
    if args.min_conviction is not None:
        overrides["min_conviction"] = args.min_conviction
    if args.min_conditions is not None:
        overrides["min_conditions"] = args.min_conditions
    if args.sl_atr is not None:
        overrides["sl_atr_mult"] = args.sl_atr
    if args.require_htf:
        overrides["require_htf_confirmation"] = True
    if overrides:
        cfg = cfg.with_overrides(**overrides)
    symbols = [s.strip().upper() for s in args.symbols.split(",")] if args.symbols else list(cfg.trading_pairs)

    frames, htf = asyncio.run(load_history(cfg, symbols, args.days))
    result = run_backtest_frames(cfg, frames, htf)
    if args.json:
        print(json.dumps({"stats": result.stats(), "by_symbol": result.by_symbol(),
                          "trades": [t.__dict__ for t in result.trades]}, indent=2, default=str))
    else:
        print_report(result, args.days)
    if args.write_db:
        n = write_to_db(result, cfg, source=args.source)
        print(f"Stored {n} backtest trades in the database (source='{args.source}').")
    return 0


if __name__ == "__main__":
    sys.exit(main())
