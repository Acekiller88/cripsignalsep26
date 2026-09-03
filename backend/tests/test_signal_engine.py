from datetime import datetime, timedelta

import pandas as pd
import pytest

from database import Side, SignalStatus
from indicators import calculate_all_indicators
from signal_engine import SignalEngine
from tests.conftest import make_ohlcv


def _frame(rows: int = 40, close: float = 100.0, atr: float = 2.0, rsi: float = 50.0,
           macd: float = 0.0, macd_signal: float = 0.0, bb_lower: float = 95.0, bb_upper: float = 105.0) -> pd.DataFrame:
    """Hand-built indicator frame where the last row is fully controlled."""
    now = datetime(2026, 9, 3, 12, 0)
    df = pd.DataFrame({
        "timestamp": [now - timedelta(minutes=15 * (rows - i)) for i in range(rows)],
        "open": close, "high": close + 1, "low": close - 1, "close": close, "volume": 1000.0,
        "rsi": 50.0, "macd": -1.0, "macd_signal": -1.0, "macd_hist": 0.0,
        "bb_upper": bb_upper, "bb_middle": (bb_upper + bb_lower) / 2, "bb_lower": bb_lower,
        "atr": atr, "ema_9": close, "ema_21": close, "ema_50": close, "adx": 20.0,
        "volume_avg": 1000.0, "volume_ratio": 1.0,
    })
    df.loc[df.index[-1], ["rsi", "macd", "macd_signal"]] = [rsi, macd, macd_signal]
    return df


def test_no_signal_when_conditions_not_met(settings):
    eng = SignalEngine(settings)
    ev = eng.evaluate("BTCUSDT", _frame())
    assert ev.candidate is None
    assert ev.rejected_reason == "conditions_not_met"
    assert ev.long_score == 0 and ev.short_score == 0


def test_long_signal_rsi_and_bb(settings):
    eng = SignalEngine(settings)
    df = _frame(close=94.0, rsi=25.0, bb_lower=95.0)
    ev = eng.evaluate("BTCUSDT", df)
    assert ev.candidate is not None
    c = ev.candidate
    assert c.side == Side.LONG
    assert set(c.conditions) == {"rsi_oversold", "below_bb_lower"}
    # ATR based levels: SL 2 ATR, TP 2/4/6 ATR
    assert c.entry_price == 94.0
    assert c.sl_price == pytest.approx(94.0 - 4.0)
    assert c.tp1_price == pytest.approx(94.0 + 4.0)
    assert c.tp2_price == pytest.approx(94.0 + 8.0)
    assert c.tp3_price == pytest.approx(94.0 + 12.0)
    assert c.risk_reward == pytest.approx(3.0)
    assert c.entry_low < c.entry_price < c.entry_high
    assert 50 <= c.conviction_score <= 100


def test_short_signal_rsi_and_bb(settings):
    eng = SignalEngine(settings)
    df = _frame(close=106.0, rsi=75.0, bb_upper=105.0)
    c = eng.evaluate("ETHUSDT", df).candidate
    assert c is not None and c.side == Side.SHORT
    assert c.sl_price == pytest.approx(106.0 + 4.0)
    assert c.tp1_price == pytest.approx(106.0 - 4.0)
    assert c.tp3_price == pytest.approx(106.0 - 12.0)
    assert c.risk_reward == pytest.approx(3.0)


def test_macd_crossover_detection(settings):
    eng = SignalEngine(settings)
    # bullish cross on the last candle: prev macd below signal, now above; RSI oversold gives the 2nd condition
    df = _frame(rsi=28.0, macd=0.5, macd_signal=0.0)
    df.loc[df.index[-2], ["macd", "macd_signal"]] = [-0.5, 0.0]
    ev = eng.evaluate("SOLUSDT", df)
    assert ev.long_conditions["macd_bullish_cross"] is True
    assert ev.candidate is not None and ev.candidate.side == Side.LONG

    # macd above signal for a long time (no recent cross) -> not a crossover
    df2 = _frame(rsi=28.0, macd=0.5, macd_signal=0.0)
    df2["macd"] = 0.5
    df2["macd_signal"] = 0.0
    ev2 = eng.evaluate("SOLUSDT", df2)
    assert ev2.long_conditions["macd_bullish_cross"] is False
    assert ev2.candidate is None


