import os
import sys
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
import pytest

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("DATA_SOURCE", "synthetic")
os.environ.setdefault("LOG_LEVEL", "WARNING")
os.environ["TELEGRAM_BOT_TOKEN"] = ""
os.environ["TELEGRAM_CHANNEL_ID"] = ""

from config import load_settings  # noqa: E402
from database import Database  # noqa: E402


@pytest.fixture
def settings():
    return load_settings()


@pytest.fixture
def db():
    """Fresh in-memory SQLite database (or TEST_DATABASE_URL, e.g. PostgreSQL)."""
    url = os.getenv("TEST_DATABASE_URL", "sqlite:///:memory:")
    database = Database(url)
    database.drop_tables()
    database.create_tables()
    yield database
    database.drop_tables()
    database.dispose()


def make_ohlcv(n: int = 300, start_price: float = 100.0, seed: int = 7, tf_minutes: int = 15,
               end: datetime | None = None, drift: float = 0.0, vol: float = 0.004) -> pd.DataFrame:
    """Random-walk OHLCV frame with closed candles ending just before `end`."""
    rng = np.random.default_rng(seed)
    rets = rng.normal(drift, vol, n)
    close = start_price * np.exp(np.cumsum(rets))
    open_ = np.concatenate([[start_price], close[:-1]])
    spread = np.abs(rng.normal(0, vol, n)) * close
    high = np.maximum(open_, close) + spread
    low = np.minimum(open_, close) - spread
    volume = rng.lognormal(10, 0.3, n)
    end = end or datetime.utcnow().replace(second=0, microsecond=0)
    end = end - timedelta(minutes=end.minute % tf_minutes)
    ts = [end - timedelta(minutes=tf_minutes * (n - i)) for i in range(n)]
    return pd.DataFrame({"timestamp": ts, "open": open_, "high": high, "low": low, "close": close, "volume": volume})
