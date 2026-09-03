"""
Streamlit dashboard for the Crypto Signal Bot.

Reads directly from the PostgreSQL database (same DATABASE_URL as the backend)
and – when reachable – from the backend API for live bot status.

    streamlit run dashboard.py --server.port 8501 --server.address 0.0.0.0
"""
from __future__ import annotations

import math
import os
from datetime import datetime, timedelta

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import requests
import streamlit as st
from sqlalchemy import create_engine, text

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://crypto_user:crypto_password_123@localhost:5432/crypto_signals")
API_URL = os.getenv("API_URL", "http://localhost:8000").rstrip("/")
REFRESH_SECONDS = int(os.getenv("DASHBOARD_REFRESH_SECONDS", "60"))

st.set_page_config(page_title="Crypto Signal Dashboard", page_icon="📊", layout="wide")

st.markdown(
    """
    <style>
    div[data-testid="stMetric"] {background: #11161f; border: 1px solid #222b3a; border-radius: 10px; padding: 12px 16px;}
    div[data-testid="stMetricLabel"] {color: #9aa4b2;}
    .badge {display:inline-block;padding:2px 10px;border-radius:12px;font-size:12px;font-weight:600;}
    .badge-ok {background:#1b4332;color:#95d5b2;} .badge-warn {background:#5c3d00;color:#ffd166;} .badge-bad {background:#5a1a1a;color:#ffadad;}
    </style>
    """,
    unsafe_allow_html=True,
)


# ---------------------------------------------------------------------------
# Data access
# ---------------------------------------------------------------------------
@st.cache_resource
def get_engine():
    return create_engine(DATABASE_URL, pool_pre_ping=True, pool_size=3, max_overflow=2)


@st.cache_data(ttl=REFRESH_SECONDS)
def load_signals(limit: int = 2000) -> pd.DataFrame:
    with get_engine().connect() as conn:
        df = pd.read_sql(text("SELECT * FROM signals ORDER BY timestamp DESC LIMIT :limit"), conn, params={"limit": limit})
    for col in ("timestamp", "closed_at", "candle_time", "tp1_hit_at", "tp2_hit_at", "tp3_hit_at"):
        if col in df.columns:
            df[col] = pd.to_datetime(df[col])
    return df


@st.cache_data(ttl=REFRESH_SECONDS)
def load_performance():
    with get_engine().connect() as conn:
        df = pd.read_sql(text("SELECT * FROM performance ORDER BY id LIMIT 1"), conn)
    return df.iloc[0].to_dict() if not df.empty else None


@st.cache_data(ttl=REFRESH_SECONDS)
def load_bot_status():
    try:
        with get_engine().connect() as conn:
            df = pd.read_sql(text("SELECT * FROM bot_status WHERE id = 1"), conn)
        return df.iloc[0].to_dict() if not df.empty else None
    except Exception:
        return None


@st.cache_data(ttl=REFRESH_SECONDS)
def load_events(signal_id: int) -> pd.DataFrame:
    with get_engine().connect() as conn:
        return pd.read_sql(text("SELECT event_type, price, message, created_at FROM signal_events WHERE signal_id = :sid ORDER BY created_at"),
                           conn, params={"sid": int(signal_id)})


@st.cache_data(ttl=30)
def api_get(path: str):
    try:
        r = requests.get(f"{API_URL}{path}", timeout=4)
        if r.ok:
            return r.json()
    except Exception:
        return None
    return None


def fmt_price(p) -> str:
    if p is None or (isinstance(p, float) and math.isnan(p)):
        return "-"
    p = float(p)
    d = 2 if p >= 1000 else 3 if p >= 100 else 4 if p >= 1 else 5 if p >= 0.01 else 6
    return f"{p:,.{d}f}"


def fmt_pct(v, signed=True) -> str:
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return "-"
    return f"{float(v):+.2f}%" if signed else f"{float(v):.2f}%"


