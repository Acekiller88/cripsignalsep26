"""
Signal generation engine.

Strategy (per closed candle of the main timeframe):

    LONG  – at least `min_conditions` of:
              1. RSI < oversold (30)
              2. MACD line crossed above the signal line (within the last N candles)
              3. Close below the lower Bollinger Band
    SHORT – at least `min_conditions` of:
              1. RSI > overbought (70)
              2. MACD line crossed below the signal line (within the last N candles)
              3. Close above the upper Bollinger Band

Levels are ATR based (defaults):  SL = 2 ATR, TP1/2/3 = 2/4/6 ATR  →  R:R 1:3 at TP3.

The engine is *pure*: `evaluate()` returns a `SignalCandidate` (or None) and
never touches the database or the network, which keeps it trivially testable.
`SignalEngine.to_model()` converts a candidate into the ORM `Signal` object.
"""
from __future__ import annotations

import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Dict, List, Optional

import pandas as pd

from config import Settings
from database import Side, Signal, SignalStatus
from indicators import trend_label
from utils import fmt_price, utcnow

logger = logging.getLogger("signals")


@dataclass
class SignalCandidate:
    symbol: str
    side: str
    timeframe: str
    entry_price: float
    entry_low: float
    entry_high: float
    sl_price: float
    tp1_price: float
    tp2_price: float
    tp3_price: float
    risk_reward: float
    conviction_score: float
    candle_time: datetime
    atr: float
    rsi: float
    macd: float
    macd_signal: float
    bb_upper: float
    bb_lower: float
    volume_ratio: Optional[float]
    htf_trend_1h: str
    htf_trend_4h: str
    conditions: List[str] = field(default_factory=list)
    reasons: List[str] = field(default_factory=list)
    score_breakdown: Dict[str, float] = field(default_factory=dict)

    @property
    def sl_pct(self) -> float:
        return abs(self.entry_price - self.sl_price) / self.entry_price * 100.0

    def to_dict(self) -> dict:
        d = asdict(self)
        d["candle_time"] = self.candle_time.isoformat()
        return d


@dataclass
class Evaluation:
    """Full diagnostic output of one evaluation (useful for the API / debugging)."""
    symbol: str
    candle_time: Optional[datetime]
    long_conditions: Dict[str, bool]
    short_conditions: Dict[str, bool]
    long_score: int
    short_score: int
    candidate: Optional[SignalCandidate]
    rejected_reason: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "candle_time": self.candle_time.isoformat() if self.candle_time else None,
            "long_conditions": self.long_conditions,
            "short_conditions": self.short_conditions,
            "long_score": self.long_score,
            "short_score": self.short_score,
            "candidate": self.candidate.to_dict() if self.candidate else None,
            "rejected_reason": self.rejected_reason,
        }


