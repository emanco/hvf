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
    "NIGHT_TIDE":             ("2.39", "active"),
    "BTC_DONCHIAN":           ("~5.0", "active"),
    "LONDON_BO":              ("1.37", "active"),
    "ASIAN_SESSION_BREAKOUT": ("1.20", "active"),
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

    def live_pf(d):
        if d["n"] == 0:
            return "—"
        if d["gl"] == 0:
            return "∞"
        return f"{d['gw'] / d['gl']:.2f}"

    # order: active first (by reference order), then others present
    order = [k for k in _REFERENCE if k in agg or _REFERENCE[k][1] == "active"]
    for k in agg:
        if k not in order:
            order.append(k)

    lines = [
        "<b>📋 Strategy Scorecard</b>",
        f"<i>live (since {go_live}) vs honest backtest</i>",
        "<pre>",
        f"{'strat':<10}{'livePF':>7}{'bktPF':>7}{'N':>4}{'WR':>5}{'open':>5}",
        "-" * 38,
    ]
    for pt in order:
        d = agg.get(pt)
        if not d:
            continue
        bkt, status = _REFERENCE.get(pt, ("?", "other"))
        name = _SHORT.get(pt, pt[:9])
        wr = f"{100 * d['w'] / d['n']:.0f}%" if d["n"] else "—"
        tag = f" ({status})" if status and status != "active" else ""
        lines.append(
            f"{name:<10}{live_pf(d):>7}{bkt:>7}{d['n']:>4}{wr:>5}{d['open']:>5}{tag}"
        )
    lines.append("</pre>")

    total_est = sum(d["est"] for d in agg.values())
    lines.append(
        "livePF excludes estimated-PnL trades"
        + (f" ({total_est} excluded)" if total_est else "")
        + ". — = no clean closed trades yet."
    )
    lines.append(
        "<i>Samples are tiny — read as a watch, not a verdict.</i>"
    )
    return "\n".join(lines)