def test_macd_cross_lookback_zero_means_state_only(settings):
    eng = SignalEngine(settings.with_overrides(macd_cross_lookback=0))
    df = _frame(rsi=28.0, macd=0.5, macd_signal=0.0)
    df["macd"] = 0.5
    df["macd_signal"] = 0.0
    assert eng.evaluate("X", df).long_conditions["macd_bullish_cross"] is True


def test_single_condition_is_not_enough(settings):
    eng = SignalEngine(settings)
    assert eng.evaluate("X", _frame(rsi=20.0)).candidate is None
    assert eng.evaluate("X", _frame(close=90.0, bb_lower=95.0)).candidate is None


def test_min_conditions_three(settings):
    eng = SignalEngine(settings.with_overrides(min_conditions=3))
    df = _frame(close=94.0, rsi=25.0, bb_lower=95.0)
    assert eng.evaluate("X", df).candidate is None
    df.loc[df.index[-1], ["macd", "macd_signal"]] = [0.5, 0.0]
    df.loc[df.index[-2], ["macd", "macd_signal"]] = [-0.5, 0.0]
    c = eng.evaluate("X", df).candidate
    assert c is not None and len(c.conditions) == 3
    assert c.conviction_score >= 75


def test_htf_confirmation_affects_conviction_and_can_block(settings):
    eng = SignalEngine(settings.with_overrides(min_conviction=0))
    df = _frame(close=94.0, rsi=25.0, bb_lower=95.0)
    bullish = pd.DataFrame([{"ema_9": 3, "ema_21": 2.5, "ema_50": 2, "close": 3.1}])
    bearish = pd.DataFrame([{"ema_9": 1, "ema_21": 1.5, "ema_50": 2, "close": 0.9}])
    with_bull = eng.evaluate("X", df, {"1h": bullish, "4h": bullish}).candidate
    with_bear = eng.evaluate("X", df, {"1h": bearish, "4h": bearish}).candidate
    assert with_bull.conviction_score > with_bear.conviction_score
    assert with_bull.htf_trend_1h == "BULLISH" and with_bear.htf_trend_4h == "BEARISH"
    # 2/3 setup against both higher timeframes scores 40 -> rejected once the threshold is above that
    assert with_bear.conviction_score == pytest.approx(40.0)
    assert SignalEngine(settings.with_overrides(min_conviction=45)).evaluate("X", df, {"1h": bearish, "4h": bearish}).candidate is None

    strict = SignalEngine(settings.with_overrides(require_htf_confirmation=True))
    assert strict.evaluate("X", df, {"1h": bearish}).candidate is None
    assert strict.evaluate("X", df, {"1h": bullish}).candidate is not None


def test_min_conviction_filter(settings):
    eng = SignalEngine(settings.with_overrides(min_conviction=90))
    df = _frame(close=94.0, rsi=25.0, bb_lower=95.0)
    ev = eng.evaluate("X", df)
    assert ev.candidate is None
    assert ev.rejected_reason.startswith("conviction_")


def test_invalid_atr_rejected(settings):
    eng = SignalEngine(settings)
    df = _frame(close=94.0, rsi=25.0, bb_lower=95.0, atr=0.0)
    assert eng.evaluate("X", df).rejected_reason == "invalid_atr_or_price"


def test_to_model_roundtrip(settings):
    eng = SignalEngine(settings)
    c = eng.evaluate("XRPUSDT", _frame(close=94.0, rsi=25.0, bb_lower=95.0)).candidate
    m = eng.to_model(c, source="test")
    assert m.symbol == "XRPUSDT" and m.side == "LONG" and m.status == SignalStatus.ACTIVE
    assert m.current_sl == m.sl_price and m.tp_hits == 0
    assert m.condition_list() == c.conditions
    assert m.source == "test"
    assert m.timestamp is not None


def test_engine_on_real_indicator_pipeline(settings):
    """Run the engine over a random walk and make sure every emitted candidate is internally consistent."""
    eng = SignalEngine(settings)
    df = calculate_all_indicators(make_ohlcv(600, seed=11, vol=0.01))
    found = 0
    for i in range(50, len(df)):
        c = eng.evaluate("BTCUSDT", df.iloc[: i + 1]).candidate
        if c is None:
            continue
        found += 1
        assert len(c.conditions) >= 2
        if c.side == Side.LONG:
            assert c.sl_price < c.entry_price < c.tp1_price < c.tp2_price < c.tp3_price
        else:
            assert c.tp3_price < c.tp2_price < c.tp1_price < c.entry_price < c.sl_price
        assert c.risk_reward == pytest.approx(3.0)
    assert found > 0
