import asyncio
from datetime import datetime, timedelta

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from bot import SignalBot
from data_collector import SyntheticDataCollector, drop_unclosed_candle, ohlcv_to_dataframe
from database import Database, Signal, SignalStatus
from main import create_app
from telegram_bot import (
    TelegramNotifier,
    format_closed_message,
    format_daily_summary,
    format_signal_message,
    format_tp_update,
)
from utils import current_candle_open, from_ccxt_symbol, seconds_until_next_candle, timeframe_to_seconds, to_ccxt_symbol


class RecordingNotifier:
    enabled = False

    def __init__(self):
        self.messages = []

    async def send_signal(self, sig):
        self.messages.append(("signal", sig["symbol"], sig["side"]))
        return "42"

    async def send_tp_update(self, sig, level, new_sl):
        self.messages.append(("tp", sig["id"], level))

    async def send_closed(self, sig):
        self.messages.append(("closed", sig["id"]))

    async def send_startup(self, info):
        self.messages.append(("startup", info))

    async def send_daily_summary(self, summary, overall):
        self.messages.append(("summary", summary["day"]))

    async def close(self):
        pass

    def stats(self):
        return {"enabled": False, "sent": len(self.messages), "failed": 0, "last_error": None}


class ForcedSignalCollector(SyntheticDataCollector):
    """Synthetic collector that returns a frame engineered to end in a LONG setup."""

    def __init__(self, settings, force_symbols=("BTCUSDT",)):
        super().__init__(settings)
        self.force_symbols = set(force_symbols)

    async def get_klines(self, symbol, timeframe, limit=300, closed_only=True):
        df = await super().get_klines(symbol, timeframe, limit, closed_only)
        if symbol in self.force_symbols and timeframe == self.settings.timeframe:
            df = df.copy()
            n = len(df)
            base = float(df.loc[df.index[n - 26], "close"])
            # 22 quiet candles (narrow Bollinger Bands) followed by a 3-candle crash:
            # RSI collapses below 30 and the close ends far below the lower band.
            for j, k in enumerate(range(n - 25, n - 3)):
                px = base * (1 + 0.0004 * ((-1) ** j))
                df.loc[df.index[k], ["open", "high", "low", "close"]] = [base, max(base, px) * 1.0003, min(base, px) * 0.9997, px]
            for k, drop in zip(range(n - 3, n), [0.985, 0.97, 0.955]):
                px = base * drop
                df.loc[df.index[k], ["open", "high", "low", "close"]] = [px * 1.01, px * 1.012, px * 0.998, px]
        return df


# ---------------------------------------------------------------------------
# utils
# ---------------------------------------------------------------------------
def test_timeframe_helpers():
    assert timeframe_to_seconds("15m") == 900 and timeframe_to_seconds("1h") == 3600 and timeframe_to_seconds("4h") == 14400
    with pytest.raises(ValueError):
        timeframe_to_seconds("abc")
    now = datetime(2026, 9, 3, 12, 7, 30)
    assert seconds_until_next_candle("15m", now) == pytest.approx(7.5 * 60)
    assert seconds_until_next_candle("15m", now, delay=5) == pytest.approx(7.5 * 60 + 5)
    assert current_candle_open("15m", now) == datetime(2026, 9, 3, 12, 0)
    assert to_ccxt_symbol("BTCUSDT") == "BTC/USDT:USDT" and from_ccxt_symbol("BTC/USDT:USDT") == "BTCUSDT"
    assert to_ccxt_symbol("DOGEUSDT") == "DOGE/USDT:USDT"


def test_ohlcv_conversion_and_unclosed_drop():
    now = datetime(2026, 9, 3, 12, 10)
    rows = [[int((now - timedelta(minutes=15 * k)).replace(minute=0).timestamp() * 1000) + k, 1, 2, 0.5, 1.5, 10] for k in range(3)]
    df = ohlcv_to_dataframe(rows)
    assert list(df.columns) == ["timestamp", "open", "high", "low", "close", "volume"]
    assert df["timestamp"].is_monotonic_increasing
    frame = pd.DataFrame({
        "timestamp": [datetime(2026, 9, 3, 11, 30), datetime(2026, 9, 3, 11, 45), datetime(2026, 9, 3, 12, 0)],
        "open": 1, "high": 1, "low": 1, "close": 1, "volume": 1,
    })
    closed = drop_unclosed_candle(frame, "15m", now=datetime(2026, 9, 3, 12, 5))
    assert len(closed) == 2 and closed["timestamp"].iloc[-1] == datetime(2026, 9, 3, 11, 45)


