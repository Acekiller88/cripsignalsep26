"""
SQLAlchemy models and connection management.

Tables
------
signals          – every generated signal with entry/SL/TP levels, lifecycle
                   status, outcome and realised PnL.
signal_events    – audit trail of what happened to a signal (TP1 hit, SL moved …).
performance      – single, continuously-updated row of aggregate statistics.
bot_status       – heartbeat row so the dashboard/API can tell whether the bot
                   is alive and when it last screened the market.

All timestamps are stored as *naive UTC* datetimes.
"""
from __future__ import annotations

import contextlib
import logging
from datetime import datetime
from typing import Iterator, Optional

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    create_engine,
    inspect,
    text,
)
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, relationship, sessionmaker
from sqlalchemy.pool import StaticPool

from utils import utcnow

logger = logging.getLogger("database")


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
class SignalStatus:
    ACTIVE = "ACTIVE"
    TP_HIT = "TP_HIT"      # closed after at least TP1 was reached
    SL_HIT = "SL_HIT"      # closed by the initial stop loss
    EXPIRED = "EXPIRED"    # closed at market after the expiry window
    CLOSED_STATUSES = (TP_HIT, SL_HIT, EXPIRED)
    ALL = (ACTIVE, TP_HIT, SL_HIT, EXPIRED)


class SignalOutcome:
    WIN = "WIN"
    LOSS = "LOSS"
    BREAKEVEN = "BREAKEVEN"


class Side:
    LONG = "LONG"
    SHORT = "SHORT"


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------
class Base(DeclarativeBase):
    pass


class Signal(Base):
    __tablename__ = "signals"

    id = Column(Integer, primary_key=True, autoincrement=True)
    symbol = Column(String(20), nullable=False, index=True)
    side = Column(String(5), nullable=False)  # LONG / SHORT
    timeframe = Column(String(5), nullable=False, default="15m")

    entry_price = Column(Float, nullable=False)
    entry_low = Column(Float)     # suggested entry zone (entry ± 0.25 ATR)
    entry_high = Column(Float)
    sl_price = Column(Float, nullable=False)       # initial stop loss
    current_sl = Column(Float)                     # stop after break-even / trailing moves
    tp1_price = Column(Float, nullable=False)
    tp2_price = Column(Float, nullable=False)
    tp3_price = Column(Float, nullable=False)
    risk_reward = Column(Float)                    # reward at TP3 / risk at SL

    timestamp = Column(DateTime, nullable=False, index=True)  # signal creation time (UTC)
    candle_time = Column(DateTime)                 # open time of the candle that triggered it
    status = Column(String(10), nullable=False, default=SignalStatus.ACTIVE, index=True)
    outcome = Column(String(10))                   # WIN / LOSS / BREAKEVEN
    profit_loss_pct = Column(Float)                # realised PnL in % of entry (unleveraged)
    profit_loss_r = Column(Float)                  # realised PnL in R multiples
    conviction_score = Column(Float)
    closed_at = Column(DateTime)
    exit_price = Column(Float)

    tp_hits = Column(Integer, nullable=False, default=0)   # 0..3
    tp1_hit_at = Column(DateTime)
    tp2_hit_at = Column(DateTime)
    tp3_hit_at = Column(DateTime)
    max_favorable_pct = Column(Float, default=0.0)  # best excursion while open
    max_adverse_pct = Column(Float, default=0.0)    # worst excursion while open
    last_checked_at = Column(DateTime)              # monitor bookmark

    # Indicator snapshot at signal time (for review / analytics)
    atr = Column(Float)
    rsi = Column(Float)
    macd = Column(Float)
    macd_signal = Column(Float)
    bb_upper = Column(Float)
    bb_lower = Column(Float)
    volume_ratio = Column(Float)
    htf_trend_1h = Column(String(10))
    htf_trend_4h = Column(String(10))
    conditions = Column(Text)   # comma separated list of triggered conditions
    reasons = Column(Text)      # human readable explanation

    telegram_message_id = Column(String(40))
    source = Column(String(20), default="binance")  # binance / synthetic / backtest

    events = relationship("SignalEvent", back_populates="signal", cascade="all, delete-orphan",
                          order_by="SignalEvent.created_at")

    __table_args__ = (
        Index("ix_signals_symbol_status", "symbol", "status"),
    )

    # ------------------------------------------------------------------
    @property
    def is_active(self) -> bool:
        return self.status == SignalStatus.ACTIVE

    @property
    def sl_distance_pct(self) -> float:
        return abs(self.entry_price - self.sl_price) / self.entry_price * 100.0

    def level_pct(self, price: float) -> float:
        """Signed % move from entry to `price` in the direction of the trade."""
        direction = 1.0 if self.side == Side.LONG else -1.0
        return direction * (price - self.entry_price) / self.entry_price * 100.0

    def condition_list(self) -> list:
        return [c for c in (self.conditions or "").split(",") if c]

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "symbol": self.symbol,
            "side": self.side,
            "timeframe": self.timeframe,
            "entry_price": self.entry_price,
            "entry_low": self.entry_low,
            "entry_high": self.entry_high,
            "sl_price": self.sl_price,
            "current_sl": self.current_sl,
            "tp1_price": self.tp1_price,
            "tp2_price": self.tp2_price,
            "tp3_price": self.tp3_price,
            "risk_reward": self.risk_reward,
            "timestamp": self.timestamp.isoformat() if self.timestamp else None,
            "candle_time": self.candle_time.isoformat() if self.candle_time else None,
            "status": self.status,
            "outcome": self.outcome,
            "profit_loss_pct": self.profit_loss_pct,
            "profit_loss_r": self.profit_loss_r,
            "conviction_score": self.conviction_score,
            "closed_at": self.closed_at.isoformat() if self.closed_at else None,
            "exit_price": self.exit_price,
            "tp_hits": self.tp_hits,
            "tp1_hit_at": self.tp1_hit_at.isoformat() if self.tp1_hit_at else None,
            "tp2_hit_at": self.tp2_hit_at.isoformat() if self.tp2_hit_at else None,
            "tp3_hit_at": self.tp3_hit_at.isoformat() if self.tp3_hit_at else None,
            "max_favorable_pct": self.max_favorable_pct,
            "max_adverse_pct": self.max_adverse_pct,
            "atr": self.atr,
            "rsi": self.rsi,
            "macd": self.macd,
            "macd_signal": self.macd_signal,
            "bb_upper": self.bb_upper,
            "bb_lower": self.bb_lower,
            "volume_ratio": self.volume_ratio,
            "htf_trend_1h": self.htf_trend_1h,
            "htf_trend_4h": self.htf_trend_4h,
            "conditions": self.condition_list(),
            "reasons": self.reasons,
            "source": self.source,
        }


