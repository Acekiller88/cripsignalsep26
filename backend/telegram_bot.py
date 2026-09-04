"""
Telegram notifications (python-telegram-bot v21+/v22, async).

Messages are sent with HTML parse mode – far less escaping trouble than
Markdown.  Sending is fire-and-forget with retries; a Telegram outage never
blocks signal generation.  When the bot token / channel id are missing the
notifier runs in "disabled" mode and only logs the messages.
"""
from __future__ import annotations

import asyncio
import html
import logging
from datetime import datetime
from typing import Callable, Optional, Tuple

from config import Settings
from utils import fmt_pct, fmt_price

logger = logging.getLogger("telegram")


def _esc(value) -> str:
    return html.escape(str(value), quote=False)


def _ts(value) -> str:
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value)
        except ValueError:
            return value
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M UTC")
    return "-"


# ---------------------------------------------------------------------------
# Message formatting (pure functions – unit tested)
# ---------------------------------------------------------------------------
def format_signal_message(sig: dict, settings: Optional[Settings] = None) -> str:
    """Format a new-signal announcement. `sig` is `Signal.to_dict()` (or a compatible dict)."""
    side = sig["side"]
    side_icon = "📈" if side == "LONG" else "📉"
    entry = float(sig["entry_price"])
    d = 2 if entry >= 1000 else None  # decimals chosen by magnitude otherwise
    sl_pct = abs(entry - float(sig["sl_price"])) / entry * 100.0
    tp_pcts = [abs(float(sig[k]) - entry) / entry * 100.0 for k in ("tp1_price", "tp2_price", "tp3_price")]
    rr = sig.get("risk_reward") or (tp_pcts[2] / sl_pct if sl_pct else 0)
    lines = [
        "🔔 <b>NEW SIGNAL</b> 🔔",
        "",
        f"📊 Symbol: <b>{_esc(sig['symbol'])}</b>",
        f"{side_icon} Side: <b>{_esc(side)}</b>",
    ]
    if sig.get("entry_low") and sig.get("entry_high"):
        lines.append(f"📍 Entry: ${fmt_price(sig['entry_low'], d)} - ${fmt_price(sig['entry_high'], d)}")
    else:
        lines.append(f"📍 Entry: ${fmt_price(entry, d)}")
    lines += [
        f"🛑 Stop Loss: ${fmt_price(sig['sl_price'], d)}  (-{sl_pct:.2f}%)",
        f"🎯 TP1: ${fmt_price(sig['tp1_price'], d)}  (+{tp_pcts[0]:.2f}%)",
        f"🎯 TP2: ${fmt_price(sig['tp2_price'], d)}  (+{tp_pcts[1]:.2f}%)",
        f"🎯 TP3: ${fmt_price(sig['tp3_price'], d)}  (+{tp_pcts[2]:.2f}%)",
        f"⏰ Time: {_ts(sig.get('timestamp'))}",
        f"⚡ Conviction: {float(sig.get('conviction_score') or 0):.0f}%",
        f"📊 Risk:Reward = 1:{rr:.1f}",
    ]
    conds = sig.get("conditions") or []
    if isinstance(conds, str):
        conds = [c for c in conds.split(",") if c]
    if conds:
        pretty = {
            "rsi_oversold": "RSI oversold", "rsi_overbought": "RSI overbought",
            "macd_bullish_cross": "MACD bullish cross", "macd_bearish_cross": "MACD bearish cross",
            "below_bb_lower": "Below lower BB", "above_bb_upper": "Above upper BB",
        }
        lines += ["", "🧠 Setup: " + _esc(", ".join(pretty.get(c, c) for c in conds))]
    trend_1h, trend_4h = sig.get("htf_trend_1h"), sig.get("htf_trend_4h")
    if trend_1h or trend_4h:
        lines.append(f"📐 Trend: 1h {_esc(str(trend_1h or '-').title())} · 4h {_esc(str(trend_4h or '-').title())}")
    if sig.get("rsi") is not None:
        lines.append(f"📉 RSI: {float(sig['rsi']):.1f} · ATR: {fmt_price(sig.get('atr'), d)}")
    if settings is not None and settings.risk_per_trade:
        lines += ["", f"💡 Risk {settings.risk_per_trade * 100:.1f}% of equity → position ≈ "
                      f"{settings.risk_per_trade * 100 / sl_pct:.2f}× equity (SL {sl_pct:.2f}%)"
                  if sl_pct else ""]
    lines += ["", f"#{_esc(sig['symbol'])} #{_esc(side)} #signal{sig.get('id', '')}"]
    return "\n".join(l for l in lines if l is not None)