class SignalEngine:
    def __init__(self, settings: Settings):
        self.s = settings

    # ------------------------------------------------------------------
    # Condition helpers
    # ------------------------------------------------------------------
    def _macd_cross(self, df: pd.DataFrame, bullish: bool) -> bool:
        """MACD crossover in the requested direction within the lookback window.

        lookback == 0 → only require the MACD line to be on the right side of the signal line.
        lookback >= 1 → the line must be on the right side *and* have crossed within the last N candles.
        """
        macd = df["macd"].to_numpy()
        sig = df["macd_signal"].to_numpy()
        if len(macd) < 2:
            return False
        above_now = macd[-1] > sig[-1]
        if bullish != above_now:
            return False
        lookback = max(0, int(self.s.macd_cross_lookback))
        if lookback == 0:
            return True
        n = min(lookback, len(macd) - 1)
        for k in range(1, n + 1):
            prev_above = macd[-1 - k] > sig[-1 - k]
            if prev_above != above_now:
                return True
        return False

    def conditions(self, df: pd.DataFrame) -> Dict[str, Dict[str, bool]]:
        latest = df.iloc[-1]
        long_c = {
            "rsi_oversold": bool(latest["rsi"] < self.s.rsi_oversold),
            "macd_bullish_cross": self._macd_cross(df, bullish=True),
            "below_bb_lower": bool(latest["close"] < latest["bb_lower"]),
        }
        short_c = {
            "rsi_overbought": bool(latest["rsi"] > self.s.rsi_overbought),
            "macd_bearish_cross": self._macd_cross(df, bullish=False),
            "above_bb_upper": bool(latest["close"] > latest["bb_upper"]),
        }
        return {"long": long_c, "short": short_c}

    # ------------------------------------------------------------------
    # Conviction score
    # ------------------------------------------------------------------
    def _conviction(self, side: str, n_conditions: int, latest: pd.Series, prev: pd.Series,
                    htf_1h: str, htf_4h: str) -> (float, Dict[str, float]):
        breakdown: Dict[str, float] = {}
        base = 55.0 if n_conditions == 2 else 75.0 if n_conditions >= 3 else 30.0
        breakdown["conditions"] = base
        score = base

        want = "BULLISH" if side == Side.LONG else "BEARISH"
        against = "BEARISH" if side == Side.LONG else "BULLISH"
        for label, trend, bonus in (("htf_1h", htf_1h, 10.0), ("htf_4h", htf_4h, 5.0)):
            if trend == want:
                breakdown[label] = bonus
            elif trend == against:
                breakdown[label] = -bonus
            else:
                breakdown[label] = 0.0
            score += breakdown[label]

        vol_ratio = latest.get("volume_ratio")
        if vol_ratio is not None and not pd.isna(vol_ratio) and vol_ratio >= self.s.volume_spike_multiplier:
            breakdown["volume_spike"] = 5.0
            score += 5.0

        rsi = float(latest["rsi"])
        if (side == Side.LONG and rsi < self.s.rsi_oversold - 10) or (
            side == Side.SHORT and rsi > self.s.rsi_overbought + 10
        ):
            breakdown["rsi_extreme"] = 5.0
            score += 5.0

        # Momentum turning in our favour on the trigger candle
        rsi_prev = float(prev["rsi"])
        if (side == Side.LONG and rsi > rsi_prev) or (side == Side.SHORT and rsi < rsi_prev):
            breakdown["rsi_turning"] = 3.0
            score += 3.0
        close, open_ = float(latest["close"]), float(latest["open"])
        if (side == Side.LONG and close > open_) or (side == Side.SHORT and close < open_):
            breakdown["candle_confirms"] = 3.0
            score += 3.0

        # A strong trend (ADX) against a mean-reversion trade is a warning sign
        adx = latest.get("adx")
        if adx is not None and not pd.isna(adx) and adx > 40 and htf_1h == against:
            breakdown["strong_trend_against"] = -5.0
            score -= 5.0

        score = max(0.0, min(100.0, score))
        return round(score, 1), breakdown

    # ------------------------------------------------------------------
    # Levels
    # ------------------------------------------------------------------
    def levels(self, side: str, entry: float, atr: float) -> dict:
        s = self.s
        d = 1.0 if side == Side.LONG else -1.0
        sl = entry - d * s.sl_atr_mult * atr
        tp1 = entry + d * s.tp1_atr_mult * atr
        tp2 = entry + d * s.tp2_atr_mult * atr
        tp3 = entry + d * s.tp3_atr_mult * atr
        zone = 0.25 * atr
        risk = abs(entry - sl)
        rr = abs(tp3 - entry) / risk if risk > 0 else 0.0
        return {
            "sl_price": sl, "tp1_price": tp1, "tp2_price": tp2, "tp3_price": tp3,
            "entry_low": entry - zone, "entry_high": entry + zone, "risk_reward": rr,
        }

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------
    def evaluate(self, symbol: str, df: pd.DataFrame,
                 htf_frames: Optional[Dict[str, pd.DataFrame]] = None) -> Evaluation:
        """Evaluate the latest closed candle of `df` (indicators already computed)."""
        htf_frames = htf_frames or {}
        empty = Evaluation(symbol, None, {}, {}, 0, 0, None)
        if df is None or len(df) < 3:
            empty.rejected_reason = "not_enough_data"
            return empty

        latest = df.iloc[-1]
        prev = df.iloc[-2]
        candle_time = latest["timestamp"].to_pydatetime() if isinstance(latest["timestamp"], pd.Timestamp) \
            else latest["timestamp"]

        conds = self.conditions(df)
        long_score = sum(conds["long"].values())
        short_score = sum(conds["short"].values())
        ev = Evaluation(symbol, candle_time, conds["long"], conds["short"], long_score, short_score, None)

        if long_score >= self.s.min_conditions and long_score >= short_score:
            side = Side.LONG
            n = long_score
            triggered = [k for k, v in conds["long"].items() if v]
        elif short_score >= self.s.min_conditions:
            side = Side.SHORT
            n = short_score
            triggered = [k for k, v in conds["short"].items() if v]
        else:
            ev.rejected_reason = "conditions_not_met"
            return ev

        atr = float(latest["atr"])
        entry = float(latest["close"])
        if not atr or pd.isna(atr) or atr <= 0 or entry <= 0:
            ev.rejected_reason = "invalid_atr_or_price"
            return ev

        htf_1h = trend_label(htf_frames["1h"].iloc[-1]) if "1h" in htf_frames and len(htf_frames["1h"]) else "NEUTRAL"
        htf_4h = trend_label(htf_frames["4h"].iloc[-1]) if "4h" in htf_frames and len(htf_frames["4h"]) else "NEUTRAL"

        if self.s.require_htf_confirmation:
            want = "BULLISH" if side == Side.LONG else "BEARISH"
            if htf_1h != want:
                ev.rejected_reason = f"htf_1h_not_{want.lower()}"
                return ev

        conviction, breakdown = self._conviction(side, n, latest, prev, htf_1h, htf_4h)
        if conviction < self.s.min_conviction:
            ev.rejected_reason = f"conviction_{conviction:.0f}_below_min_{self.s.min_conviction:.0f}"
            return ev

        lv = self.levels(side, entry, atr)
        reasons = self._reasons(side, triggered, latest, htf_1h, htf_4h)
        vol_ratio = latest.get("volume_ratio")
        ev.candidate = SignalCandidate(
            symbol=symbol,
            side=side,
            timeframe=self.s.timeframe,
            entry_price=entry,
            entry_low=lv["entry_low"],
            entry_high=lv["entry_high"],
            sl_price=lv["sl_price"],
            tp1_price=lv["tp1_price"],
            tp2_price=lv["tp2_price"],
            tp3_price=lv["tp3_price"],
            risk_reward=round(lv["risk_reward"], 2),
            conviction_score=conviction,
            candle_time=candle_time,
            atr=atr,
            rsi=float(latest["rsi"]),
            macd=float(latest["macd"]),
            macd_signal=float(latest["macd_signal"]),
            bb_upper=float(latest["bb_upper"]),
            bb_lower=float(latest["bb_lower"]),
            volume_ratio=None if vol_ratio is None or pd.isna(vol_ratio) else float(vol_ratio),
            htf_trend_1h=htf_1h,
            htf_trend_4h=htf_4h,
            conditions=triggered,
            reasons=reasons,
            score_breakdown=breakdown,
        )
        return ev

    def generate_signal(self, symbol: str, df: pd.DataFrame,
                        htf_frames: Optional[Dict[str, pd.DataFrame]] = None) -> Optional[SignalCandidate]:
        """Convenience wrapper returning only the candidate."""
        return self.evaluate(symbol, df, htf_frames).candidate

    # ------------------------------------------------------------------
    @staticmethod
    def _reasons(side: str, triggered: List[str], latest: pd.Series, htf_1h: str, htf_4h: str) -> List[str]:
        out = []
        rsi = float(latest["rsi"])
        for c in triggered:
            if c in ("rsi_oversold", "rsi_overbought"):
                out.append(f"RSI {rsi:.1f} ({'oversold' if side == Side.LONG else 'overbought'})")
            elif c == "macd_bullish_cross":
                out.append("MACD bullish crossover")
            elif c == "macd_bearish_cross":
                out.append("MACD bearish crossover")
            elif c == "below_bb_lower":
                out.append(f"Close below lower Bollinger Band ({fmt_price(float(latest['bb_lower']))})")
            elif c == "above_bb_upper":
                out.append(f"Close above upper Bollinger Band ({fmt_price(float(latest['bb_upper']))})")
        out.append(f"1h trend {htf_1h.lower()}, 4h trend {htf_4h.lower()}")
        vr = latest.get("volume_ratio")
        if vr is not None and not pd.isna(vr):
            out.append(f"Volume {vr:.2f}x 20-period average")
        return out

    # ------------------------------------------------------------------
    def to_model(self, c: SignalCandidate, source: str = "binance", created_at: Optional[datetime] = None) -> Signal:
        return Signal(
            symbol=c.symbol,
            side=c.side,
            timeframe=c.timeframe,
            entry_price=c.entry_price,
            entry_low=c.entry_low,
            entry_high=c.entry_high,
            sl_price=c.sl_price,
            current_sl=c.sl_price,
            tp1_price=c.tp1_price,
            tp2_price=c.tp2_price,
            tp3_price=c.tp3_price,
            risk_reward=c.risk_reward,
            timestamp=created_at or utcnow(),
            candle_time=c.candle_time,
            status=SignalStatus.ACTIVE,
            conviction_score=c.conviction_score,
            tp_hits=0,
            max_favorable_pct=0.0,
            max_adverse_pct=0.0,
            atr=c.atr,
            rsi=c.rsi,
            macd=c.macd,
            macd_signal=c.macd_signal,
            bb_upper=c.bb_upper,
            bb_lower=c.bb_lower,
            volume_ratio=c.volume_ratio,
            htf_trend_1h=c.htf_trend_1h,
            htf_trend_4h=c.htf_trend_4h,
            conditions=",".join(c.conditions),
            reasons="; ".join(c.reasons),
            source=source,
        )