def test_ws_cache_contiguity_check():
    from data_collector import BinanceDataCollector
    ok = pd.DataFrame({"timestamp": [datetime(2026, 9, 3, 12, 0) + timedelta(minutes=15 * i) for i in range(5)]})
    assert BinanceDataCollector._is_contiguous(ok, "15m") is True
    gap = ok.drop(index=2)
    assert BinanceDataCollector._is_contiguous(gap, "15m") is False


# ---------------------------------------------------------------------------
# synthetic data source
# ---------------------------------------------------------------------------
def test_synthetic_collector_is_deterministic_and_aligned(settings):
    async def run():
        a = SyntheticDataCollector(settings)
        b = SyntheticDataCollector(settings)
        da = await a.get_klines("ETHUSDT", "15m", limit=100)
        db_ = await b.get_klines("ETHUSDT", "15m", limit=100)
        assert da["close"].tolist() == db_["close"].tolist()
        assert (da["timestamp"].dt.minute % 15 == 0).all()
        assert (da["high"] >= da[["open", "close"]].max(axis=1)).all()
        assert (da["low"] <= da[["open", "close"]].min(axis=1)).all()
        # closed candles only
        assert da["timestamp"].iloc[-1] + timedelta(minutes=15) <= datetime.utcnow()
        h1 = await a.get_klines("ETHUSDT", "1h", limit=50)
        assert (h1["timestamp"].dt.minute == 0).all()
        since = datetime.utcnow() - timedelta(hours=3)
        m1 = await a.fetch_candles_since("ETHUSDT", "1m", since)
        assert len(m1) >= 170 and m1["timestamp"].iloc[0] >= since
        assert (await a.get_last_price("ETHUSDT")) > 0
    asyncio.run(run())


# ---------------------------------------------------------------------------
# Telegram formatting
# ---------------------------------------------------------------------------
def _sig_dict(**kw):
    base = dict(id=7, symbol="BTCUSDT", side="LONG", entry_price=95350.0, entry_low=95200.0, entry_high=95500.0,
                sl_price=94100.0, tp1_price=96800.0, tp2_price=98200.0, tp3_price=100000.0, risk_reward=3.0,
                timestamp="2026-09-04T00:15:00", conviction_score=78, conditions=["rsi_oversold", "below_bb_lower"],
                htf_trend_1h="BULLISH", htf_trend_4h="NEUTRAL", rsi=27.3, atr=650.0, status="ACTIVE", outcome=None,
                tp_hits=0, exit_price=None, profit_loss_pct=None, profit_loss_r=None, closed_at=None)
    base.update(kw)
    return base


def test_format_signal_message(settings):
    msg = format_signal_message(_sig_dict(), settings)
    assert "NEW SIGNAL" in msg and "BTCUSDT" in msg and "LONG" in msg
    assert "$95,200.00 - $95,500.00" in msg
    assert "Stop Loss: $94,100.00" in msg and "TP3: $100,000.00" in msg
    assert "2026-09-04 00:15 UTC" in msg and "Conviction: 78%" in msg and "Risk:Reward = 1:3.0" in msg
    assert "RSI oversold" in msg
    small = format_signal_message(_sig_dict(symbol="DOGEUSDT", entry_price=0.3214, entry_low=0.32, entry_high=0.3228,
                                            sl_price=0.31, tp1_price=0.33, tp2_price=0.34, tp3_price=0.35), settings)
    assert "0.32000" in small  # sensible decimals for small prices


def test_format_tp_and_closed_and_summary():
    tp = format_tp_update(_sig_dict(), 1, 95350.0)
    assert "TP1 HIT" in tp and "break-even" in tp
    closed = format_closed_message(_sig_dict(status="TP_HIT", outcome="WIN", tp_hits=2, exit_price=96800.0,
                                             profit_loss_pct=3.21, profit_loss_r=1.2, closed_at="2026-09-04T05:15:00"))
    assert "WIN" in closed and "+3.21%" in closed and "5h 0m" in closed and "stop after TP2" in closed
    summary = format_daily_summary({"day": "2026-09-03", "opened": 3, "closed": {
        "closed_signals": 2, "total_wins": 1, "total_losses": 1, "total_breakeven": 0, "total_pnl_pct": 1.5, "win_rate": 50.0}},
        {"total_signals": 10, "active_signals": 2, "win_rate": 60.0, "profit_factor": None, "expectancy": 0.8, "total_pnl_pct": 12.0})
    assert "DAILY SUMMARY" in summary and "∞" in summary and "+12.00%" in summary