def badge(text_: str, kind: str) -> str:
    return f'<span class="badge badge-{kind}">{text_}</span>'


def compute_stats(df: pd.DataFrame) -> dict:
    """Same formulas as backend/performance_tracker.py, for filtered views."""
    closed = df[df["status"].isin(["TP_HIT", "SL_HIT", "EXPIRED"])]
    pnl = closed["profit_loss_pct"].fillna(0.0)
    wins = closed[closed["outcome"] == "WIN"]
    losses = closed[closed["outcome"] == "LOSS"]
    decisive = len(wins) + len(losses)
    win_rate = len(wins) / decisive * 100 if decisive else 0.0
    gross_profit = pnl[pnl > 0].sum()
    gross_loss = abs(pnl[pnl < 0].sum())
    pf = gross_profit / gross_loss if gross_loss > 0 else (float("inf") if gross_profit > 0 else 0.0)
    avg_win = wins["profit_loss_pct"].mean() if len(wins) else 0.0
    avg_loss = abs(losses["profit_loss_pct"].mean()) if len(losses) else 0.0
    expectancy = (win_rate / 100) * avg_win - (1 - win_rate / 100) * avg_loss if decisive else 0.0
    return {
        "total": len(df), "active": int((df["status"] == "ACTIVE").sum()), "closed": len(closed),
        "wins": len(wins), "losses": len(losses), "win_rate": win_rate, "pf": pf, "expectancy": expectancy,
        "total_pnl": pnl.sum(), "avg_win": avg_win, "avg_loss": avg_loss,
    }


# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------
st.sidebar.title("📊 Crypto Signal Bot")
st.sidebar.caption(f"Auto refresh every {REFRESH_SECONDS}s · data cached")
if st.sidebar.button("🔄 Refresh now", use_container_width=True):
    st.cache_data.clear()
    st.rerun()

try:
    signals = load_signals()
    db_ok = True
except Exception as exc:
    db_ok = False
    signals = pd.DataFrame()
    st.error(f"Database connection failed: {exc}")
    st.stop()

symbols_all = sorted(signals["symbol"].unique().tolist()) if not signals.empty else []
sel_symbols = st.sidebar.multiselect("Symbols", symbols_all, default=symbols_all)
period = st.sidebar.selectbox("Period", ["All time", "Last 24h", "Last 7 days", "Last 30 days", "Last 90 days"], index=0)
sel_source = st.sidebar.multiselect("Source", sorted(signals["source"].dropna().unique().tolist()) if not signals.empty else [],
                                    default=[s for s in (signals["source"].dropna().unique().tolist() if not signals.empty else []) if s != "backtest"] or None)

filtered = signals.copy()
if not filtered.empty:
    if sel_symbols:
        filtered = filtered[filtered["symbol"].isin(sel_symbols)]
    if sel_source:
        filtered = filtered[filtered["source"].isin(sel_source)]
    days = {"Last 24h": 1, "Last 7 days": 7, "Last 30 days": 30, "Last 90 days": 90}.get(period)
    if days:
        filtered = filtered[filtered["timestamp"] >= datetime.utcnow() - timedelta(days=days)]

# ---------------------------------------------------------------------------
# Header + bot status
# ---------------------------------------------------------------------------
st.title("📊 Crypto Trading Signal Dashboard")

