"""Lightweight strategy scorecard — live performance vs honest backtest.

Side-by-side view so a strategy quietly degrading from its (honest) backtest
is VISIBLE instead of discovered months later (the QL/KZ failure mode). This
is the lightweight precursor to statistical alarms — no CI math yet, just the
numbers next to each other. Live PF excludes pnl_estimated trades (DB caveat:
those PnLs are unreliable).

Which strategies appear is DERIVED from config.active_strategy_map(), not a
hand-maintained status tag — a retirement drops the row automatically. The old
table went stale exactly that way: on 2026-07-28 it still listed NR7 (retired
07-02) and LONDON_BO (retired 07-28) as active. Same fix as alert_startup.

The reference PFs must be the HONEST re-backtests, and each carries its source.
The pre-2026-07 figures were all inflated by the two fill fictions (blind-gap
entry fills, stop-modify-through-market) — see CLAUDE.md "Negative results".
Because the status dot is live/backtest, an inflated denominator makes a
perfectly healthy strategy read red, which is the failure mode that trains you
to ignore the dot.
"""
from datetime import datetime, timezone

from hvf_trader import config
from hvf_trader.database.models import TradeRecord

# pattern_type -> (display string, numeric PF for the ratio, provenance).
# Numeric is separate from display so a range can be shown without the old
# fragile float(s.replace("~", "")) parse silently falling back to "no
# comparison" (which rendered as a green dot).
_REFERENCE = {
    "NIGHT_TIDE": (
        "1.4-1.55", 1.40,
        "IC-native baseline, scripts/nt_ic_feed_diag.py (2026-07-14). NOT the "
        "Dukascopy PF 2-3 — IC's feed yields ~4x fewer signals.",
    ),
    "ASIAN_SESSION_BREAKOUT": (
        "1.28", 1.28,
        "GBPJPY honest 2023+, floored spread, scripts/asb_fill_audit.py row E "
        "(2026-07-28). Was 1.79 — void, inflated by both fill fictions.",
    ),
    "BTC_DONCHIAN": (
        "BTC 2.6 / ETH 4.9 / XAU 2.5 / USTEC 1.6 / JP225 1.5 / US500 1.4", 2.60,
        "Crypto legs: entry-at-close, scripts/btc_donchian_honest_bt.py "
        "(2026-07-02); was ~5.0, never honest. XAUUSD/USTEC/JP225/US500: "
        "real-cost PF 2017+, scripts/donchian_universe_screen.py (2026-07-29). "
        "Per-symbol because the universe extension spans very different edges — "
        "a single number here would flatter the index legs and understate "
        "crypto. Ratio uses the BTC leg, so the dot tracks the incumbents; the "
        "half-stake extension legs are not separable here yet.",
    ),
}

# short labels to keep the table narrow on mobile
_SHORT = {
    "NR7_BREAKOUT": "NR7", "NIGHT_TIDE": "NightTide", "BTC_DONCHIAN": "Donchian",
    "LONDON_BO": "London", "ASIAN_SESSION_BREAKOUT": "ASB",
    "QUANTUM_LONDON": "QL", "KZ_HUNT": "KZ_Hunt",
}


def build_strategy_scorecard(trade_logger) -> str:
    """Telegram-formatted live-vs-backtest scorecard since go-live."""
    session = trade_logger._session
    go_live = config.PERF_GO_LIVE_DATE

    closed = (
        session.query(TradeRecord)
        .filter(TradeRecord.status == "CLOSED")
        .filter(TradeRecord.opened_at >= go_live)
        .all()
    )
    open_rows = (
        session.query(TradeRecord)
        .filter(TradeRecord.status == "OPEN")
        .all()
    )

    agg: dict[str, dict] = {}
    for t in closed:
        pt = t.pattern_type or "UNKNOWN"
        d = agg.setdefault(pt, {"n": 0, "w": 0, "gw": 0.0, "gl": 0.0,
                                "est": 0, "open": 0})
        if t.pnl_estimated:            # unreliable PnL — count but exclude from PF
            d["est"] += 1
            continue
        if t.pnl is None or t.pnl == 0:
            continue
        d["n"] += 1
        if t.pnl > 0:
            d["w"] += 1
            d["gw"] += t.pnl
        else:
            d["gl"] += abs(t.pnl)
    for t in open_rows:
        pt = t.pattern_type or "UNKNOWN"
        agg.setdefault(pt, {"n": 0, "w": 0, "gw": 0.0, "gl": 0.0,
                            "est": 0, "open": 0})["open"] += 1

    def live_str_and_val(d):
        if d["n"] == 0:
            return "—", None
        if d["gl"] == 0:
            return "∞", float("inf")
        v = d["gw"] / d["gl"]
        return f"{v:.2f}", v

    def status_dot(live_val, bkt_val):
        """⚪ no data · 🟢 tracking · 🟡 soft · 🔴 well below backtest."""
        if live_val is None:
            return "⚪"
        if bkt_val is None:
            return "🟢"
        ratio = live_val / bkt_val
        if ratio >= 0.7:
            return "🟢"
        if ratio >= 0.4:
            return "🟡"
        return "🔴"

    # Rows come from the live config, so retiring a strategy removes it here
    # with no edit to this file.
    active = config.active_strategy_map()
    lines = [
        "<b>📋 Strategy Scorecard</b>",
        f"<i>live (since {go_live}) vs honest backtest</i>",
        "",
    ]
    total_est = 0
    for pt, symbols in active.items():
        d = agg.get(pt, {"n": 0, "w": 0, "gw": 0.0, "gl": 0.0, "est": 0, "open": 0})
        total_est += d["est"]
        live_str, live_val = live_str_and_val(d)
        bkt_s, bkt_val, _src = _REFERENCE.get(pt, ("—", None, ""))
        name = _SHORT.get(pt, pt)
        if d["n"]:
            detail = f"{d['n']}T · {100 * d['w'] / d['n']:.0f}% WR"
        else:
            detail = "no closed trades"
        if d["open"]:
            detail += f" · {d['open']} open"
        lines.append(f"{status_dot(live_val, bkt_val)} <b>{name}</b> "
                     f"<i>{', '.join(symbols)}</i>")
        lines.append(f"   live <b>{live_str}</b>  vs  backtest {bkt_s}   ({detail})")

    # Anything with live history since go-live that is no longer enabled. Keeps
    # a retired strategy's PnL from silently vanishing from this view.
    retired = sorted(set(agg) - set(active))
    if retired:
        bits = []
        for pt in retired:
            d = agg[pt]
            if not (d["n"] or d["open"]):
                continue
            bits.append(f"{_SHORT.get(pt, pt)} ({d['n']}T"
                        + (f", {d['open']} open" if d["open"] else "") + ")")
        if bits:
            lines.append("")
            lines.append(f"<i>retired, still in PnL history: {', '.join(bits)}</i>")

    lines.append("")
    lines.append(
        "<i>livePF excludes estimated-PnL trades"
        + (f" ({total_est} excluded)" if total_est else "")
        + ". Samples are tiny — a watch, not a verdict.</i>"
    )
    return "\n".join(lines)
