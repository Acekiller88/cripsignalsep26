#!/usr/bin/env python3
"""
Formatting helpers for the operator scripts (works on Python 3.8+).

    python3 scripts/report_lib.py status      < /api/status JSON
    python3 scripts/report_lib.py market      < /api/market JSON
    python3 scripts/report_lib.py performance < /api/performance JSON
    python3 scripts/report_lib.py breakdown   < /api/performance/breakdown JSON
    python3 scripts/report_lib.py signals     < /api/signals JSON
    python3 scripts/report_lib.py get <key.path>   (e.g. live.cycles_completed)
"""
import json
import sys


def _load():
    raw = sys.stdin.read().strip()
    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None


def _fmt(v, spec):
    try:
        return format(v, spec)
    except (TypeError, ValueError):
        return str(v)


def status(d):
    live = d.get("live") or {}
    ds = live.get("data_source") or {}
    tg = live.get("telegram") or {}
    print("  uptime_h=%s cycles=%s signals_generated=%s" % (
        _fmt((live.get("uptime_seconds") or 0) / 3600, ".1f"), live.get("cycles_completed"), live.get("signals_generated")))
    print("  last_cycle=%s next_cycle=%s last_monitor=%s" % (
        live.get("last_cycle_finished"), live.get("next_cycle_at"), live.get("last_monitor_at")))
    print("  source=%s endpoint=%s ws=%s rest_calls=%s rest_failures=%s last_rest_error=%s" % (
        ds.get("source"), ds.get("endpoint"), ds.get("websocket_connected"), ds.get("rest_calls"),
        ds.get("rest_failures"), ds.get("last_rest_error")))
    if ds.get("unsupported_symbols"):
        print("  unsupported_symbols=%s" % ",".join(ds["unsupported_symbols"]))
    print("  telegram enabled=%s ready=%s bot=%s channel=%s admin_chat=%s sent=%s failed=%s last_error=%s" % (
        tg.get("enabled"), tg.get("ready"), tg.get("bot"), tg.get("channel_id"), tg.get("admin_chat_id"),
        tg.get("sent"), tg.get("failed"), tg.get("last_error")))
    if tg.get("hint"):
        print("  telegram hint: %s" % tg["hint"])
    print("  last_error=%s at %s" % (live.get("last_error"), live.get("last_error_at")))
    print("  signals total=%s active=%s" % (d.get("total_signals"), d.get("active_signals")))


def market(d):
    items = d.get("items") or {}
    evs = d.get("evaluations") or {}
    if not items:
        print("  (no market snapshot yet – bot has not completed a cycle)")
        return
    for sym, v in items.items():
        ev = evs.get(sym) or {}
        note = ev.get("rejected_reason") or ("CANDIDATE" if ev.get("candidate") else "")
        print("  %-9s close=%-12s rsi=%-5s atr%%=%-5s vol=%-5sx trend=%-8s L%s S%s %s candle=%s" % (
            sym, _fmt(v.get("close"), ".6g"), _fmt(v.get("rsi"), ".1f"), _fmt(v.get("atr_pct"), ".2f"),
            _fmt(v.get("volume_ratio"), ".2f"), v.get("trend"), ev.get("long_score", "-"), ev.get("short_score", "-"),
            note, str(v.get("timestamp"))[:16]))


def performance(d):
    pf = d.get("profit_factor")
    pf_txt = "inf" if pf is None or pf >= 999 else _fmt(pf, ".2f")
    print("  total=%s active=%s closed=%s W/L/BE=%s/%s/%s win_rate=%s%%" % (
        d.get("total_signals"), d.get("active_signals"), d.get("closed_signals"), d.get("total_wins"),
        d.get("total_losses"), d.get("total_breakeven"), _fmt(d.get("win_rate") or 0, ".1f")))
    print("  total_pnl=%s%% profit_factor=%s expectancy=%s%%/trade avg_r=%s" % (
        _fmt(d.get("total_pnl_pct") or 0, "+.2f"), pf_txt, _fmt(d.get("expectancy") or 0, "+.3f"),
        _fmt(d.get("avg_r") or 0, "+.2f")))
    print("  max_dd=%s%% tp_hit=%s/%s/%s%% avg_duration_h=%s streak=%s last_updated=%s" % (
        _fmt(d.get("max_drawdown_pct") or 0, ".2f"), _fmt(d.get("tp1_hit_rate") or 0, ".0f"),
        _fmt(d.get("tp2_hit_rate") or 0, ".0f"), _fmt(d.get("tp3_hit_rate") or 0, ".0f"),
        _fmt((d.get("avg_duration_minutes") or 0) / 60, ".1f"), d.get("current_streak"), d.get("last_updated")))