status = load_bot_status()
api_status = api_get("/api/status")
cfg = api_get("/api/config")
now = datetime.utcnow()
with st.container():
    c1, c2, c3, c4 = st.columns([2, 2, 2, 3])
    if status and status.get("last_heartbeat") is not None:
        hb = pd.to_datetime(status["last_heartbeat"])
        age = (now - hb.to_pydatetime()).total_seconds()
        if age < 120:
            c1.markdown(f"**Bot:** {badge('ONLINE', 'ok')} &nbsp; heartbeat {int(age)}s ago", unsafe_allow_html=True)
        elif age < 900:
            c1.markdown(f"**Bot:** {badge('STALE', 'warn')} &nbsp; heartbeat {int(age // 60)} min ago", unsafe_allow_html=True)
        else:
            c1.markdown(f"**Bot:** {badge('OFFLINE', 'bad')} &nbsp; last seen {hb:%Y-%m-%d %H:%M} UTC", unsafe_allow_html=True)
        lc = status.get("last_cycle_finished")
        nc = status.get("next_cycle_at")
        c2.markdown(f"**Last scan:** {pd.to_datetime(lc):%H:%M:%S} UTC" if lc is not None and not pd.isna(lc) else "**Last scan:** –")
        c3.markdown(f"**Next scan:** {pd.to_datetime(nc):%H:%M:%S} UTC" if nc is not None and not pd.isna(nc) else "**Next scan:** –")
        src = status.get("data_source") or "-"
        ws = "WS ✅" if status.get("websocket_connected") else "REST"
        mode = ""
        if cfg:
            mode = " · TESTNET" if cfg.get("binance_testnet") and src == "binance" else (" · LIVE" if src == "binance" else "")
        c4.markdown(f"**Data:** {src}{mode} · {ws} · cycles {status.get('cycles_completed', 0)} · v{status.get('version', '-')}")
        if status.get("last_error"):
            st.warning(f"Last error ({pd.to_datetime(status.get('last_error_at')):%H:%M} UTC): {status['last_error']}")
    else:
        c1.markdown(f"**Bot:** {badge('NO HEARTBEAT', 'bad')}", unsafe_allow_html=True)
        c2.caption("Start the backend (`python main.py`) – it writes a heartbeat to the bot_status table.")

# ---------------------------------------------------------------------------
# KPI metrics
# ---------------------------------------------------------------------------
perf = load_performance()
stats = compute_stats(filtered) if not filtered.empty else None
use_filtered = stats is not None and (period != "All time" or (sel_symbols and len(sel_symbols) != len(symbols_all)) or (sel_source and len(sel_source) != len(signals["source"].dropna().unique())))

st.subheader("Performance" + (" (filtered)" if use_filtered else " (all time)"))
if use_filtered:
    m = {
        "total": stats["total"], "active": stats["active"], "win_rate": stats["win_rate"], "pf": stats["pf"],
        "exp": stats["expectancy"], "pnl": stats["total_pnl"], "wins": stats["wins"], "losses": stats["losses"],
    }
elif perf is not None:
    m = {
        "total": int(perf.get("total_signals") or 0), "active": int(perf.get("active_signals") or 0),
        "win_rate": float(perf.get("win_rate") or 0), "pf": float(perf.get("profit_factor") or 0),
        "exp": float(perf.get("expectancy") or 0), "pnl": float(perf.get("total_pnl_pct") or 0),
        "wins": int(perf.get("total_wins") or 0), "losses": int(perf.get("total_losses") or 0),
    }
else:
    m = None

