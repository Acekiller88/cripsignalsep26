"""
Central configuration for the Crypto Signal Bot.

All values are read from environment variables (a `.env` file in the repository
root or in `backend/` is loaded automatically). Every setting has a sensible
default so the bot can start with nothing more than a database URL.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import List

from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# .env loading: existing environment variables always take precedence.
# ---------------------------------------------------------------------------
_BACKEND_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _BACKEND_DIR.parent
for _candidate in (_REPO_ROOT / ".env", _BACKEND_DIR / ".env"):
    if _candidate.exists():
        load_dotenv(_candidate, override=False)
load_dotenv(override=False)  # also honour a .env in the current working directory

APP_VERSION = "1.0.0"


# ---------------------------------------------------------------------------
# Environment parsing helpers
# ---------------------------------------------------------------------------
def _env_str(name: str, default: str = "") -> str:
    value = os.getenv(name)
    return default if value is None or value.strip() == "" else value.strip()


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None or value.strip() == "":
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def _env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    try:
        return int(value) if value not in (None, "") else default
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    value = os.getenv(name)
    try:
        return float(value) if value not in (None, "") else default
    except ValueError:
        return default


def _env_list(name: str, default: List[str]) -> List[str]:
    value = os.getenv(name)
    if value is None or value.strip() == "":
        return list(default)
    return [item.strip().upper() for item in value.split(",") if item.strip()]


def _env_int_list(name: str, default: List[int]) -> List[int]:
    value = os.getenv(name)
    if value is None or value.strip() == "":
        return list(default)
    out: List[int] = []
    for item in value.split(","):
        item = item.strip()
        if item:
            out.append(int(item))
    return out or list(default)


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Settings:
    # --- Exchange / market data -------------------------------------------
    binance_api_key: str = ""
    binance_secret: str = ""
    binance_testnet: bool = True
    # "binance" (real exchange, testnet or live) or "synthetic" (offline generator
    # used for local testing / CI when the exchange is unreachable).
    data_source: str = "binance"
    enable_websocket: bool = True
    exchange_timeout_ms: int = 20_000

    # --- Database -----------------------------------------------------------
    database_url: str = "postgresql://crypto_user:crypto_password_123@localhost:5432/crypto_signals"

    # --- Telegram -----------------------------------------------------------
    telegram_bot_token: str = ""
    telegram_channel_id: str = ""
    notify_tp_updates: bool = True
    notify_startup: bool = True
    daily_summary_hour_utc: int = 0  # -1 disables the daily summary

    # --- Trading universe ---------------------------------------------------
    trading_pairs: List[str] = field(
        default_factory=lambda: ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "DOGEUSDT"]
    )
    timeframe: str = "15m"
    confirmation_timeframes: List[str] = field(default_factory=lambda: ["1h", "4h"])
    screening_interval: int = 900  # seconds; normally equals the timeframe length
    candle_close_delay_seconds: int = 8  # wait a few seconds after candle close before fetching
    kline_limit: int = 300  # candles fetched per timeframe for indicator warm-up
    run_cycle_on_startup: bool = True

    # --- Indicator parameters ------------------------------------------------
    rsi_period: int = 14
    rsi_oversold: float = 30.0
    rsi_overbought: float = 70.0
    macd_fast: int = 12
    macd_slow: int = 26
    macd_signal: int = 9
    bb_period: int = 20
    bb_std: float = 2.0
    atr_period: int = 14
    ema_periods: List[int] = field(default_factory=lambda: [9, 21, 50])
    volume_avg_period: int = 20
    volume_spike_multiplier: float = 1.5

    # --- Signal logic -------------------------------------------------------
    min_conditions: int = 2  # minimum primary conditions (out of 3)
    macd_cross_lookback: int = 3  # crossover must have happened within the last N closed candles
    min_conviction: float = 40.0  # signals below this conviction are discarded (see signal_engine._conviction)
    require_htf_confirmation: bool = False  # hard-require the 1h trend to agree with the signal

    # --- Risk management ----------------------------------------------------
    sl_atr_mult: float = 2.0
    tp1_atr_mult: float = 2.0
    tp2_atr_mult: float = 4.0
    tp3_atr_mult: float = 6.0
    move_sl_to_breakeven_after_tp1: bool = True
    max_active_signals: int = 10
    one_signal_per_symbol: bool = True
    signal_cooldown_minutes: int = 60  # after a signal closes, wait before a new one on the same symbol
    signal_expiry_hours: int = 48
    risk_per_trade: float = 0.02  # used for the position-size hint in Telegram messages

    # --- Monitoring ---------------------------------------------------------
    monitor_interval: int = 60  # seconds between TP/SL checks

    # --- Application --------------------------------------------------------
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    log_level: str = "INFO"
    admin_token: str = ""  # protects the manual-trigger endpoints when set
    app_version: str = APP_VERSION

    # ---------------------------------------------------------------------
    @property
    def timeframe_seconds(self) -> int:
        from utils import timeframe_to_seconds  # local import avoids a cycle

        return timeframe_to_seconds(self.timeframe)

    @property
    def telegram_enabled(self) -> bool:
        return bool(self.telegram_bot_token and self.telegram_channel_id)

    @property
    def is_synthetic(self) -> bool:
        return self.data_source.lower() == "synthetic"

    def with_overrides(self, **kwargs) -> "Settings":
        """Return a copy with some fields replaced (handy for tests)."""
        return replace(self, **kwargs)

    def public_dict(self) -> dict:
        """Configuration summary safe to expose via the API (no secrets)."""
        return {
            "version": self.app_version,
            "data_source": self.data_source,
            "binance_testnet": self.binance_testnet,
            "websocket_enabled": self.enable_websocket,
            "trading_pairs": list(self.trading_pairs),
            "timeframe": self.timeframe,
            "confirmation_timeframes": list(self.confirmation_timeframes),
            "screening_interval": self.screening_interval,
            "monitor_interval": self.monitor_interval,
            "telegram_enabled": self.telegram_enabled,
            "strategy": {
                "rsi": {"period": self.rsi_period, "oversold": self.rsi_oversold, "overbought": self.rsi_overbought},
                "macd": {"fast": self.macd_fast, "slow": self.macd_slow, "signal": self.macd_signal,
                         "cross_lookback": self.macd_cross_lookback},
                "bollinger": {"period": self.bb_period, "std": self.bb_std},
                "atr": {"period": self.atr_period},
                "ema": list(self.ema_periods),
                "min_conditions": self.min_conditions,
                "min_conviction": self.min_conviction,
                "require_htf_confirmation": self.require_htf_confirmation,
            },
            "risk": {
                "sl_atr_mult": self.sl_atr_mult,
                "tp_atr_mults": [self.tp1_atr_mult, self.tp2_atr_mult, self.tp3_atr_mult],
                "move_sl_to_breakeven_after_tp1": self.move_sl_to_breakeven_after_tp1,
                "max_active_signals": self.max_active_signals,
                "one_signal_per_symbol": self.one_signal_per_symbol,
                "signal_cooldown_minutes": self.signal_cooldown_minutes,
                "signal_expiry_hours": self.signal_expiry_hours,
                "risk_per_trade": self.risk_per_trade,
            },
        }


def load_settings() -> Settings:
    """Build a Settings object from the environment."""
    timeframe = _env_str("TIMEFRAME", "15m")
    from utils import timeframe_to_seconds

    default_interval = timeframe_to_seconds(timeframe)
    return Settings(
        binance_api_key=_env_str("BINANCE_API_KEY"),
        binance_secret=_env_str("BINANCE_SECRET"),
        binance_testnet=_env_bool("BINANCE_TESTNET", True),
        data_source=_env_str("DATA_SOURCE", "binance").lower(),
        enable_websocket=_env_bool("ENABLE_WEBSOCKET", True),
        exchange_timeout_ms=_env_int("EXCHANGE_TIMEOUT_MS", 20_000),
        database_url=_env_str(
            "DATABASE_URL", "postgresql://crypto_user:crypto_password_123@localhost:5432/crypto_signals"
        ),
        telegram_bot_token=_env_str("TELEGRAM_BOT_TOKEN"),
        telegram_channel_id=_env_str("TELEGRAM_CHANNEL_ID"),
        notify_tp_updates=_env_bool("NOTIFY_TP_UPDATES", True),
        notify_startup=_env_bool("NOTIFY_STARTUP", True),
        daily_summary_hour_utc=_env_int("DAILY_SUMMARY_HOUR_UTC", 0),
        trading_pairs=_env_list("TRADING_PAIRS", ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "DOGEUSDT"]),
        timeframe=timeframe,
        confirmation_timeframes=[tf.lower() for tf in _env_list("CONFIRMATION_TIMEFRAMES", ["1h", "4h"])],
        screening_interval=_env_int("SCREENING_INTERVAL", default_interval),
        candle_close_delay_seconds=_env_int("CANDLE_CLOSE_DELAY_SECONDS", 8),
        kline_limit=_env_int("KLINE_LIMIT", 300),
        run_cycle_on_startup=_env_bool("RUN_CYCLE_ON_STARTUP", True),
        rsi_period=_env_int("RSI_PERIOD", 14),
        rsi_oversold=_env_float("RSI_OVERSOLD", 30.0),
        rsi_overbought=_env_float("RSI_OVERBOUGHT", 70.0),
        macd_fast=_env_int("MACD_FAST", 12),
        macd_slow=_env_int("MACD_SLOW", 26),
        macd_signal=_env_int("MACD_SIGNAL", 9),
        bb_period=_env_int("BB_PERIOD", 20),
        bb_std=_env_float("BB_STD", 2.0),
        atr_period=_env_int("ATR_PERIOD", 14),
        ema_periods=_env_int_list("EMA_PERIODS", [9, 21, 50]),
        volume_avg_period=_env_int("VOLUME_AVG_PERIOD", 20),
        volume_spike_multiplier=_env_float("VOLUME_SPIKE_MULTIPLIER", 1.5),
        min_conditions=_env_int("MIN_CONDITIONS", 2),
        macd_cross_lookback=_env_int("MACD_CROSS_LOOKBACK", 3),
        min_conviction=_env_float("MIN_CONVICTION", 40.0),
        require_htf_confirmation=_env_bool("REQUIRE_HTF_CONFIRMATION", False),
        sl_atr_mult=_env_float("SL_ATR_MULT", 2.0),
        tp1_atr_mult=_env_float("TP1_ATR_MULT", 2.0),
        tp2_atr_mult=_env_float("TP2_ATR_MULT", 4.0),
        tp3_atr_mult=_env_float("TP3_ATR_MULT", 6.0),
        move_sl_to_breakeven_after_tp1=_env_bool("MOVE_SL_TO_BREAKEVEN_AFTER_TP1", True),
        max_active_signals=_env_int("MAX_ACTIVE_SIGNALS", 10),
        one_signal_per_symbol=_env_bool("ONE_SIGNAL_PER_SYMBOL", True),
        signal_cooldown_minutes=_env_int("SIGNAL_COOLDOWN_MINUTES", 60),
        signal_expiry_hours=_env_int("SIGNAL_EXPIRY_HOURS", 48),
        risk_per_trade=_env_float("RISK_PER_TRADE", 0.02),
        monitor_interval=_env_int("MONITOR_INTERVAL", 60),
        api_host=_env_str("API_HOST", "0.0.0.0"),
        api_port=_env_int("API_PORT", 8000),
        log_level=_env_str("LOG_LEVEL", "INFO").upper(),
        admin_token=_env_str("ADMIN_TOKEN"),
    )


settings: Settings = load_settings()

# Backwards-compatible module-level constants (as referenced in the project brief)
BINANCE_API_KEY = settings.binance_api_key
BINANCE_SECRET = settings.binance_secret
BINANCE_TESTNET = settings.binance_testnet
DATABASE_URL = settings.database_url
TELEGRAM_BOT_TOKEN = settings.telegram_bot_token
TELEGRAM_CHANNEL_ID = settings.telegram_channel_id
TRADING_PAIRS = settings.trading_pairs
TIMEFRAME = settings.timeframe
SCREENING_INTERVAL = settings.screening_interval
MAX_ACTIVE_SIGNALS = settings.max_active_signals
RISK_PER_TRADE = settings.risk_per_trade