def _row(label, v):
    pf = v.get("profit_factor")
    pf_txt = "inf" if pf is None else _fmt(pf, ".2f")
    return "  %-11s closed=%-4s active=%-3s win=%5s%% pnl=%7s%% pf=%-5s exp=%s" % (
        label, v.get("closed_signals"), v.get("active_signals"), _fmt(v.get("win_rate") or 0, ".1f"),
        _fmt(v.get("total_pnl_pct") or 0, "+.2f"), pf_txt, _fmt(v.get("expectancy") or 0, "+.3f"))


def breakdown(d):
    print(_row("OVERALL", d.get("overall") or {}))
    for k, v in (d.get("by_symbol") or {}).items():
        print(_row(k, v))
    for k, v in (d.get("by_side") or {}).items():
        print(_row(k, v))
    for k, v in (d.get("by_conviction") or {}).items():
        print(_row("conv " + k, v))
    if d.get("by_status"):
        print("  by_status=%s" % json.dumps(d["by_status"]))


def signals(d):
    items = d.get("items") or []
    if not items:
        print("  (no signals)")
    for s in items:
        pnl = "" if s.get("profit_loss_pct") is None else _fmt(s["profit_loss_pct"], "+.2f") + "%"
        if s.get("unrealised_pct") is not None and s.get("status") == "ACTIVE":
            pnl = "unreal " + _fmt(s["unrealised_pct"], "+.2f") + "%"
        print("  #%-5s %s %-9s%-6s entry=%-12s %-8s%-9s%-8s tp%s conv=%s %s" % (
            s.get("id"), str(s.get("timestamp"))[:16], s.get("symbol"), s.get("side"), _fmt(s.get("entry_price"), ".6g"),
            s.get("status"), s.get("outcome") or "-", pnl, s.get("tp_hits"), _fmt(s.get("conviction_score") or 0, ".0f"),
            ",".join(s.get("conditions") or [])))


def tg_discover(d):
    """Print the chats seen in a getUpdates payload, channels first (mirrors TelegramNotifier)."""
    seen = []
    for u in d.get("result") or []:
        m = u.get("channel_post") or u.get("message") or u.get("my_chat_member")
        c = m.get("chat") if isinstance(m, dict) else None
        if c and c.get("id") not in [x[1] for x in seen]:
            seen.append((c.get("type"), c.get("id"), c.get("title") or c.get("username") or c.get("first_name")))
    for t, i, name in sorted(seen, key=lambda x: 0 if x[0] in ("channel", "group", "supergroup") else 1):
        kind = "channel" if t in ("channel", "group", "supergroup") else "private"
        print("%s %s %s" % (kind, i, name))


def get(d, path):
    cur = d
    for part in path.split("."):
        if isinstance(cur, dict):
            cur = cur.get(part)
        else:
            cur = None
        if cur is None:
            break
    print("" if cur is None else cur)


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 1
    cmd = sys.argv[1]
    d = _load()
    if d is None:
        print("  (no data – API not reachable?)")
        return 1
    if cmd == "status":
        status(d)
    elif cmd == "market":
        market(d)
    elif cmd == "performance":
        performance(d)
    elif cmd == "breakdown":
        breakdown(d)
    elif cmd == "signals":
        signals(d)
    elif cmd == "tg_discover":
        tg_discover(d)
    elif cmd == "get" and len(sys.argv) > 2:
        get(d, sys.argv[2])
    else:
        print(__doc__)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