if m:
    k1, k2, k3, k4, k5, k6 = st.columns(6)
    k1.metric("Total Signals", f"{m['total']:,}")
    k2.metric("Active Signals", m["active"])
    k3.metric("Win Rate", f"{m['win_rate']:.1f}%", f"{m['wins']}W / {m['losses']}L", delta_color="off")
    pf_txt = "∞" if m["pf"] is None or m["pf"] >= 999 or math.isinf(m["pf"]) else f"{m['pf']:.2f}"
    k4.metric("Profit Factor", pf_txt)
    k5.metric("Expectancy", f"{m['exp']:+.2f}% / trade")
    k6.metric("Total PnL", f"{m['pnl']:+.2f}%")
    if perf is not None and not use_filtered:
        extra1, extra2, extra3, extra4, extra5, extra6 = st.columns(6)
        extra1.metric("Avg Win", f"{float(perf.get('avg_win_pct') or 0):+.2f}%")
        extra2.metric("Avg Loss", f"-{float(perf.get('avg_loss_pct') or 0):.2f}%")
        extra3.metric("Max Drawdown", f"{float(perf.get('max_drawdown_pct') or 0):.2f}%")
        extra4.metric("TP1 / TP2 / TP3 hit", f"{float(perf.get('tp1_hit_rate') or 0):.0f}% / {float(perf.get('tp2_hit_rate') or 0):.0f}% / {float(perf.get('tp3_hit_rate') or 0):.0f}%")
        streak = int(perf.get("current_streak") or 0)
        extra5.metric("Streak", f"{abs(streak)} {'wins' if streak > 0 else 'losses' if streak < 0 else ''}".strip())
        extra6.metric("Avg Duration", f"{float(perf.get('avg_duration_minutes') or 0) / 60:.1f} h")
        if perf.get("last_updated") is not None:
            st.caption(f"Statistics updated {pd.to_datetime(perf['last_updated']):%Y-%m-%d %H:%M:%S} UTC · "
                       "PnL is unleveraged % of entry price, scale-out in thirds at TP1/TP2/TP3.")
else:
    st.info("No signals yet – statistics will appear after the first screening cycles.")

# ---------------------------------------------------------------------------
# Tabs
# ---------------------------------------------------------------------------
tab_active, tab_history, tab_charts, tab_market, tab_detail = st.tabs(
    ["🔴 Active Signals", "📜 Signal History", "📈 Charts", "🧭 Market", "🔍 Signal Detail"])

with tab_active:
    active = filtered[filtered["status"] == "ACTIVE"].sort_values("timestamp", ascending=False) if not filtered.empty else pd.DataFrame()
    live = api_get("/api/signals/active")
    live_prices = {i["id"]: i for i in (live or {}).get("items", [])}
    if active.empty:
        st.info("No active signals")
    else:
        rows = []
        for _, s in active.iterrows():
            lp = live_prices.get(int(s["id"]), {})
            rows.append({
                "ID": int(s["id"]), "Symbol": s["symbol"], "Side": s["side"],
                "Entry": fmt_price(s["entry_price"]), "Stop": fmt_price(s.get("current_sl") or s["sl_price"]),
                "TP1": fmt_price(s["tp1_price"]), "TP2": fmt_price(s["tp2_price"]), "TP3": fmt_price(s["tp3_price"]),
                "TPs hit": int(s.get("tp_hits") or 0),
                "Last": fmt_price(lp.get("last_price")) if lp.get("last_price") else "-",
                "Unrealised": fmt_pct(lp.get("unrealised_pct")) if lp.get("unrealised_pct") is not None else "-",
                "MFE": fmt_pct(s.get("max_favorable_pct")), "MAE": fmt_pct(s.get("max_adverse_pct")),
                "Conviction": f"{float(s.get('conviction_score') or 0):.0f}%",
                "Opened (UTC)": s["timestamp"].strftime("%Y-%m-%d %H:%M"),
                "Age": f"{int((now - s['timestamp'].to_pydatetime()).total_seconds() // 3600)}h",
            })
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

