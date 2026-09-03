"""
Small shared helpers: logging, time/timeframe utilities, symbol conversion,
price formatting and retry/backoff logic.
"""
from __future__ import annotations

import asyncio
import logging
import random
import sys
from datetime import datetime, timezone
from typing import Awaitable, Callable, Iterable, Optional, Tuple, TypeVar

T = TypeVar("T")

_TIMEFRAME_UNITS = {"m": 60, "h": 3600, "d": 86400, "w": 604800}


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
def setup_logging(level: str = "INFO") -> None:
    """Configure root logging once, with a compact UTC formatter."""
    root = logging.getLogger()
    if getattr(root, "_crypto_bot_configured", False):
        root.setLevel(level.upper())
        return
    handler = logging.StreamHandler(sys.stdout)
    formatter = logging.Formatter(
        fmt="%(asctime)s | %(levelname)-7s | %(name)-18s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    formatter.converter = lambda *_: datetime.now(timezone.utc).timetuple()  # type: ignore[assignment]
    handler.setFormatter(formatter)
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level.upper())
    root._crypto_bot_configured = True  # type: ignore[attr-defined]
    # Quieten very chatty third-party loggers
    for noisy in ("httpx", "httpcore", "ccxt", "telegram", "urllib3", "asyncio", "websockets"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


# ---------------------------------------------------------------------------
# Time helpers
# ---------------------------------------------------------------------------
def utcnow() -> datetime:
    """Naive UTC 'now' (all timestamps in the database are naive UTC)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def timeframe_to_seconds(timeframe: str) -> int:
    """'15m' -> 900, '1h' -> 3600, '4h' -> 14400, '1d' -> 86400."""
    tf = timeframe.strip().lower()
    if not tf or tf[-1] not in _TIMEFRAME_UNITS:
        raise ValueError(f"Unsupported timeframe: {timeframe!r}")
    try:
        amount = int(tf[:-1])
    except ValueError as exc:
        raise ValueError(f"Unsupported timeframe: {timeframe!r}") from exc
    return amount * _TIMEFRAME_UNITS[tf[-1]]


def seconds_until_next_candle(timeframe: str, now: Optional[datetime] = None, delay: int = 0) -> float:
    """Seconds until the next candle boundary (+ optional delay) for a timeframe."""
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    tf_seconds = timeframe_to_seconds(timeframe)
    epoch = now.timestamp()
    next_close = (int(epoch // tf_seconds) + 1) * tf_seconds
    return max(0.0, next_close - epoch + delay)


def current_candle_open(timeframe: str, now: Optional[datetime] = None) -> datetime:
    """Naive UTC open time of the candle that is currently forming."""
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    tf_seconds = timeframe_to_seconds(timeframe)
    open_ts = int(now.timestamp() // tf_seconds) * tf_seconds
    return datetime.fromtimestamp(open_ts, tz=timezone.utc).replace(tzinfo=None)


def to_naive_utc(dt: datetime) -> datetime:
    if dt.tzinfo is not None:
        return dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


# ---------------------------------------------------------------------------
# Symbols
# ---------------------------------------------------------------------------
def to_ccxt_symbol(symbol: str) -> str:
    """'BTCUSDT' -> 'BTC/USDT:USDT' (ccxt USD-M perpetual notation)."""
    s = symbol.upper().replace("/", "").split(":")[0]
    for quote in ("USDT", "USDC", "BUSD", "USD"):
        if s.endswith(quote) and len(s) > len(quote):
            return f"{s[:-len(quote)]}/{quote}:{quote}"
    return symbol


def from_ccxt_symbol(symbol: str) -> str:
    """'BTC/USDT:USDT' -> 'BTCUSDT'."""
    return symbol.split(":")[0].replace("/", "").upper()


# ---------------------------------------------------------------------------
# Price formatting
# ---------------------------------------------------------------------------
def price_decimals(price: float) -> int:
    """Sensible number of decimals for a given price magnitude."""
    p = abs(float(price))
    if p >= 1000:
        return 2
    if p >= 100:
        return 3
    if p >= 1:
        return 4
    if p >= 0.01:
        return 5
    return 6


def fmt_price(price: Optional[float], decimals: Optional[int] = None) -> str:
    if price is None:
        return "-"
    d = price_decimals(price) if decimals is None else decimals
    return f"{price:,.{d}f}"


def fmt_pct(value: Optional[float], signed: bool = True) -> str:
    if value is None:
        return "-"
    return f"{value:+.2f}%" if signed else f"{value:.2f}%"


# ---------------------------------------------------------------------------
# Retry with exponential backoff
# ---------------------------------------------------------------------------
async def retry_async(
    func: Callable[[], Awaitable[T]],
    *,
    attempts: int = 4,
    base_delay: float = 1.0,
    max_delay: float = 30.0,
    retry_on: Tuple[type, ...] = (Exception,),
    logger: Optional[logging.Logger] = None,
    what: str = "operation",
) -> T:
    """Call `func` until it succeeds, sleeping with exponential backoff + jitter."""
    last_exc: Optional[BaseException] = None
    for attempt in range(1, attempts + 1):
        try:
            return await func()
        except retry_on as exc:  # noqa: PERF203
            last_exc = exc
            if attempt >= attempts:
                break
            delay = min(max_delay, base_delay * (2 ** (attempt - 1))) * (0.7 + random.random() * 0.6)
            if logger:
                logger.warning(
                    "%s failed (attempt %d/%d): %s — retrying in %.1fs",
                    what, attempt, attempts, str(exc)[:200], delay,
                )
            await asyncio.sleep(delay)
    assert last_exc is not None
    raise last_exc


def chunked(items: Iterable[T], size: int):
    batch = []
    for item in items:
        batch.append(item)
        if len(batch) >= size:
            yield batch
            batch = []
    if batch:
        yield batch
