"""Lightweight strategy scorecard — live performance vs honest backtest.

Side-by-side view so a strategy quietly degrading from its (honest) backtest
is VISIBLE instead of discovered months later (the QL/KZ failure mode). This
is the lightweight precursor to statistical alarms — no CI math yet, just the
numbers next to each other. Live PF excludes pnl_estimated trades (DB caveat:
those PnLs are unreliable).

Honest backtest PFs are the validated 2026-06-23 figures (see memory
project_backtest_harness_hardened). Update the reference table if a strategy
is re-validated.
"""
from datetime import datetime, timezone

from hvf_trader import config
from hvf_trader.database.models import TradeRecord

# (honest backtest PF as string, status tag). Validated 2026-06-23.
_REFERENCE = {
    "NR7_BREAKOUT":           ("~5.0", "active"),
    "NIGHT_TIDE":             ("2.13", "active"),   # spread-correct (was 2.39)
    "BTC_DONCHIAN":           ("~5.0", "active"),
    "LONDON_BO":              ("1.32", "active"),   # spread-correct (was 1.37)
    "ASIAN_SESSION_BREAKOUT": ("1.79", "active"),   # GBPJPY-only (EURJPY dropped 06-26)
    "QUANTUM_LONDON":         ("0.44", "RETIRED"),
    "KZ_HUNT":                ("0.38", "off"),
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

    # Active strategies only, in reference order — retired/off are dropped.
    lines = [
        "<b>📋 Strategy Scorecard</b>",
        f"<i>live (since {go_live}) vs honest backtest</i>",
        "",
    ]
    total_est = 0
    for pt, (bkt_s, status) in _REFERENCE.items():
        if status != "active":
            continue
        d = agg.get(pt, {"n": 0, "w": 0, "gw": 0.0, "gl": 0.0, "est": 0, "open": 0})
        total_est += d["est"]
        live_str, live_val = live_str_and_val(d)
        try:
            bkt_val = float(bkt_s.replace("~", ""))
        except ValueError:
            bkt_val = None
        name = _SHORT.get(pt, pt)
        if d["n"]:
            detail = f"{d['n']}T · {100 * d['w'] / d['n']:.0f}% WR"
        else:
            detail = "no closed trades"
        if d["open"]:
            detail += f" · {d['open']} open"
        lines.append(f"{status_dot(live_val, bkt_val)} <b>{name}</b>")
        lines.append(f"   live <b>{live_str}</b>  vs  backtest {bkt_s}   ({detail})")

    lines.append("")
    lines.append(
        "<i>livePF excludes estimated-PnL trades"
        + (f" ({total_est} excluded)" if total_est else "")
        + ". Samples are tiny — a watch, not a verdict.</i>"
    )
    return "\n".join(lines)