with tab_history:
    hist = filtered.sort_values("timestamp", ascending=False) if not filtered.empty else pd.DataFrame()
    status_filter = st.multiselect("Status", ["ACTIVE", "TP_HIT", "SL_HIT", "EXPIRED"], default=["TP_HIT", "SL_HIT", "EXPIRED", "ACTIVE"])
    if not hist.empty:
        hist = hist[hist["status"].isin(status_filter)]
    if hist.empty:
        st.info("No signals for the selected filters")
    else:
        show = pd.DataFrame({
            "ID": hist["id"].astype(int), "Time (UTC)": hist["timestamp"].dt.strftime("%Y-%m-%d %H:%M"),
            "Symbol": hist["symbol"], "Side": hist["side"], "Entry": hist["entry_price"].map(fmt_price),
            "SL": hist["sl_price"].map(fmt_price), "TP1": hist["tp1_price"].map(fmt_price), "TP3": hist["tp3_price"].map(fmt_price),
            "Status": hist["status"], "Outcome": hist["outcome"].fillna("-"), "TPs": hist["tp_hits"].fillna(0).astype(int),
            "PnL %": hist["profit_loss_pct"].map(lambda v: fmt_pct(v) if pd.notna(v) else "-"),
            "R": hist["profit_loss_r"].map(lambda v: f"{v:+.2f}" if pd.notna(v) else "-"),
            "Conv.": hist["conviction_score"].map(lambda v: f"{v:.0f}%" if pd.notna(v) else "-"),
            "Setup": hist["conditions"].fillna("").str.replace(",", ", "),
            "Closed (UTC)": hist["closed_at"].dt.strftime("%Y-%m-%d %H:%M").fillna("-"),
        })
        st.dataframe(show, use_container_width=True, hide_index=True, height=520)
        st.download_button("⬇️ Download CSV", hist.to_csv(index=False).encode(), "signals.csv", "text/csv")

with tab_charts:
    closed = filtered[filtered["status"].isin(["TP_HIT", "SL_HIT", "EXPIRED"])].copy() if not filtered.empty else pd.DataFrame()
    if closed.empty:
        st.info("Charts appear once signals have closed.")
    else:
        closed = closed.sort_values("closed_at")
        closed["cumulative_pnl"] = closed["profit_loss_pct"].fillna(0).cumsum()
        left, right = st.columns([3, 2])
        with left:
            fig = go.Figure()
            fig.add_trace(go.Scatter(x=closed["closed_at"], y=closed["cumulative_pnl"], mode="lines+markers",
                                     name="Cumulative PnL %", line=dict(color="#4cc9f0", width=2), fill="tozeroy",
                                     fillcolor="rgba(76,201,240,0.12)"))
            fig.update_layout(title="Cumulative PnL (%)", height=360, margin=dict(l=10, r=10, t=40, b=10),
                              template="plotly_dark", xaxis_title=None, yaxis_title="%")
            st.plotly_chart(fig, use_container_width=True)
        with right:
            by_sym = closed.groupby("symbol").agg(pnl=("profit_loss_pct", "sum"), n=("id", "count"),
                                                  wins=("outcome", lambda s: (s == "WIN").sum())).reset_index()
            by_sym["win_rate"] = by_sym["wins"] / by_sym["n"] * 100
            fig2 = px.bar(by_sym, x="symbol", y="pnl", color="pnl", color_continuous_scale=["#e63946", "#adb5bd", "#2dc653"],
                          title="PnL by symbol (%)", text=by_sym["n"].map(lambda n: f"{n} trades"))
            fig2.update_layout(height=360, margin=dict(l=10, r=10, t=40, b=10), template="plotly_dark", coloraxis_showscale=False)
            st.plotly_chart(fig2, use_container_width=True)
        c1, c2, c3 = st.columns(3)
        with c1:
            fig3 = px.histogram(closed, x="profit_loss_pct", nbins=30, title="PnL distribution (%)", color_discrete_sequence=["#4cc9f0"])
            fig3.update_layout(height=300, margin=dict(l=10, r=10, t=40, b=10), template="plotly_dark")
            st.plotly_chart(fig3, use_container_width=True)
        with c2:
            oc = closed["outcome"].fillna("BREAKEVEN").value_counts().reset_index()
            oc.columns = ["outcome", "count"]
            fig4 = px.pie(oc, names="outcome", values="count", title="Outcomes", hole=0.5,
                          color="outcome", color_discrete_map={"WIN": "#2dc653", "LOSS": "#e63946", "BREAKEVEN": "#adb5bd"})
            fig4.update_layout(height=300, margin=dict(l=10, r=10, t=40, b=10), template="plotly_dark")
            st.plotly_chart(fig4, use_container_width=True)
        with c3:
            closed["conv_bucket"] = pd.cut(closed["conviction_score"].fillna(0), bins=[-1, 49, 64, 79, 101],
                                           labels=["<50", "50-64", "65-79", "80+"])
            cb = closed.groupby("conv_bucket", observed=True).agg(n=("id", "count"), wins=("outcome", lambda s: (s == "WIN").sum()),
                                                                  pnl=("profit_loss_pct", "mean")).reset_index()
            cb["win_rate"] = cb["wins"] / cb["n"] * 100
            fig5 = px.bar(cb, x="conv_bucket", y="win_rate", title="Win rate by conviction", text=cb["n"].map(lambda n: f"n={n}"),
                          color_discrete_sequence=["#f4a261"])
            fig5.update_layout(height=300, margin=dict(l=10, r=10, t=40, b=10), template="plotly_dark", yaxis_title="%", xaxis_title=None)
            st.plotly_chart(fig5, use_container_width=True)
        daily = closed.set_index("closed_at")["profit_loss_pct"].resample("D").sum().reset_index()
        daily.columns = ["day", "pnl"]
        fig6 = px.bar(daily, x="day", y="pnl", title="Daily PnL (%)", color=daily["pnl"] > 0,
                      color_discrete_map={True: "#2dc653", False: "#e63946"})
        fig6.update_layout(height=280, margin=dict(l=10, r=10, t=40, b=10), template="plotly_dark", showlegend=False)
        st.plotly_chart(fig6, use_container_width=True)

