"""
Technical indicators implemented with pandas/numpy only.

Why not TA-Lib / pandas-ta?  TA-Lib needs a C library that is painful to build
in slim Docker images and pandas-ta 0.3.x is incompatible with numpy 2.x.  The
formulas below follow the classic (Wilder / TA-Lib) definitions and are
unit-tested against hand-computed references.

All functions accept a DataFrame with columns
    timestamp, open, high, low, close, volume
and return the same DataFrame with indicator columns added.
"""
from __future__ import annotations

from typing import Iterable, Optional

import numpy as np
import pandas as pd

REQUIRED_COLUMNS = ("open", "high", "low", "close", "volume")


# ---------------------------------------------------------------------------
# Building blocks
# ---------------------------------------------------------------------------
def ema(series: pd.Series, period: int) -> pd.Series:
    """Exponential moving average seeded with the SMA of the first `period` values (TA-Lib style)."""
    values = series.astype(float).to_numpy()
    out = np.full(len(values), np.nan)
    if len(values) < period:
        return pd.Series(out, index=series.index)
    alpha = 2.0 / (period + 1.0)
    out[period - 1] = np.nanmean(values[:period])
    for i in range(period, len(values)):
        out[i] = alpha * values[i] + (1.0 - alpha) * out[i - 1]
    return pd.Series(out, index=series.index)


def rma(series: pd.Series, period: int) -> pd.Series:
    """Wilder's smoothing (used by RSI and ATR)."""
    values = series.astype(float).to_numpy()
    out = np.full(len(values), np.nan)
    if len(values) < period:
        return pd.Series(out, index=series.index)
    out[period - 1] = np.nanmean(values[:period])
    alpha = 1.0 / period
    for i in range(period, len(values)):
        out[i] = alpha * values[i] + (1.0 - alpha) * out[i - 1]
    return pd.Series(out, index=series.index)


def sma(series: pd.Series, period: int) -> pd.Series:
    return series.astype(float).rolling(window=period, min_periods=period).mean()


# ---------------------------------------------------------------------------
# Indicators
# ---------------------------------------------------------------------------
def rsi(close: pd.Series, period: int = 14) -> pd.Series:
    """Relative Strength Index (Wilder)."""
    delta = close.astype(float).diff()
    gain = delta.clip(lower=0.0)
    loss = (-delta).clip(lower=0.0)
    # first value of diff is NaN: treat as 0 so the seed window covers `period` changes
    gain.iloc[0] = 0.0
    loss.iloc[0] = 0.0
    avg_gain = rma(gain.iloc[1:], period)
    avg_loss = rma(loss.iloc[1:], period)
    rs = avg_gain / avg_loss.replace(0.0, np.nan)
    out = 100.0 - (100.0 / (1.0 + rs))
    # where avg_loss == 0 and avg_gain > 0 -> RSI 100; both 0 -> 50
    out = out.where(avg_loss != 0.0, np.where(avg_gain > 0.0, 100.0, 50.0))
    out = out.where(~avg_gain.isna())  # keep NaN during warm-up
    return out.reindex(close.index)