def format_tp_update(sig: dict, level: int, new_sl: Optional[float]) -> str:
    entry = float(sig["entry_price"])
    d = 2 if entry >= 1000 else None
    price = float(sig[f"tp{level}_price"])
    pct = abs(price - entry) / entry * 100.0
    lines = [
        f"✅ <b>TP{level} HIT</b> — {_esc(sig['symbol'])} {_esc(sig['side'])}",
        f"🎯 TP{level}: ${fmt_price(price, d)}  (+{pct:.2f}% from entry ${fmt_price(entry, d)})",
    ]
    if level < 3:
        lines.append(f"📦 1/3 position closed, {3 - level}/3 still running")
    if new_sl is not None:
        label = "break-even" if abs(new_sl - entry) < 1e-12 else fmt_price(new_sl, d)
        lines.append(f"🔒 Stop moved to {label}")
    lines.append(f"#{_esc(sig['symbol'])} #signal{sig.get('id', '')}")
    return "\n".join(lines)


def format_closed_message(sig: dict) -> str:
    entry = float(sig["entry_price"])
    d = 2 if entry >= 1000 else None
    status = sig.get("status")
    outcome = sig.get("outcome")
    pnl = sig.get("profit_loss_pct")
    r = sig.get("profit_loss_r")
    if outcome == "WIN":
        head = "🏆 <b>SIGNAL CLOSED — WIN</b>"
    elif outcome == "LOSS":
        head = "❌ <b>SIGNAL CLOSED — LOSS</b>"
    else:
        head = "➖ <b>SIGNAL CLOSED — BREAK-EVEN</b>"
    reason = {"TP_HIT": "take-profit", "SL_HIT": "stop loss", "EXPIRED": "expired (time stop)"}.get(status, status)
    if status == "TP_HIT" and (sig.get("tp_hits") or 0) < 3:
        reason = f"stop after TP{sig.get('tp_hits')}"
    lines = [
        head,
        f"📊 {_esc(sig['symbol'])} {_esc(sig['side'])} · signal #{sig.get('id', '')}",
        f"📍 Entry ${fmt_price(entry, d)} → Exit ${fmt_price(sig.get('exit_price'), d)} ({_esc(reason)})",
        f"🎯 Targets hit: {sig.get('tp_hits', 0)}/3",
        f"💰 Result: <b>{fmt_pct(pnl)}</b>" + (f" ({float(r):+.2f}R)" if r is not None else ""),
    ]
    if sig.get("timestamp") and sig.get("closed_at"):
        try:
            t0 = datetime.fromisoformat(sig["timestamp"])
            t1 = datetime.fromisoformat(sig["closed_at"])
            mins = int((t1 - t0).total_seconds() // 60)
            lines.append(f"⏱ Duration: {mins // 60}h {mins % 60}m")
        except ValueError:
            pass
    lines.append(f"#{_esc(sig['symbol'])} #closed")
    return "\n".join(lines)


def format_daily_summary(summary: dict, overall: Optional[dict]) -> str:
    c = summary["closed"]
    lines = [
        f"📅 <b>DAILY SUMMARY — {summary['day']}</b>",
        "",
        f"🆕 Signals opened: {summary['opened']}",
        f"🏁 Signals closed: {c['closed_signals']} (W {c['total_wins']} / L {c['total_losses']} / BE {c['total_breakeven']})",
        f"📈 Day PnL: <b>{fmt_pct(c['total_pnl_pct'])}</b>",
        f"🎯 Win rate: {c['win_rate']:.1f}%",
    ]
    if overall:
        pf = overall.get("profit_factor")
        pf_txt = "∞" if pf is None or pf >= 999 else f"{pf:.2f}"
        lines += [
            "",
            "<b>All-time</b>",
            f"• Signals: {overall.get('total_signals', 0)} (active {overall.get('active_signals', 0)})",
            f"• Win rate: {overall.get('win_rate', 0):.1f}%",
            f"• Profit factor: {pf_txt}",
            f"• Expectancy: {fmt_pct(overall.get('expectancy'))} / trade",
            f"• Total PnL: <b>{fmt_pct(overall.get('total_pnl_pct'))}</b>",
        ]
    return "\n".join(lines)


def format_startup_message(settings: Settings, source_info: str) -> str:
    mode = "SYNTHETIC (offline demo data)" if settings.is_synthetic else (
        "Binance Futures TESTNET" if settings.binance_testnet else "Binance Futures LIVE")
    return "\n".join([
        f"🤖 <b>Crypto Signal Bot v{settings.app_version} online</b>",
        f"🌐 Data: {_esc(mode)}",
        f"📊 Pairs: {_esc(', '.join(settings.trading_pairs))}",
        f"⏱ Timeframe: {_esc(settings.timeframe)} (confirm: {_esc(', '.join(settings.confirmation_timeframes))})",
        f"🎯 Strategy: RSI/MACD/Bollinger ≥{settings.min_conditions}/3 · SL {settings.sl_atr_mult:g} ATR · "
        f"TP {settings.tp1_atr_mult:g}/{settings.tp2_atr_mult:g}/{settings.tp3_atr_mult:g} ATR",
        f"ℹ️ {_esc(source_info)}",
    ])


# ---------------------------------------------------------------------------
# Notifier
# ---------------------------------------------------------------------------
class TelegramNotifier:
    """Sends messages to the signal channel (and optionally to the owner's private chat).

    Destinations: `TELEGRAM_CHANNEL_ID` / `TELEGRAM_ADMIN_CHAT_ID` from the
    environment, or – when they are empty – discovered automatically from the
    bot's pending updates: the first channel the bot was made administrator of
    becomes the signal channel, the first private chat that sent `/start`
    becomes the admin chat.  Discovered ids are persisted through
    `persist_callback` (bot_status table) so they survive restarts.
    """

    def __init__(self, settings: Settings, channel_id: Optional[str] = None, admin_chat_id: Optional[str] = None,
                 persist_callback: Optional[Callable[[Optional[str], Optional[str]], None]] = None):
        self.s = settings
        self.enabled = settings.telegram_enabled
        self.bot = None
        self.sent = 0
        self.failed = 0
        self.last_error: Optional[str] = None
        self.channel_id: Optional[str] = settings.telegram_channel_id or channel_id or None
        self.admin_chat_id: Optional[str] = settings.telegram_admin_chat_id or admin_chat_id or None
        self.bot_username: Optional[str] = None
        self.discovery_hint: Optional[str] = None
        self._persist = persist_callback
        self._update_offset: Optional[int] = None
        self._lock = asyncio.Lock()
        if self.enabled:
            try:
                from telegram import Bot
                from telegram.request import HTTPXRequest

                request = HTTPXRequest(connection_pool_size=8, connect_timeout=15.0, read_timeout=20.0,
                                       write_timeout=20.0, pool_timeout=10.0)
                self.bot = Bot(token=settings.telegram_bot_token, request=request)
            except Exception as exc:  # pragma: no cover
                logger.error("Could not initialise Telegram bot: %s", exc)
                self.enabled = False
        else:
            logger.warning("Telegram disabled (TELEGRAM_BOT_TOKEN not set) — messages are logged only")

    # ------------------------------------------------------------------
    # Destination discovery
    # ------------------------------------------------------------------
    @property
    def ready(self) -> bool:
        return self.enabled and self.bot is not None and bool(self.channel_id)

    async def discover_destinations(self) -> bool:
        """Look at pending updates for a channel / private chat. Returns True when the channel is known."""
        if not self.enabled or self.bot is None:
            return False
        if self.channel_id and self.admin_chat_id:
            return True
        try:
            updates = await self.bot.get_updates(offset=self._update_offset, timeout=0, read_timeout=15.0,
                                                 allowed_updates=["message", "channel_post", "my_chat_member"])
        except Exception as exc:
            self.last_error = f"{type(exc).__name__}: {exc}"
            logger.warning("Telegram getUpdates failed: %s", str(exc)[:160])
            return bool(self.channel_id)
        found_channel = found_admin = False
        for upd in updates:
            self._update_offset = upd.update_id + 1
            chat = None
            if upd.my_chat_member is not None:
                status = getattr(upd.my_chat_member.new_chat_member, "status", "")
                if status in ("administrator", "member", "creator"):
                    chat = upd.my_chat_member.chat
            elif upd.channel_post is not None:
                chat = upd.channel_post.chat
            elif upd.message is not None:
                chat = upd.message.chat
            if chat is None:
                continue
            if chat.type == "channel" and not self.channel_id:
                self.channel_id = str(chat.id)
                found_channel = True
                logger.info("Telegram: discovered signal channel %s (%s)", chat.id, chat.title)
            elif chat.type == "private" and not self.admin_chat_id:
                self.admin_chat_id = str(chat.id)
                found_admin = True
                logger.info("Telegram: discovered admin chat %s (%s)", chat.id, chat.username or chat.first_name)
            elif chat.type in ("group", "supergroup") and not self.channel_id:
                # a group works as a signal destination too
                self.channel_id = str(chat.id)
                found_channel = True
                logger.info("Telegram: discovered signal group %s (%s)", chat.id, chat.title)
        if (found_channel or found_admin) and self._persist is not None:
            try:
                self._persist(self.channel_id, self.admin_chat_id)
            except Exception as exc:  # pragma: no cover
                logger.warning("Could not persist Telegram destinations: %s", exc)
        if found_admin and not found_channel and self.admin_chat_id and not self.channel_id:
            await self.send_text(
                "👋 Hi! I'm your Crypto Signal Bot.\n\nTo receive signals, create a channel (or group), add me as "
                "<b>administrator</b> with permission to post, and I'll start posting there automatically within a minute.",
                chat_id=self.admin_chat_id)
        if not self.channel_id:
            me = self.bot_username or "your bot"
            self.discovery_hint = (f"waiting for a channel: add @{me} as administrator of a Telegram channel "
                                   f"(or set TELEGRAM_CHANNEL_ID)")
        else:
            self.discovery_hint = None
        return bool(self.channel_id)

    # ------------------------------------------------------------------
    async def send_text(self, text: str, disable_notification: bool = False,
                        chat_id: Optional[str] = None) -> Optional[str]:
        """Send an HTML message to the channel (or `chat_id`). Returns the message id (or None)."""
        if not self.enabled or self.bot is None:
            logger.info("[telegram:disabled] %s", text.replace("\n", " | ")[:300])
            return None
        target = chat_id or self.channel_id
        if not target:
            logger.info("[telegram:no-channel-yet] %s", text.replace("\n", " | ")[:300])
            return None
        from telegram.error import RetryAfter, TimedOut, NetworkError, TelegramError

        delay = 2.0
        async with self._lock:  # serialise sends to respect channel rate limits
            for attempt in range(1, 5):
                try:
                    msg = await self.bot.send_message(
                        chat_id=target, text=text, parse_mode="HTML",
                        disable_web_page_preview=True, disable_notification=disable_notification,
                    )
                    self.sent += 1
                    self.last_error = None
                    return str(msg.message_id)
                except RetryAfter as exc:
                    wait = float(getattr(exc, "retry_after", delay)) + 1.0
                    logger.warning("Telegram flood control: waiting %.0fs", wait)
                    await asyncio.sleep(wait)
                except (TimedOut, NetworkError) as exc:
                    self.last_error = f"{type(exc).__name__}: {exc}"
                    logger.warning("Telegram network error (attempt %d/4): %s", attempt, exc)
                    await asyncio.sleep(delay)
                    delay = min(delay * 2, 30.0)
                except TelegramError as exc:
                    # Bad request (e.g. wrong chat id / HTML error) – retrying won't help
                    self.failed += 1
                    self.last_error = f"{type(exc).__name__}: {exc}"
                    logger.error("Telegram error: %s", exc)
                    return None
        self.failed += 1
        return None

    async def send_signal(self, sig: dict) -> Optional[str]:
        return await self.send_text(format_signal_message(sig, self.s))

    async def send_tp_update(self, sig: dict, level: int, new_sl: Optional[float]) -> Optional[str]:
        return await self.send_text(format_tp_update(sig, level, new_sl))

    async def send_closed(self, sig: dict) -> Optional[str]:
        return await self.send_text(format_closed_message(sig))

    async def send_daily_summary(self, summary: dict, overall: Optional[dict]) -> Optional[str]:
        return await self.send_text(format_daily_summary(summary, overall), disable_notification=True)

    async def send_startup(self, source_info: str) -> Optional[str]:
        text = format_startup_message(self.s, source_info)
        mid = await self.send_text(text, disable_notification=True)
        if self.admin_chat_id and self.admin_chat_id != self.channel_id:
            await self.send_text(text, disable_notification=True, chat_id=self.admin_chat_id)
        return mid

    async def send_admin(self, text: str) -> Optional[str]:
        """Operational message to the owner's private chat (falls back to the channel)."""
        return await self.send_text(text, disable_notification=True, chat_id=self.admin_chat_id or self.channel_id)

    async def test_connection(self) -> Tuple[bool, str]:
        if not self.enabled or self.bot is None:
            return False, "Telegram not configured"
        try:
            me = await self.bot.get_me()
            self.bot_username = me.username
            if not self.channel_id:
                await self.discover_destinations()
            dest = f"channel {self.channel_id}" if self.channel_id else "no channel yet (add the bot as channel admin)"
            return True, f"Connected as @{me.username} — {dest}"
        except Exception as exc:
            return False, f"{type(exc).__name__}: {exc}"

    async def close(self) -> None:
        if self.bot is not None:
            try:
                await self.bot.shutdown()
            except Exception:  # pragma: no cover
                pass

    def stats(self) -> dict:
        return {"enabled": self.enabled, "ready": self.ready, "bot": self.bot_username, "channel_id": self.channel_id,
                "admin_chat_id": self.admin_chat_id, "sent": self.sent, "failed": self.failed,
                "last_error": self.last_error, "hint": self.discovery_hint}