with tab_market:
    market = api_get("/api/market")
    if not market or not market.get("items"):
        st.info("Live market snapshot needs the backend API (API_URL). Showing nothing until the bot has run a cycle.")
    else:
        rows = []
        for sym, snap in market["items"].items():
            ev = (market.get("evaluations") or {}).get(sym, {})
            rows.append({
                "Symbol": sym, "Close": fmt_price(snap.get("close")), "RSI": f"{snap.get('rsi', 0):.1f}",
                "MACD": f"{snap.get('macd', 0):.4g}", "Signal": f"{snap.get('macd_signal', 0):.4g}",
                "BB lower": fmt_price(snap.get("bb_lower")), "BB upper": fmt_price(snap.get("bb_upper")),
                "ATR": fmt_price(snap.get("atr")), "ATR %": f"{snap.get('atr_pct', 0):.2f}%",
                "Vol ratio": f"{(snap.get('volume_ratio') or 0):.2f}x", "Trend": snap.get("trend"),
                "Long score": ev.get("long_score", "-"), "Short score": ev.get("short_score", "-"),
                "Note": ev.get("rejected_reason") or ("CANDIDATE" if ev.get("candidate") else ""),
                "Candle": (snap.get("timestamp") or "")[:16].replace("T", " "),
            })
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
        if cfg:
            s = cfg.get("strategy", {})
            st.caption(f"Strategy: RSI {s.get('rsi', {}).get('period')} (<{s.get('rsi', {}).get('oversold')} / >{s.get('rsi', {}).get('overbought')}), "
                       f"MACD {s.get('macd', {}).get('fast')}/{s.get('macd', {}).get('slow')}/{s.get('macd', {}).get('signal')}, "
                       f"BB {s.get('bollinger', {}).get('period')}/{s.get('bollinger', {}).get('std')}σ · min {s.get('min_conditions')}/3 conditions · "
                       f"SL {cfg.get('risk', {}).get('sl_atr_mult')} ATR · TP {'/'.join(str(x) for x in cfg.get('risk', {}).get('tp_atr_mults', []))} ATR")

