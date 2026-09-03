"""
Market data layer.

* `BinanceDataCollector` – Binance USD-M Futures via ccxt.
    - REST (`ccxt.async_support`) for historical candles, with exponential
      backoff on network / rate-limit errors.
    - WebSocket (`ccxt.pro`) streaming of the main timeframe for real-time
      candles; the REST path is used automatically whenever the socket is
      unhealthy or the cache is incomplete.
    - Testnet (testnet.binancefuture.com) or live endpoints.

* `SyntheticDataCollector` – deterministic offline price generator.  Used for
  local testing, CI and demos when the exchange is unreachable.  It produces
  realistic looking OHLCV series (regime-switching random walk with volatility
  clustering) aligned to real wall-clock candle boundaries.

Both expose the same async interface:

    await get_klines(symbol, timeframe, limit, closed_only=True) -> DataFrame
    await fetch_candles_since(symbol, timeframe, since) -> DataFrame
    await get_last_price(symbol) -> float
    await start() / await close()
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import math
import time
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Protocol, Tuple

import numpy as np
import pandas as pd

from config import Settings
from utils import retry_async, timeframe_to_seconds, to_ccxt_symbol

logger = logging.getLogger("data")

OHLCV_COLUMNS = ["timestamp", "open", "high", "low", "close", "volume"]


def ohlcv_to_dataframe(rows: List[List[float]]) -> pd.DataFrame:
    """Convert ccxt-style [[ts_ms, o, h, l, c, v], ...] into a tidy DataFrame."""
    if not rows:
        return pd.DataFrame(columns=OHLCV_COLUMNS)
    df = pd.DataFrame(rows, columns=OHLCV_COLUMNS)
    df["timestamp"] = pd.to_datetime(df["timestamp"].astype("int64"), unit="ms", utc=True).dt.tz_localize(None)
    for col in OHLCV_COLUMNS[1:]:
        df[col] = df[col].astype(float)
    df = df.drop_duplicates(subset="timestamp", keep="last").sort_values("timestamp").reset_index(drop=True)
    return df


def drop_unclosed_candle(df: pd.DataFrame, timeframe: str, now: Optional[datetime] = None) -> pd.DataFrame:
    """Remove the still-forming candle so analysis only sees closed candles."""
    if df.empty:
        return df
    now = now or datetime.now(timezone.utc).replace(tzinfo=None)
    tf = timedelta(seconds=timeframe_to_seconds(timeframe))
    return df[df["timestamp"] + tf <= now].reset_index(drop=True)


class DataCollector(Protocol):
    name: str
    websocket_connected: bool

    async def start(self) -> None: ...
    async def close(self) -> None: ...
    async def get_klines(self, symbol: str, timeframe: str, limit: int = 300, closed_only: bool = True) -> pd.DataFrame: ...
    async def fetch_candles_since(self, symbol: str, timeframe: str, since: datetime, limit: int = 1000) -> pd.DataFrame: ...
    async def get_last_price(self, symbol: str) -> Optional[float]: ...


# ===========================================================================
# Binance (ccxt)
# ===========================================================================
class BinanceDataCollector:
    """Binance USD-M futures market data via ccxt (REST + WebSocket)."""

    name = "binance"

    def __init__(self, settings: Settings):
        import ccxt.async_support as ccxt_async  # imported lazily so tests without ccxt still work

        self.settings = settings
        self._ccxt = ccxt_async
        params = {
            "enableRateLimit": True,
            "timeout": settings.exchange_timeout_ms,
            "options": {
                "defaultType": "future",
                "adjustForTimeDifference": True,
                "recvWindow": 10_000,
            },
        }
        if settings.binance_api_key and settings.binance_secret:
            params["apiKey"] = settings.binance_api_key
            params["secret"] = settings.binance_secret

        self.rest = ccxt_async.binanceusdm(params)
        if settings.binance_testnet:
            self.rest.set_sandbox_mode(True)

        self.ws = None
        self._ws_tasks: List[asyncio.Task] = []
        self._ws_symbols: List[str] = []
        self._ws_timeframe = settings.timeframe
        if settings.enable_websocket:
            try:
                import ccxt.pro as ccxt_pro

                self.ws = ccxt_pro.binanceusdm(dict(params))
                if settings.binance_testnet:
                    self.ws.set_sandbox_mode(True)
            except Exception as exc:  # pragma: no cover
                logger.warning("ccxt.pro unavailable, WebSocket disabled: %s", exc)
                self.ws = None

        self.websocket_connected = False
        self._ws_last_update: Dict[Tuple[str, str], float] = {}
        # (symbol, timeframe) -> {ts_ms: [ts, o, h, l, c, v]}
        self._cache: Dict[Tuple[str, str], Dict[int, List[float]]] = {}
        self._cache_limit = 1500
        self._markets_loaded = False
        self._stop = asyncio.Event()
        self.rest_calls = 0
        self.rest_failures = 0
        self.last_rest_error: Optional[str] = None

    # ------------------------------------------------------------------
    @property
    def endpoint(self) -> str:
        try:
            return self.rest.urls["api"]["fapiPublic"]
        except Exception:  # pragma: no cover
            return "unknown"

    def _retryable(self) -> Tuple[type, ...]:
        c = self._ccxt
        return (c.NetworkError, c.RateLimitExceeded, c.DDoSProtection, c.RequestTimeout, c.ExchangeNotAvailable)

    async def _ensure_markets(self) -> None:
        if self._markets_loaded:
            return

        async def _load():
            await self.rest.load_markets()

        await retry_async(_load, attempts=5, base_delay=2.0, retry_on=self._retryable(), logger=logger,
                          what="load_markets")
        self._markets_loaded = True
        logger.info("Loaded %d Binance futures markets from %s", len(self.rest.markets), self.endpoint)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    async def start(self, symbols: Optional[List[str]] = None) -> None:
        """Warm the REST connection and start WebSocket streams."""
        symbols = symbols or list(self.settings.trading_pairs)
        try:
            await self._ensure_markets()
        except Exception as exc:
            logger.error("Could not load markets (will retry on demand): %s", exc)
        if self.ws is not None:
            self._ws_symbols = symbols
            for symbol in symbols:
                task = asyncio.create_task(self._ws_loop(symbol, self._ws_timeframe), name=f"ws-{symbol}")
                self._ws_tasks.append(task)
            logger.info("WebSocket streams started for %s (%s)", ", ".join(symbols), self._ws_timeframe)

    async def close(self) -> None:
        self._stop.set()
        for task in self._ws_tasks:
            task.cancel()
        if self._ws_tasks:
            await asyncio.gather(*self._ws_tasks, return_exceptions=True)
        self._ws_tasks.clear()
        try:
            if self.ws is not None:
                await self.ws.close()
        except Exception:  # pragma: no cover
            pass
        try:
            await self.rest.close()
        except Exception:  # pragma: no cover
            pass

    # ------------------------------------------------------------------
    # WebSocket streaming
    # ------------------------------------------------------------------
    async def _ws_loop(self, symbol: str, timeframe: str) -> None:
        ccxt_symbol = to_ccxt_symbol(symbol)
        backoff = 1.0
        while not self._stop.is_set():
            try:
                candles = await self.ws.watch_ohlcv(ccxt_symbol, timeframe)
                self._merge_cache(symbol, timeframe, candles)
                self._ws_last_update[(symbol, timeframe)] = time.time()
                if not self.websocket_connected:
                    logger.info("WebSocket connected (%s %s)", symbol, timeframe)
                self.websocket_connected = True
                backoff = 1.0
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.websocket_connected = False
                logger.warning("WebSocket %s %s error: %s — reconnecting in %.0fs", symbol, timeframe,
                               str(exc)[:160], backoff)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 60.0)

    def _merge_cache(self, symbol: str, timeframe: str, candles: List[List[float]]) -> None:
        key = (symbol, timeframe)
        bucket = self._cache.setdefault(key, {})
        for c in candles:
            if c and c[0] is not None:
                bucket[int(c[0])] = [int(c[0]), float(c[1]), float(c[2]), float(c[3]), float(c[4]), float(c[5])]
        if len(bucket) > self._cache_limit:
            for ts in sorted(bucket)[: len(bucket) - self._cache_limit]:
                del bucket[ts]

    def _cache_dataframe(self, symbol: str, timeframe: str) -> pd.DataFrame:
        bucket = self._cache.get((symbol, timeframe), {})
        return ohlcv_to_dataframe([bucket[ts] for ts in sorted(bucket)])

    @staticmethod
    def _is_contiguous(df: pd.DataFrame, timeframe: str) -> bool:
        """True when consecutive candles are exactly one timeframe apart (no gaps)."""
        if len(df) < 2:
            return True
        step = pd.Timedelta(seconds=timeframe_to_seconds(timeframe))
        return bool((df["timestamp"].diff().dropna() == step).all())

    def _ws_is_fresh(self, symbol: str, timeframe: str) -> bool:
        """True when the socket delivered an update for this stream recently."""
        last = self._ws_last_update.get((symbol, timeframe))
        if last is None or not self.websocket_connected:
            return False
        tf = timeframe_to_seconds(timeframe)
        # Binance pushes kline updates at least every ~2s while trading is active;
        # tolerate up to half a candle (min 90 s) of silence on quiet testnet markets.
        return (time.time() - last) < max(90.0, tf / 2)

    # ------------------------------------------------------------------
    # REST
    # ------------------------------------------------------------------
    async def _rest_fetch_ohlcv(self, symbol: str, timeframe: str, since: Optional[int] = None,
                                limit: int = 500) -> List[List[float]]:
        await self._ensure_markets()
        ccxt_symbol = to_ccxt_symbol(symbol)

        async def _call():
            self.rest_calls += 1
            return await self.rest.fetch_ohlcv(ccxt_symbol, timeframe, since=since, limit=min(limit, 1500))

        try:
            rows = await retry_async(_call, attempts=4, base_delay=1.5, max_delay=20.0,
                                     retry_on=self._retryable(), logger=logger,
                                     what=f"fetch_ohlcv {symbol} {timeframe}")
            self.last_rest_error = None
            return rows
        except Exception as exc:
            self.rest_failures += 1
            self.last_rest_error = f"{type(exc).__name__}: {str(exc)[:200]}"
            raise

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    async def get_klines(self, symbol: str, timeframe: str, limit: int = 300,
                         closed_only: bool = True) -> pd.DataFrame:
        """Return the latest `limit` candles (closed candles only by default).

        Uses the WebSocket cache when it is healthy and complete, otherwise
        falls back to REST (and the REST result is merged into the cache).
        """
        symbol = symbol.upper()
        df = pd.DataFrame(columns=OHLCV_COLUMNS)
        used_ws = False
        if timeframe == self._ws_timeframe and self._ws_is_fresh(symbol, timeframe):
            cached = self._cache_dataframe(symbol, timeframe)
            if len(cached) >= limit + 1 and self._is_contiguous(cached.tail(limit + 1), timeframe):
                df = cached.tail(limit + 1).reset_index(drop=True)
                used_ws = True

        if not used_ws:
            try:
                rows = await self._rest_fetch_ohlcv(symbol, timeframe, limit=limit + 1)
                self._merge_cache(symbol, timeframe, rows)
                df = ohlcv_to_dataframe(rows)
            except Exception as exc:
                # Last resort: whatever we have in the cache (may be stale but is better than nothing)
                cached = self._cache_dataframe(symbol, timeframe)
                if cached.empty:
                    raise
                logger.warning("REST failed for %s %s (%s) — serving %d cached candles", symbol, timeframe,
                               str(exc)[:120], len(cached))
                df = cached

        if closed_only:
            df = drop_unclosed_candle(df, timeframe)
        return df.tail(limit).reset_index(drop=True)

    async def fetch_candles_since(self, symbol: str, timeframe: str, since: datetime,
                                  limit: int = 1000) -> pd.DataFrame:
        """Candles with open time >= `since` (naive UTC)."""
        since_ms = int(since.replace(tzinfo=timezone.utc).timestamp() * 1000)
        rows = await self._rest_fetch_ohlcv(symbol.upper(), timeframe, since=since_ms, limit=limit)
        return ohlcv_to_dataframe(rows)

    async def get_last_price(self, symbol: str) -> Optional[float]:
        symbol = symbol.upper()
        # 1) WebSocket cache (close of the forming candle)
        if self._ws_is_fresh(symbol, self._ws_timeframe):
            bucket = self._cache.get((symbol, self._ws_timeframe))
            if bucket:
                return float(bucket[max(bucket)][4])
        # 2) REST ticker
        await self._ensure_markets()
        ccxt_symbol = to_ccxt_symbol(symbol)

        async def _call():
            self.rest_calls += 1
            return await self.rest.fetch_ticker(ccxt_symbol)

        try:
            ticker = await retry_async(_call, attempts=3, base_delay=1.0, retry_on=self._retryable(),
                                       logger=logger, what=f"fetch_ticker {symbol}")
            price = ticker.get("last") or ticker.get("close")
            return float(price) if price is not None else None
        except Exception as exc:
            logger.warning("Could not fetch last price for %s: %s", symbol, str(exc)[:120])
            return None

    async def check_connection(self) -> Tuple[bool, str]:
        """Ping the REST endpoint; returns (ok, message)."""
        try:
            await self._ensure_markets()
            t0 = time.time()
            await self.rest.fetch_time()
            return True, f"OK ({(time.time() - t0) * 1000:.0f} ms, {self.endpoint})"
        except Exception as exc:
            return False, f"{type(exc).__name__}: {str(exc)[:200]}"

    def stats(self) -> dict:
        return {
            "source": self.name,
            "endpoint": self.endpoint,
            "testnet": self.settings.binance_testnet,
            "websocket_enabled": self.ws is not None,
            "websocket_connected": self.websocket_connected,
            "rest_calls": self.rest_calls,
            "rest_failures": self.rest_failures,
            "last_rest_error": self.last_rest_error,
            "cached_streams": {f"{s}:{tf}": len(b) for (s, tf), b in self._cache.items()},
        }


# ===========================================================================
# Synthetic (offline) data
# ===========================================================================
_BASE_PRICES = {
    "BTCUSDT": 95_000.0,
    "ETHUSDT": 3_400.0,
    "SOLUSDT": 180.0,
    "XRPUSDT": 2.3,
    "DOGEUSDT": 0.32,
    "BNBUSDT": 650.0,
    "ADAUSDT": 0.9,
    "AVAXUSDT": 38.0,
    "LINKUSDT": 20.0,
}


class SyntheticDataCollector:
    """Deterministic offline market simulator with realistic OHLCV structure.

    A 1-minute series per symbol is generated from a fixed anchor (60 days
    back) with a regime-switching drift and GARCH-like volatility clustering,
    then resampled to any timeframe.  The same symbol always yields the same
    history, so repeated calls are consistent and tests are reproducible.
    """

    name = "synthetic"
    websocket_connected = False

    def __init__(self, settings: Settings, history_days: int = 60, seed_salt: str = "cripsignal",
                 clock=None):
        self.settings = settings
        self.history_days = history_days
        self.seed_salt = seed_salt
        self._clock = clock or (lambda: datetime.now(timezone.utc).replace(tzinfo=None))
        self._series: Dict[str, Dict[str, object]] = {}
        anchor = self._clock() - timedelta(days=history_days)
        self.anchor = anchor.replace(hour=0, minute=0, second=0, microsecond=0)

    async def start(self, symbols: Optional[List[str]] = None) -> None:
        for symbol in symbols or self.settings.trading_pairs:
            self._ensure_series(symbol)
        logger.info("Synthetic data source ready (%d symbols, anchor %s)", len(self._series), self.anchor)

    async def close(self) -> None:
        return None

    # ------------------------------------------------------------------
    def _seed(self, symbol: str) -> int:
        digest = hashlib.sha256(f"{self.seed_salt}:{symbol}".encode()).hexdigest()
        return int(digest[:8], 16)

    def _ensure_series(self, symbol: str) -> None:
        symbol = symbol.upper()
        now = self._clock()
        needed_minutes = int((now - self.anchor).total_seconds() // 60) + 1
        state = self._series.get(symbol)
        if state is None:
            rng = np.random.default_rng(self._seed(symbol))
            base = _BASE_PRICES.get(symbol, 10.0 + (self._seed(symbol) % 1000))
            state = {
                "rng": rng,
                "price": base,
                "vol": 0.0006,        # per-minute volatility (~0.06%)
                "drift": 0.0,
                "regime_left": 0,
                "rows": [],           # [ts_ms, o, h, l, c, v]
                "base_vol": 0.0006 if base > 1000 else 0.0009,
                "base_volume": max(1.0, 5_000_000.0 / base),
            }
            self._series[symbol] = state
        rows: List[List[float]] = state["rows"]  # type: ignore[assignment]
        missing = needed_minutes - len(rows)
        if missing > 0:
            self._extend(state, missing)

    def _extend(self, state: dict, count: int) -> None:
        rng: np.random.Generator = state["rng"]
        rows: List[List[float]] = state["rows"]
        price = float(state["price"])
        vol = float(state["vol"])
        drift = float(state["drift"])
        regime_left = int(state["regime_left"])
        base_vol = float(state["base_vol"])
        base_volume = float(state["base_volume"])
        start_idx = len(rows)
        anchor_ms = int(self.anchor.replace(tzinfo=timezone.utc).timestamp() * 1000)

        for i in range(count):
            if regime_left <= 0:
                # new regime: trending up / down / ranging with occasional high-vol bursts
                regime = rng.choice(["up", "down", "range", "burst"], p=[0.3, 0.3, 0.3, 0.1])
                regime_left = int(rng.integers(90, 720))  # 1.5h .. 12h
                if regime == "up":
                    drift = base_vol * rng.uniform(0.05, 0.2)
                elif regime == "down":
                    drift = -base_vol * rng.uniform(0.05, 0.2)
                elif regime == "range":
                    drift = 0.0
                else:
                    drift = base_vol * rng.uniform(-0.5, 0.5)
                    vol = base_vol * rng.uniform(2.5, 4.0)
            regime_left -= 1
            # volatility clustering: mean-revert towards base with random shocks
            vol = max(base_vol * 0.4, vol + 0.05 * (base_vol - vol) + base_vol * 0.08 * rng.standard_normal())
            shock = rng.standard_t(df=4) * vol
            ret = drift + shock
            open_ = price
            close = open_ * math.exp(ret)
            wick = abs(rng.standard_normal()) * vol * 0.8
            high = max(open_, close) * math.exp(wick * rng.uniform(0.2, 1.0))
            low = min(open_, close) * math.exp(-wick * rng.uniform(0.2, 1.0))
            volume = base_volume * math.exp(rng.standard_normal() * 0.5) * (1.0 + 40.0 * abs(ret))
            ts = anchor_ms + (start_idx + i) * 60_000
            rows.append([ts, open_, high, low, close, volume])
            price = close

        state["price"] = price
        state["vol"] = vol
        state["drift"] = drift
        state["regime_left"] = regime_left

    def _minute_frame(self, symbol: str) -> pd.DataFrame:
        self._ensure_series(symbol)
        rows = self._series[symbol.upper()]["rows"]
        return ohlcv_to_dataframe(list(rows))  # type: ignore[arg-type]

    @staticmethod
    def _resample(df_1m: pd.DataFrame, timeframe: str) -> pd.DataFrame:
        tf = timeframe_to_seconds(timeframe)
        if tf == 60:
            return df_1m
        bucket = (df_1m["timestamp"].astype("int64") // 10**9 // tf) * tf
        grouped = df_1m.groupby(bucket)
        out = pd.DataFrame({
            "timestamp": pd.to_datetime(grouped["timestamp"].first().index.to_numpy(), unit="s"),
            "open": grouped["open"].first().to_numpy(),
            "high": grouped["high"].max().to_numpy(),
            "low": grouped["low"].min().to_numpy(),
            "close": grouped["close"].last().to_numpy(),
            "volume": grouped["volume"].sum().to_numpy(),
        })
        return out.reset_index(drop=True)

    # ------------------------------------------------------------------
    async def get_klines(self, symbol: str, timeframe: str, limit: int = 300,
                         closed_only: bool = True) -> pd.DataFrame:
        df = self._resample(self._minute_frame(symbol), timeframe)
        if closed_only:
            df = drop_unclosed_candle(df, timeframe, now=self._clock())
        return df.tail(limit).reset_index(drop=True)

    async def fetch_candles_since(self, symbol: str, timeframe: str, since: datetime,
                                  limit: int = 1000) -> pd.DataFrame:
        df = self._resample(self._minute_frame(symbol), timeframe)
        df = df[df["timestamp"] >= since]
        return df.head(limit).reset_index(drop=True)

    async def get_last_price(self, symbol: str) -> Optional[float]:
        df = self._minute_frame(symbol)
        return float(df["close"].iloc[-1]) if not df.empty else None

    async def check_connection(self) -> Tuple[bool, str]:
        return True, "synthetic data source (offline)"

    def stats(self) -> dict:
        return {
            "source": self.name,
            "endpoint": "synthetic",
            "testnet": False,
            "websocket_enabled": False,
            "websocket_connected": False,
            "symbols": sorted(self._series),
            "anchor": self.anchor.isoformat(),
        }


# ===========================================================================
# Factory
# ===========================================================================
def create_data_collector(settings: Settings):
    if settings.is_synthetic:
        return SyntheticDataCollector(settings)
    return BinanceDataCollector(settings)