def test_notifier_disabled_without_token(settings):
    n = TelegramNotifier(settings)
    assert n.enabled is False
    assert asyncio.run(n.send_text("hello")) is None
    assert n.stats()["sent"] == 0


# ---------------------------------------------------------------------------
# Bot cycle end-to-end (synthetic data, in-memory DB)
# ---------------------------------------------------------------------------
def test_bot_cycle_generates_persists_and_notifies(settings, db):
    cfg = settings.with_overrides(trading_pairs=["BTCUSDT", "ETHUSDT"], notify_startup=False)
    notifier = RecordingNotifier()
    bot = SignalBot(cfg, db, collector=ForcedSignalCollector(cfg), notifier=notifier)

    async def run():
        await bot.collector.start(cfg.trading_pairs)
        summary = await bot.run_cycle()
        # second cycle on the same candle must not duplicate
        summary2 = await bot.run_cycle()
        return summary, summary2

    summary, summary2 = asyncio.run(run())
    assert "BTCUSDT" in summary["symbols"] and summary["symbols"]["BTCUSDT"].get("signal_id")
    assert summary["symbols"]["BTCUSDT"]["side"] == "LONG"
    assert ("signal", "BTCUSDT", "LONG") in notifier.messages
    assert summary2["symbols"]["BTCUSDT"].get("skipped") == "candle_already_processed"
    with db.session() as s:
        sigs = s.query(Signal).all()
        assert len(sigs) == 1
        sig = sigs[0]
        assert sig.status == SignalStatus.ACTIVE and sig.telegram_message_id == "42"
        assert sig.sl_price < sig.entry_price < sig.tp1_price < sig.tp2_price < sig.tp3_price
        assert sig.conviction_score >= cfg.min_conviction
        assert len(sig.events) == 1 and sig.events[0].event_type == "CREATED"
    assert "performance" in summary and summary["performance"]["active_signals"] == 1
    assert bot.status()["cycles_completed"] == 2
    assert bot.last_market["BTCUSDT"]["rsi"] < 30

    # forced re-evaluation of the same candle is blocked by the one-signal-per-symbol rule
    summary3 = asyncio.run(bot.run_cycle(force=True))
    assert "active_signal_exists" in summary3["symbols"]["BTCUSDT"].get("blocked", "")


def test_max_active_signals_rule(settings, db):
    cfg = settings.with_overrides(trading_pairs=["BTCUSDT"], max_active_signals=0, notify_startup=False)
    bot = SignalBot(cfg, db, collector=ForcedSignalCollector(cfg), notifier=RecordingNotifier())
    summary = asyncio.run(bot.run_cycle())
    assert "max_active_signals" in summary["symbols"]["BTCUSDT"].get("blocked", "")
    with db.session() as s:
        assert s.query(Signal).count() == 0