with tab_detail:
    if signals.empty:
        st.info("No signals yet")
    else:
        ids = signals["id"].astype(int).tolist()
        sid = st.selectbox("Signal", ids, format_func=lambda i: f"#{i} · {signals.loc[signals['id'] == i, 'symbol'].iloc[0]} "
                                                                  f"{signals.loc[signals['id'] == i, 'side'].iloc[0]} · "
                                                                  f"{signals.loc[signals['id'] == i, 'status'].iloc[0]}")
        s = signals[signals["id"] == sid].iloc[0]
        a, b, c = st.columns(3)
        a.markdown(f"**{s['symbol']} {s['side']}** · {s['timeframe']}  \nOpened {s['timestamp']:%Y-%m-%d %H:%M} UTC  \n"
                   f"Status **{s['status']}** {('· ' + str(s['outcome'])) if pd.notna(s['outcome']) else ''}")
        b.markdown(f"Entry **{fmt_price(s['entry_price'])}** (zone {fmt_price(s['entry_low'])} – {fmt_price(s['entry_high'])})  \n"
                   f"SL {fmt_price(s['sl_price'])} → current {fmt_price(s['current_sl'])}  \n"
                   f"TP1 {fmt_price(s['tp1_price'])} · TP2 {fmt_price(s['tp2_price'])} · TP3 {fmt_price(s['tp3_price'])}")
        c.markdown(f"Conviction **{float(s['conviction_score'] or 0):.0f}%** · R:R 1:{float(s['risk_reward'] or 0):.1f}  \n"
                   f"PnL **{fmt_pct(s['profit_loss_pct'])}** ({(f'{s.profit_loss_r:+.2f}R') if pd.notna(s['profit_loss_r']) else '-'}) · TPs hit {int(s['tp_hits'] or 0)}  \n"
                   f"MFE {fmt_pct(s['max_favorable_pct'])} · MAE {fmt_pct(s['max_adverse_pct'])}")
        st.markdown(f"**Why:** {s['reasons'] or '-'}")
        st.markdown(f"RSI {float(s['rsi'] or 0):.1f} · MACD {float(s['macd'] or 0):.4g} / {float(s['macd_signal'] or 0):.4g} · "
                    f"BB [{fmt_price(s['bb_lower'])}, {fmt_price(s['bb_upper'])}] · ATR {fmt_price(s['atr'])} · "
                    f"Volume {float(s['volume_ratio'] or 0):.2f}x · 1h {s['htf_trend_1h']} · 4h {s['htf_trend_4h']}")
        # levels chart
        lv = go.Figure()
        levels = [("SL", s["sl_price"], "#e63946"), ("Entry", s["entry_price"], "#f1faee"), ("TP1", s["tp1_price"], "#80ed99"),
                  ("TP2", s["tp2_price"], "#57cc99"), ("TP3", s["tp3_price"], "#38a3a5")]
        for name, price, color in levels:
            lv.add_trace(go.Bar(x=[name], y=[price], marker_color=color, text=fmt_price(price), textposition="outside", name=name))
        ymin = min(p for _, p, _ in levels) * 0.995
        ymax = max(p for _, p, _ in levels) * 1.005
        lv.update_layout(title="Price levels", height=300, template="plotly_dark", showlegend=False,
                         yaxis=dict(range=[ymin, ymax]), margin=dict(l=10, r=10, t=40, b=10))
        st.plotly_chart(lv, use_container_width=True)
        try:
            ev = load_events(int(sid))
            if not ev.empty:
                ev["created_at"] = pd.to_datetime(ev["created_at"]).dt.strftime("%Y-%m-%d %H:%M:%S")
                ev["price"] = ev["price"].map(fmt_price)
                st.dataframe(ev.rename(columns={"event_type": "Event", "price": "Price", "message": "Note", "created_at": "Time (UTC)"}),
                             use_container_width=True, hide_index=True)
        except Exception:
            pass

st.caption(f"Crypto Signal Bot · {now:%Y-%m-%d %H:%M:%S} UTC · Signals are informational only – not financial advice.")