def macd(close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> pd.DataFrame:
    """MACD line, signal line and histogram."""
    ema_fast = ema(close, fast)
    ema_slow = ema(close, slow)
    macd_line = ema_fast - ema_slow
    # signal line = EMA of the MACD line, computed on the valid (non-NaN) region
    valid = macd_line.dropna()
    signal_line = ema(valid, signal).reindex(close.index)
    hist = macd_line - signal_line
    return pd.DataFrame({"macd": macd_line, "macd_signal": signal_line, "macd_hist": hist}, index=close.index)


def bollinger_bands(close: pd.Series, period: int = 20, std_mult: float = 2.0) -> pd.DataFrame:
    """Bollinger Bands using population standard deviation (TA-Lib/pandas-ta default)."""
    middle = sma(close, period)
    std = close.astype(float).rolling(window=period, min_periods=period).std(ddof=0)
    upper = middle + std_mult * std
    lower = middle - std_mult * std
    width = (upper - lower) / middle.replace(0.0, np.nan) * 100.0
    pct_b = (close - lower) / (upper - lower).replace(0.0, np.nan)
    return pd.DataFrame(
        {"bb_upper": upper, "bb_middle": middle, "bb_lower": lower, "bb_width": width, "bb_pct": pct_b},
        index=close.index,
    )


def true_range(high: pd.Series, low: pd.Series, close: pd.Series) -> pd.Series:
    prev_close = close.shift(1)
    tr = pd.concat(
        [(high - low), (high - prev_close).abs(), (low - prev_close).abs()], axis=1
    ).max(axis=1)
    tr.iloc[0] = float(high.iloc[0] - low.iloc[0])
    return tr


def atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    """Average True Range (Wilder smoothing)."""
    tr = true_range(high.astype(float), low.astype(float), close.astype(float))
    return rma(tr, period)


def adx(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    """Average Directional Index – used only as a trend-strength hint in conviction scoring."""
    high = high.astype(float)
    low = low.astype(float)
    close = close.astype(float)
    up_move = high.diff()
    down_move = -low.diff()
    plus_dm = pd.Series(np.where((up_move > down_move) & (up_move > 0), up_move, 0.0), index=high.index)
    minus_dm = pd.Series(np.where((down_move > up_move) & (down_move > 0), down_move, 0.0), index=high.index)
    tr = true_range(high, low, close)
    atr_ = rma(tr, period)
    plus_di = 100.0 * rma(plus_dm, period) / atr_.replace(0.0, np.nan)
    minus_di = 100.0 * rma(minus_dm, period) / atr_.replace(0.0, np.nan)
    dx = 100.0 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0.0, np.nan)
    dx_valid = dx.dropna()
    return rma(dx_valid, period).reindex(high.index)


# ---------------------------------------------------------------------------
# Aggregate
# ---------------------------------------------------------------------------
def calculate_all_indicators(
    df: pd.DataFrame,
    *,
    rsi_period: int = 14,
    macd_fast: int = 12,
    macd_slow: int = 26,
    macd_signal: int = 9,
    bb_period: int = 20,
    bb_std: float = 2.0,
    atr_period: int = 14,
    ema_periods: Iterable[int] = (9, 21, 50),
    volume_avg_period: int = 20,
    dropna: bool = True,
) -> pd.DataFrame:
    """Compute every indicator the strategy needs and append them as columns.

    With `dropna=True` (default) the warm-up rows containing NaN indicator
    values are removed, so `df.iloc[-1]` is always a fully-populated candle.
    """
    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"DataFrame is missing required columns: {missing}")

    out = df.copy()
    for col in REQUIRED_COLUMNS:
        out[col] = out[col].astype(float)

    close = out["close"]
    out["rsi"] = rsi(close, rsi_period)

    macd_df = macd(close, macd_fast, macd_slow, macd_signal)
    out["macd"] = macd_df["macd"]
    out["macd_signal"] = macd_df["macd_signal"]
    out["macd_hist"] = macd_df["macd_hist"]

    bb = bollinger_bands(close, bb_period, bb_std)
    for col in bb.columns:
        out[col] = bb[col]

    out["atr"] = atr(out["high"], out["low"], close, atr_period)
    out["atr_pct"] = out["atr"] / close * 100.0

    for period in ema_periods:
        out[f"ema_{period}"] = ema(close, period)

    out["adx"] = adx(out["high"], out["low"], close, 14)

    out["volume_avg"] = sma(out["volume"], volume_avg_period)
    out["volume_ratio"] = out["volume"] / out["volume_avg"].replace(0.0, np.nan)

    if dropna:
        core = ["rsi", "macd", "macd_signal", "bb_upper", "bb_lower", "atr", "volume_avg"] + [
            f"ema_{p}" for p in ema_periods
        ]
        out = out.dropna(subset=core)
    return out.reset_index(drop=True)


def min_candles_required(
    *, macd_slow: int = 26, macd_signal: int = 9, ema_periods: Iterable[int] = (9, 21, 50), bb_period: int = 20
) -> int:
    """Smallest number of candles that yields at least a couple of fully populated rows."""
    return max(macd_slow + macd_signal, max(ema_periods), bb_period) + 5


def trend_label(row: pd.Series) -> str:
    """Classify trend from EMA alignment: BULLISH / BEARISH / NEUTRAL."""
    try:
        e9, e21, e50, close = row["ema_9"], row["ema_21"], row["ema_50"], row["close"]
    except KeyError:
        return "NEUTRAL"
    if any(pd.isna(v) for v in (e9, e21, e50, close)):
        return "NEUTRAL"
    if close > e50 and e21 > e50:
        return "BULLISH"
    if close < e50 and e21 < e50:
        return "BEARISH"
    return "NEUTRAL"


def latest_snapshot(df: pd.DataFrame) -> Optional[dict]:
    """Small dict of the latest indicator values (for the API)."""
    if df is None or df.empty:
        return None
    row = df.iloc[-1]
    keys = [
        "timestamp", "open", "high", "low", "close", "volume", "rsi", "macd", "macd_signal", "macd_hist",
        "bb_upper", "bb_middle", "bb_lower", "bb_width", "atr", "atr_pct", "ema_9", "ema_21", "ema_50",
        "adx", "volume_avg", "volume_ratio",
    ]
    snap = {}
    for k in keys:
        if k in row.index:
            v = row[k]
            if isinstance(v, pd.Timestamp):
                v = v.isoformat()
            elif isinstance(v, (np.floating, float)):
                v = None if pd.isna(v) else float(v)
            snap[k] = v
    snap["trend"] = trend_label(row)
    return snap