# ---------------------------------------------------------------------------
# FastAPI
# ---------------------------------------------------------------------------
def test_api_endpoints(settings):
    db = Database("sqlite:///:memory:")
    db.create_tables()
    cfg = settings.with_overrides(trading_pairs=["BTCUSDT", "ETHUSDT"], notify_startup=False, run_cycle_on_startup=False,
                                  admin_token="secret")
    notifier = RecordingNotifier()
    app = create_app(cfg, run_bot=True, db=db, collector=ForcedSignalCollector(cfg), notifier=notifier)
    with TestClient(app) as client:
        assert client.get("/health").status_code == 200
        assert client.get("/api/config").json()["trading_pairs"] == ["BTCUSDT", "ETHUSDT"]
        # admin protection
        assert client.post("/api/admin/run-cycle").status_code == 401
        r = client.post("/api/admin/run-cycle", headers={"X-Admin-Token": "secret"})
        assert r.status_code == 200 and r.json()["symbols"]["BTCUSDT"].get("signal_id")
        active = client.get("/api/signals/active").json()
        assert active["count"] == 1 and active["items"][0]["symbol"] == "BTCUSDT"
        assert "unrealised_pct" in active["items"][0]
        sid = active["items"][0]["id"]
        detail = client.get(f"/api/signals/{sid}").json()
        assert detail["events"][0]["event_type"] == "CREATED"
        assert client.get("/api/signals/999999").status_code == 404
        listing = client.get("/api/signals?status=ACTIVE&symbol=btcusdt").json()
        assert listing["total"] == 1
        perf = client.get("/api/performance").json()
        assert perf["total_signals"] == 1 and perf["active_signals"] == 1
        assert client.get("/api/performance/breakdown").json()["overall"]["active_signals"] == 1
        assert client.get("/api/performance/equity").json()["points"] == []
        status = client.get("/api/status").json()
        assert status["live"]["cycles_completed"] == 1 and status["active_signals"] == 1
        market = client.get("/api/market").json()
        assert "BTCUSDT" in market["items"] and "BTCUSDT" in market["evaluations"]
        mon = client.post("/api/admin/run-monitor?token=secret").json()
        assert mon["checked"] == 1
        assert client.get("/").status_code == 200
        assert client.get("/docs").status_code == 200
    db.dispose()


def test_telegram_notifier_sends_with_mocked_bot(settings):
    """Exercise the real send path (HTML parse mode, retry on network error) with a fake Bot."""
    from telegram.error import NetworkError, BadRequest

    class Msg:
        message_id = 777

    class FakeBot:
        def __init__(self):
            self.calls = []
            self.fail_first = True

        async def send_message(self, **kw):
            self.calls.append(kw)
            if self.fail_first:
                self.fail_first = False
                raise NetworkError("boom")
            if "BAD" in kw["text"]:
                raise BadRequest("chat not found")
            return Msg()

        async def get_me(self):
            class Me:
                username = "signal_bot"
            return Me()

        async def shutdown(self):
            pass

    cfg = settings.with_overrides(telegram_bot_token="123:abc", telegram_channel_id="-100123")
    import telegram_bot as tb
    orig_sleep = tb.asyncio.sleep

    async def no_sleep(_):
        pass

    tb.asyncio.sleep = no_sleep
    try:
        n = TelegramNotifier(cfg)
        assert n.enabled
        n.bot = FakeBot()
        mid = asyncio.run(n.send_signal(_sig_dict()))
        assert mid == "777" and n.sent == 1 and n.failed == 0
        assert n.bot.calls[-1]["parse_mode"] == "HTML" and n.bot.calls[-1]["chat_id"] == "-100123"
        assert asyncio.run(n.send_text("BAD")) is None and n.failed == 1 and "BadRequest" in n.last_error
        ok, info = asyncio.run(n.test_connection())
        assert ok and "signal_bot" in info
    finally:
        tb.asyncio.sleep = orig_sleep


# ---------------------------------------------------------------------------
# Telegram destination auto-discovery
# ---------------------------------------------------------------------------
class _Chat:
    def __init__(self, id, type, title=None, username=None, first_name=None):
        self.id, self.type, self.title, self.username, self.first_name = id, type, title, username, first_name


class _Upd:
    def __init__(self, update_id, message=None, channel_post=None, my_chat_member=None):
        self.update_id, self.message, self.channel_post, self.my_chat_member = update_id, message, channel_post, my_chat_member


class _Msg:
    def __init__(self, chat):
        self.chat = chat


class _MemberUpd:
    def __init__(self, chat, status):
        self.chat = chat
        self.new_chat_member = type("M", (), {"status": status})()


class _DiscoveryBot:
    def __init__(self, updates):
        self.updates = updates
        self.sent = []
        self.offsets = []

    async def get_updates(self, offset=None, **kw):
        self.offsets.append(offset)
        return [u for u in self.updates if offset is None or u.update_id >= offset]

    async def send_message(self, **kw):
        self.sent.append(kw)
        return type("R", (), {"message_id": len(self.sent)})()

    async def get_me(self):
        return type("Me", (), {"username": "my_signal_bot", "id": 1})()

    async def shutdown(self):
        pass