class SignalEvent(Base):
    __tablename__ = "signal_events"

    id = Column(Integer, primary_key=True, autoincrement=True)
    signal_id = Column(Integer, ForeignKey("signals.id", ondelete="CASCADE"), nullable=False, index=True)
    event_type = Column(String(20), nullable=False)  # CREATED, TP1_HIT, TP2_HIT, TP3_HIT, SL_HIT, SL_MOVED, EXPIRED
    price = Column(Float)
    message = Column(Text)
    created_at = Column(DateTime, nullable=False, default=utcnow)

    signal = relationship("Signal", back_populates="events")

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "signal_id": self.signal_id,
            "event_type": self.event_type,
            "price": self.price,
            "message": self.message,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class Performance(Base):
    __tablename__ = "performance"

    id = Column(Integer, primary_key=True, autoincrement=True)
    total_signals = Column(Integer, default=0)      # all signals ever generated
    active_signals = Column(Integer, default=0)
    closed_signals = Column(Integer, default=0)
    total_wins = Column(Integer, default=0)
    total_losses = Column(Integer, default=0)
    total_breakeven = Column(Integer, default=0)
    win_rate = Column(Float, default=0.0)           # percent
    total_pnl_pct = Column(Float, default=0.0)
    gross_profit_pct = Column(Float, default=0.0)
    gross_loss_pct = Column(Float, default=0.0)
    profit_factor = Column(Float, default=0.0)
    expectancy = Column(Float, default=0.0)         # % per trade
    avg_win_pct = Column(Float, default=0.0)
    avg_loss_pct = Column(Float, default=0.0)
    avg_r = Column(Float, default=0.0)
    best_trade_pct = Column(Float, default=0.0)
    worst_trade_pct = Column(Float, default=0.0)
    max_drawdown_pct = Column(Float, default=0.0)
    current_streak = Column(Integer, default=0)     # >0 wins in a row, <0 losses in a row
    tp1_hit_rate = Column(Float, default=0.0)
    tp2_hit_rate = Column(Float, default=0.0)
    tp3_hit_rate = Column(Float, default=0.0)
    avg_duration_minutes = Column(Float, default=0.0)
    last_updated = Column(DateTime)

    def to_dict(self) -> dict:
        return {c.name: getattr(self, c.name) for c in self.__table__.columns if c.name != "last_updated"} | {
            "last_updated": self.last_updated.isoformat() if self.last_updated else None
        }


