import numpy as np
import pandas as pd
import pytest

from indicators import (
    atr,
    bollinger_bands,
    calculate_all_indicators,
    ema,
    macd,
    min_candles_required,
    rsi,
    trend_label,
)
from tests.conftest import make_ohlcv

# Classic Wilder RSI worked example (J. Welles Wilder, 1978)
WILDER_CLOSES = [
    44.34, 44.09, 44.15, 43.61, 44.33, 44.83, 45.10, 45.42, 45.84, 46.08, 45.89, 46.03, 45.61, 46.28, 46.28,
    46.00, 46.03, 46.41, 46.22, 45.64, 46.21, 46.25, 45.71, 46.45, 45.78, 45.35, 44.03, 44.18, 44.22, 44.57,
    43.42, 42.66, 43.13,
]


def test_rsi_matches_wilder_reference():
    r = rsi(pd.Series(WILDER_CLOSES), 14)
    assert r.iloc[:14].isna().all()
    assert r.iloc[14] == pytest.approx(70.46, abs=0.15)
    assert r.iloc[15] == pytest.approx(66.25, abs=0.15)
    assert r.iloc[-1] == pytest.approx(37.77, abs=0.5)


def test_rsi_extremes():
    up = pd.Series(np.linspace(1, 100, 60))
    assert rsi(up, 14).iloc[-1] == pytest.approx(100.0)
    down = pd.Series(np.linspace(100, 1, 60))
    assert rsi(down, 14).iloc[-1] == pytest.approx(0.0)
    flat = pd.Series(np.full(60, 50.0))
    assert rsi(flat, 14).iloc[-1] == pytest.approx(50.0)


def test_ema_converges_to_pandas_ewm():
    s = pd.Series(np.random.default_rng(1).normal(100, 1, 400).cumsum())
    ours = ema(s, 21)
    ref = s.ewm(span=21, adjust=False).mean()
    assert ours.iloc[:20].isna().all()
    assert np.allclose(ours.iloc[-50:], ref.iloc[-50:], atol=1e-6)


def test_macd_relationship():
    s = pd.Series(np.random.default_rng(2).normal(0, 1, 300).cumsum() + 500)
    m = macd(s, 12, 26, 9)
    valid = m.dropna()
    assert len(valid) > 200
    assert np.allclose(valid["macd_hist"], valid["macd"] - valid["macd_signal"])
    assert np.allclose(m["macd"].dropna(), (ema(s, 12) - ema(s, 26)).dropna())


def test_bollinger_bands_manual():
    s = pd.Series(np.random.default_rng(3).normal(0, 1, 100).cumsum() + 50)
    bb = bollinger_bands(s, 20, 2.0)
    window = s.iloc[80:100]
    assert bb["bb_middle"].iloc[99] == pytest.approx(window.mean())
    assert bb["bb_upper"].iloc[99] == pytest.approx(window.mean() + 2 * window.std(ddof=0))
    assert bb["bb_lower"].iloc[99] == pytest.approx(window.mean() - 2 * window.std(ddof=0))
    assert (bb["bb_upper"].dropna() >= bb["bb_lower"].dropna()).all()


def test_atr_constant_range():
    n = 60
    high = pd.Series(np.full(n, 101.0))
    low = pd.Series(np.full(n, 99.0))
    close = pd.Series(np.full(n, 100.0))
    assert atr(high, low, close, 14).iloc[-1] == pytest.approx(2.0)


def test_atr_includes_gaps():
    # gap up: previous close 100, today's low 105 -> TR must use |low - prev_close| = 5, not high-low = 1
    high = pd.Series([101.0] * 15 + [106.0])
    low = pd.Series([99.0] * 15 + [105.0])
    close = pd.Series([100.0] * 15 + [105.5])
    a = atr(high, low, close, 14)
    assert a.iloc[-1] > 2.0


def test_calculate_all_indicators_columns_and_dropna():
    df = make_ohlcv(300)
    out = calculate_all_indicators(df)
    expected = {"rsi", "macd", "macd_signal", "macd_hist", "bb_upper", "bb_middle", "bb_lower", "atr", "ema_9",
                "ema_21", "ema_50", "volume_avg", "volume_ratio", "adx", "atr_pct", "bb_width"}
    assert expected.issubset(out.columns)
    assert len(out) < len(df)
    assert out[["rsi", "macd", "macd_signal", "bb_upper", "bb_lower", "atr", "ema_50"]].notna().all().all()
    # timestamps preserved & in order
    assert out["timestamp"].is_monotonic_increasing
    assert out["timestamp"].iloc[-1] == df["timestamp"].iloc[-1]


def test_calculate_all_indicators_missing_column():
    with pytest.raises(ValueError):
        calculate_all_indicators(pd.DataFrame({"close": [1, 2, 3]}))


def test_min_candles_required():
    assert min_candles_required() >= 50
    assert min_candles_required(ema_periods=(200,)) >= 200


def test_trend_label():
    assert trend_label(pd.Series({"ema_9": 3, "ema_21": 2.5, "ema_50": 2, "close": 3.1})) == "BULLISH"
    assert trend_label(pd.Series({"ema_9": 1, "ema_21": 1.5, "ema_50": 2, "close": 0.9})) == "BEARISH"
    assert trend_label(pd.Series({"ema_9": 1, "ema_21": 1.5, "ema_50": 2, "close": 2.1})) == "NEUTRAL"
    assert trend_label(pd.Series({"close": 1})) == "NEUTRAL"