def test_telegram_discovers_channel_and_admin_chat(settings):
    """Token only: the channel where the bot became admin and the owner's DM are discovered and persisted."""
    persisted = []
    cfg = settings.with_overrides(telegram_bot_token="123:abc", telegram_channel_id="")
    n = TelegramNotifier(cfg, persist_callback=lambda c, a: persisted.append((c, a)))
    assert n.enabled and not n.ready and n.channel_id is None
    n.bot = _DiscoveryBot([
        _Upd(10, message=_Msg(_Chat(555, "private", username="owner"))),                    # owner pressed /start
        _Upd(11, my_chat_member=_MemberUpd(_Chat(-1001234, "channel", title="Signals"), "administrator")),
        _Upd(12, my_chat_member=_MemberUpd(_Chat(-1009999, "channel", title="Other"), "administrator")),  # ignored
    ])
    assert asyncio.run(n.discover_destinations()) is True
    assert n.channel_id == "-1001234" and n.admin_chat_id == "555" and n.ready
    assert persisted == [("-1001234", "555")]
    # signals go to the channel, admin messages to the DM
    assert asyncio.run(n.send_text("hello")) == "1" and n.bot.sent[-1]["chat_id"] == "-1001234"
    asyncio.run(n.send_admin("ops"))
    assert n.bot.sent[-1]["chat_id"] == "555"
    st = n.stats()
    assert st["ready"] and st["channel_id"] == "-1001234" and st["hint"] is None
    # once both destinations are known, no more polling happens
    asyncio.run(n.discover_destinations())
    assert n.bot.offsets == [None]


def test_telegram_waits_for_channel_and_guides_owner(settings):
    """Only a private /start seen: bot replies with instructions and keeps signals unsent (logged) until a channel appears."""
    cfg = settings.with_overrides(telegram_bot_token="123:abc", telegram_channel_id="")
    n = TelegramNotifier(cfg)
    n.bot = _DiscoveryBot([_Upd(1, message=_Msg(_Chat(777, "private", first_name="Ali")))])
    n.bot_username = "my_signal_bot"
    assert asyncio.run(n.discover_destinations()) is False
    assert n.admin_chat_id == "777" and n.channel_id is None
    assert n.bot.sent and n.bot.sent[-1]["chat_id"] == "777" and "administrator" in n.bot.sent[-1]["text"]
    assert "my_signal_bot" in n.discovery_hint
    assert asyncio.run(n.send_text("signal")) is None and n.failed == 0   # nothing sent, no failure counted
    # later the channel is created
    n.bot.updates.append(_Upd(2, channel_post=_Msg(_Chat(-100555, "channel", title="Crypto Signals"))))
    assert asyncio.run(n.discover_destinations()) is True
    assert n.channel_id == "-100555" and n.discovery_hint is None
    assert asyncio.run(n.send_text("signal")) == "2"


def test_explicit_channel_id_still_wins(settings):
    cfg = settings.with_overrides(telegram_bot_token="123:abc", telegram_channel_id="@public_channel")
    n = TelegramNotifier(cfg, channel_id="-100111")   # stored value must not override explicit env
    assert n.channel_id == "@public_channel" and n.ready
    n.bot = _DiscoveryBot([_Upd(1, channel_post=_Msg(_Chat(-100222, "channel")))])
    asyncio.run(n.discover_destinations())
    assert n.channel_id == "@public_channel"


def test_bot_persists_discovered_destinations(settings):
    """SignalBot stores discovered ids in bot_status and reuses them on the next start."""
    db = Database("sqlite:///:memory:")
    db.create_tables()
    cfg = settings.with_overrides(telegram_bot_token="123:abc", telegram_channel_id="", notify_startup=False,
                                  run_cycle_on_startup=False)
    bot = SignalBot(cfg, db, collector=ForcedSignalCollector(cfg))
    assert isinstance(bot.notifier, TelegramNotifier) and bot.notifier.channel_id is None
    bot.notifier.bot = _DiscoveryBot([_Upd(1, my_chat_member=_MemberUpd(_Chat(-100777, "channel", title="S"), "administrator"))])
    asyncio.run(bot.notifier.discover_destinations())
    with db.session() as session:
        row = db.get_or_create_status(session)
        assert row.telegram_channel_id == "-100777"
    bot2 = SignalBot(cfg, db, collector=ForcedSignalCollector(cfg))
    assert bot2.notifier.channel_id == "-100777" and bot2.notifier.ready
    db.dispose()