class BotStatus(Base):
    __tablename__ = "bot_status"

    id = Column(Integer, primary_key=True)
    started_at = Column(DateTime)
    last_heartbeat = Column(DateTime)
    last_cycle_started = Column(DateTime)
    last_cycle_finished = Column(DateTime)
    last_cycle_duration_s = Column(Float)
    next_cycle_at = Column(DateTime)
    last_monitor_at = Column(DateTime)
    cycles_completed = Column(Integer, default=0)
    signals_generated = Column(Integer, default=0)
    last_error = Column(Text)
    last_error_at = Column(DateTime)
    data_source = Column(String(20))
    websocket_connected = Column(Boolean, default=False)
    version = Column(String(20))
    # Telegram destinations discovered at runtime (survive container restarts)
    telegram_channel_id = Column(String(32))
    telegram_admin_chat_id = Column(String(32))

    def to_dict(self) -> dict:
        out = {}
        for c in self.__table__.columns:
            v = getattr(self, c.name)
            out[c.name] = v.isoformat() if isinstance(v, datetime) else v
        return out


# ---------------------------------------------------------------------------
# Engine / session management
# ---------------------------------------------------------------------------
class Database:
    """Owns the SQLAlchemy engine and hands out short-lived sessions."""

    def __init__(self, url: str, echo: bool = False):
        self.url = url
        self.engine: Engine = self._make_engine(url, echo)
        self.SessionLocal = sessionmaker(bind=self.engine, autoflush=False, expire_on_commit=False)

    @staticmethod
    def _make_engine(url: str, echo: bool) -> Engine:
        if url.startswith("sqlite"):
            connect_args = {"check_same_thread": False}
            if url in ("sqlite://", "sqlite:///:memory:"):
                return create_engine(url, echo=echo, connect_args=connect_args, poolclass=StaticPool, future=True)
            return create_engine(url, echo=echo, connect_args=connect_args, future=True)
        # PostgreSQL (or anything else): connection pool with health checks
        return create_engine(
            url,
            echo=echo,
            pool_size=5,
            max_overflow=10,
            pool_pre_ping=True,
            pool_recycle=1800,
            future=True,
        )

    # ------------------------------------------------------------------
    def create_tables(self) -> None:
        Base.metadata.create_all(self.engine)
        self._migrate()

    def _migrate(self) -> None:
        """Very small forward-only migration: add columns missing from old installs."""
        inspector = inspect(self.engine)
        for table in Base.metadata.sorted_tables:
            if not inspector.has_table(table.name):
                continue
            existing = {col["name"] for col in inspector.get_columns(table.name)}
            for column in table.columns:
                if column.name in existing:
                    continue
                col_type = column.type.compile(dialect=self.engine.dialect)
                ddl = f'ALTER TABLE {table.name} ADD COLUMN {column.name} {col_type}'
                logger.info("Migrating schema: %s", ddl)
                with self.engine.begin() as conn:
                    conn.execute(text(ddl))

    def drop_tables(self) -> None:
        Base.metadata.drop_all(self.engine)

    def ping(self) -> bool:
        try:
            with self.engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            return True
        except Exception as exc:  # pragma: no cover - depends on infra
            logger.error("Database ping failed: %s", exc)
            return False

    def dispose(self) -> None:
        self.engine.dispose()

    @contextlib.contextmanager
    def session(self) -> Iterator[Session]:
        """Transactional scope: commits on success, rolls back on error."""
        session: Session = self.SessionLocal()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    # ------------------------------------------------------------------
    # Convenience helpers used by several modules
    # ------------------------------------------------------------------
    def get_or_create_status(self, session: Session) -> BotStatus:
        status = session.get(BotStatus, 1)
        if status is None:
            status = BotStatus(id=1)
            session.add(status)
            session.flush()
        return status

    def add_event(self, session: Session, signal: Signal, event_type: str,
                  price: Optional[float] = None, message: str = "",
                  created_at: Optional[datetime] = None) -> SignalEvent:
        event = SignalEvent(
            signal_id=signal.id, event_type=event_type, price=price,
            message=message, created_at=created_at or utcnow(),
        )
        session.add(event)
        return event


# ---------------------------------------------------------------------------
# Module-level default instance (lazy) – convenient for scripts/dashboard
# ---------------------------------------------------------------------------
_default_db: Optional[Database] = None


def get_database(url: Optional[str] = None) -> Database:
    """Return the process-wide Database, creating it (and the tables) on first use."""
    global _default_db
    if _default_db is None:
        if url is None:
            from config import settings
            url = settings.database_url
        _default_db = Database(url)
        _default_db.create_tables()
    return _default_db


def set_database(db: Database) -> None:
    global _default_db
    _default_db = db
