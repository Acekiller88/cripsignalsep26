"""BinanceDataCollector tests with a mocked ccxt exchange (no network)."""
import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from data_collector import BinanceDataCollector

TF_MS = 15 * 60 * 1000


def _rows(n: int, end: datetime | None = None, include_open: bool = True):
    """n closed candles ending at the last full 15m boundary, plus (optionally) the forming candle."""
    now = end or datetime.now(timezone.utc)
    cur_open = int(now.timestamp() * 1000) // TF_MS * TF_MS
    rows = []
    for i in range(n, 0, -1):
        ts = cur_open - i * TF_MS
        rows.append([ts, 100.0 + i, 101.0 + i, 99.0 + i, 100.5 + i, 1000.0])
    if include_open:
        rows.append([cur_open, 100.0, 100.4, 99.8, 100.2, 12.0])
    return rows


class FakeRest:
    """Minimal stand-in for ccxt.async_support.binanceusdm."""

    def __init__(self, fail_times: int = 0):
        self.markets = {"BTC/USDT:USDT": {}, "ETH/USDT:USDT": {}}
        self.calls = []
        self.fail_times = fail_times
        self.urls = {"api": {"fapiPublic": "https://testnet.binancefuture.com/fapi/v1"}}

    async def load_markets(self):
        return self.markets

    async def fetch_ohlcv(self, symbol, timeframe, since=None, limit=None, params=None):
        self.calls.append((symbol, timeframe, since, limit))
        if self.fail_times > 0:
            self.fail_times -= 1
            import ccxt
            raise ccxt.NetworkError("simulated timeout")
        rows = _rows(limit or 100)
        if since is not None:
            rows = [r for r in rows if r[0] >= since]
        return rows

    async def fetch_ticker(self, symbol):
        return {"last": 12345.6}

    async def fetch_time(self):
        return 0

    async def close(self):
        pass


@pytest.fixture
def collector(settings, monkeypatch):
    cfg = settings.with_overrides(data_source="binance", enable_websocket=False, binance_testnet=True)
    c = BinanceDataCollector(cfg)
    c.rest = FakeRest()
    return c


def test_binance_collector_builds_testnet_endpoints(settings):
    cfg = settings.with_overrides(data_source="binance", enable_websocket=True, binance_testnet=True)
    c = BinanceDataCollector(cfg)
    assert "testnet.binancefuture.com" in c.endpoint
    assert c.ws is not None and "binancefuture.com" in c.ws.urls["api"]["ws"]["future"]
    live = BinanceDataCollector(cfg.with_overrides(binance_testnet=False, enable_websocket=False))
    assert live.endpoint.startswith("https://fapi.binance.com")
    asyncio.run(c.close())
    asyncio.run(live.close())


def test_get_klines_rest_drops_forming_candle(collector):
    df = asyncio.run(collector.get_klines("BTCUSDT", "15m", limit=50))
    assert len(df) == 50
    assert collector.rest.calls[0][0] == "BTC/USDT:USDT" and collector.rest.calls[0][1] == "15m"
    # the forming candle (open == current boundary) must be excluded
    now = datetime.utcnow()
    assert df["timestamp"].iloc[-1] + timedelta(minutes=15) <= now
    assert list(df.columns) == ["timestamp", "open", "high", "low", "close", "volume"]
    assert collector.rest_calls == 1 and collector.rest_failures == 0


def test_rest_retries_with_backoff(collector, monkeypatch):
    import utils
    sleeps = []

    async def fake_sleep(d):
        sleeps.append(d)

    monkeypatch.setattr(utils.asyncio, "sleep", fake_sleep)
    collector.rest = FakeRest(fail_times=2)
    df = asyncio.run(collector.get_klines("ETHUSDT", "15m", limit=20))
    assert len(df) == 20
    assert len(collector.rest.calls) == 3 and len(sleeps) == 2
    assert sleeps[1] > sleeps[0] * 1.2  # exponential growth (with jitter)


def test_rest_failure_falls_back_to_cache_then_raises(collector, monkeypatch):
    import utils

    async def fake_sleep(d):
        pass

    monkeypatch.setattr(utils.asyncio, "sleep", fake_sleep)
    # warm the cache
    asyncio.run(collector.get_klines("BTCUSDT", "15m", limit=30))
    collector.rest = FakeRest(fail_times=99)
    df = asyncio.run(collector.get_klines("BTCUSDT", "15m", limit=30))
    assert len(df) == 30  # served from cache
    assert collector.rest_failures == 1 and "NetworkError" in collector.last_rest_error
    # unknown symbol with no cache -> error propagates
    with pytest.raises(Exception):
        asyncio.run(collector.get_klines("SOLUSDT", "15m", limit=30))


def test_ws_cache_used_when_fresh_and_complete(collector):
    import time
    rows = _rows(120)
    collector.ws = object()  # pretend a socket exists
    collector._merge_cache("BTCUSDT", "15m", rows)
    collector._ws_last_update[("BTCUSDT", "15m")] = time.time()
    collector.websocket_connected = True
    df = asyncio.run(collector.get_klines("BTCUSDT", "15m", limit=100))
    assert len(df) == 100 and collector.rest.calls == []  # no REST call
    price = asyncio.run(collector.get_last_price("BTCUSDT"))
    assert price == pytest.approx(100.2)  # close of the forming candle from the cache
    # stale socket -> REST again
    collector._ws_last_update[("BTCUSDT", "15m")] = time.time() - 10_000
    asyncio.run(collector.get_klines("BTCUSDT", "15m", limit=100))
    assert len(collector.rest.calls) == 1


def test_fetch_candles_since_and_ticker(collector):
    since = datetime.utcnow() - timedelta(hours=2)
    df = asyncio.run(collector.fetch_candles_since("BTCUSDT", "15m", since, limit=50))
    assert (df["timestamp"] >= since - timedelta(minutes=15)).all()
    assert collector.rest.calls[-1][2] is not None  # since passed in ms
    assert asyncio.run(collector.get_last_price("ETHUSDT")) == pytest.approx(12345.6)
    ok, info = asyncio.run(collector.check_connection())
    assert ok and "testnet" in info


def test_unsupported_symbols_detected_on_start(collector):
    asyncio.run(collector.start(["BTCUSDT", "SOLUSDT", "ETHUSDT"]))
    assert collector.unsupported_symbols == ["SOLUSDT"]
    assert collector.stats()["unsupported_symbols"] == ["SOLUSDT"]
    ok, info = asyncio.run(collector.check_connection())
    assert ok and "unsupported symbols: SOLUSDT" in info
