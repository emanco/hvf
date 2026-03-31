"""
System audit report — runs on VPS, outputs JSON to stdout.
Collects all data needed for the /audit-system skill in one shot.
"""

import json
import os
import sqlite3
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

DB_PATH = r"C:\hvf_trader\hvf_trader.db"
LOG_DIR = r"C:\hvf_trader\logs"
GO_LIVE_DATE = "2026-03-25"


def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def bot_status():
    """Check if bot service is running."""
    try:
        result = subprocess.run(
            [r"C:\nssm\nssm.exe", "status", "HVF_Bot"],
            capture_output=True, text=True, timeout=10,
        )
        status = result.stdout.strip().replace("\x00", "").strip()
        return status
    except Exception as e:
        return f"ERROR: {e}"


def recent_log_errors(lines=100):
    """Get recent errors from error log."""
    errors = []
    error_log = os.path.join(LOG_DIR, "errors.log")
    if not os.path.exists(error_log):
        return errors
    try:
        with open(error_log, "r") as f:
            all_lines = f.readlines()
        for line in all_lines[-lines:]:
            line = line.strip()
            if line and ("ERROR" in line or "CRITICAL" in line):
                errors.append(line)
    except Exception:
        pass
    return errors[-20:]  # Last 20 errors max


def last_scan_time():
    """Get timestamp of most recent scan from main log."""
    main_log = os.path.join(LOG_DIR, "main.log")
    if not os.path.exists(main_log):
        return None
    try:
        with open(main_log, "r") as f:
            all_lines = f.readlines()
        for line in reversed(all_lines):
            if "Scan " in line and "candidates" in line:
                return line[:19]  # timestamp portion
        return None
    except Exception:
        return None


def trade_stats(conn):
    """Get trade statistics since go-live date."""
    cur = conn.cursor()

    # All trades since go-live
    cur.execute(
        "SELECT * FROM trade_records WHERE opened_at >= ? ORDER BY id",
        (GO_LIVE_DATE,),
    )
    trades = [dict(r) for r in cur.fetchall()]

    closed = [t for t in trades if t["status"] == "CLOSED"]
    open_trades = [t for t in trades if t["status"] in ("OPEN", "PARTIAL")]

    total = len(closed)
    wins = [t for t in closed if t["pnl"] and t["pnl"] > 0]
    losses = [t for t in closed if t["pnl"] and t["pnl"] <= 0]
    zero_pnl = [t for t in closed if t["pnl"] is not None and t["pnl"] == 0.0]
    null_pnl = [t for t in closed if t["pnl"] is None]

    total_pnl = sum(t["pnl"] for t in closed if t["pnl"])
    total_pips = sum(t["pnl_pips"] for t in closed if t["pnl_pips"])

    gross_profit = sum(t["pnl"] for t in wins) if wins else 0
    gross_loss = abs(sum(t["pnl"] for t in losses)) if losses else 0.001
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else 0

    win_rate = (len(wins) / total * 100) if total > 0 else 0

    # Slippage stats
    slippage_trades = [t for t in closed if t.get("slippage") is not None]
    avg_slippage = 0
    if slippage_trades:
        avg_slippage = sum(t["slippage"] for t in slippage_trades) / len(slippage_trades)

    # Per close reason
    close_reasons = {}
    for t in closed:
        reason = t.get("close_reason", "UNKNOWN")
        close_reasons[reason] = close_reasons.get(reason, 0) + 1

    # Per pattern type
    by_pattern = {}
    for t in closed:
        pt = t.get("pattern_type") or "LEGACY"
        if pt not in by_pattern:
            by_pattern[pt] = {"count": 0, "wins": 0, "pnl": 0, "pips": 0}
        by_pattern[pt]["count"] += 1
        if t["pnl"] and t["pnl"] > 0:
            by_pattern[pt]["wins"] += 1
        by_pattern[pt]["pnl"] += t["pnl"] or 0
        by_pattern[pt]["pips"] += t["pnl_pips"] or 0

    # Per pair
    by_pair = {}
    for t in closed:
        sym = t["symbol"]
        if sym not in by_pair:
            by_pair[sym] = {"count": 0, "wins": 0, "pnl": 0, "pips": 0}
        by_pair[sym]["count"] += 1
        if t["pnl"] and t["pnl"] > 0:
            by_pair[sym]["wins"] += 1
        by_pair[sym]["pnl"] += t["pnl"] or 0
        by_pair[sym]["pips"] += t["pnl_pips"] or 0

    # Consecutive losses (current streak)
    consecutive_losses = 0
    for t in reversed(closed):
        if t["pnl"] and t["pnl"] <= 0:
            consecutive_losses += 1
        else:
            break

    return {
        "total_closed": total,
        "open_count": len(open_trades),
        "open_trades": [
            {
                "id": t["id"], "symbol": t["symbol"], "direction": t["direction"],
                "pattern_type": t.get("pattern_type"), "opened_at": t["opened_at"],
                "entry_price": t["entry_price"], "stop_loss": t["stop_loss"],
            }
            for t in open_trades
        ],
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": round(win_rate, 1),
        "profit_factor": round(profit_factor, 2),
        "total_pnl": round(total_pnl, 2),
        "total_pips": round(total_pips, 1),
        "avg_slippage": round(avg_slippage, 6),
        "slippage_count": len(slippage_trades),
        "zero_pnl_trades": [
            {"id": t["id"], "symbol": t["symbol"], "close_reason": t.get("close_reason")}
            for t in zero_pnl
        ],
        "null_pnl_trades": [
            {"id": t["id"], "symbol": t["symbol"], "close_reason": t.get("close_reason")}
            for t in null_pnl
        ],
        "close_reasons": close_reasons,
        "by_pattern": by_pattern,
        "by_pair": by_pair,
        "consecutive_losses": consecutive_losses,
    }


def pattern_stats(conn):
    """Get pattern arming/triggering/rejection stats."""
    cur = conn.cursor()
    cur.execute(
        "SELECT * FROM pattern_records WHERE detected_at >= ? ORDER BY id",
        (GO_LIVE_DATE,),
    )
    patterns = [dict(r) for r in cur.fetchall()]

    by_status = {}
    for p in patterns:
        s = p["status"]
        by_status[s] = by_status.get(s, 0) + 1

    # Rejection reasons — check recent events
    cur.execute(
        "SELECT details FROM event_logs WHERE event_type = 'TRADE_REJECTED' "
        "AND timestamp >= ? ORDER BY id DESC LIMIT 50",
        (GO_LIVE_DATE,),
    )
    rejection_reasons = {}
    for row in cur.fetchall():
        detail = row["details"] or ""
        # Extract check name: "Check=rrr_check: ..."
        if "Check=" in detail:
            check = detail.split("Check=")[1].split(":")[0]
            rejection_reasons[check] = rejection_reasons.get(check, 0) + 1

    # Most rejected pairs
    rejected_by_pair = {}
    for p in patterns:
        if p["status"] == "REJECTED":
            sym = p["symbol"]
            rejected_by_pair[sym] = rejected_by_pair.get(sym, 0) + 1

    armed = by_status.get("ARMED", 0)
    triggered = by_status.get("TRIGGERED", 0)
    rejected = by_status.get("REJECTED", 0)
    expired = by_status.get("EXPIRED", 0)
    total = len(patterns)

    return {
        "total_patterns": total,
        "by_status": by_status,
        "trigger_rate": round(triggered / max(armed + triggered + expired, 1) * 100, 1),
        "rejection_reasons": rejection_reasons,
        "rejected_by_pair": rejected_by_pair,
    }


def mt5_account():
    """Get current MT5 account info."""
    try:
        import MetaTrader5 as mt5
        mt5.initialize()
        info = mt5.account_info()
        if info:
            result = {
                "balance": info.balance,
                "equity": info.equity,
                "free_margin": info.margin_free,
                "margin_used": info.margin,
                "currency": info.currency,
            }
        else:
            result = {"error": "No account info"}
        mt5.shutdown()
        return result
    except Exception as e:
        return {"error": str(e)}


def main():
    now = datetime.now(timezone.utc)
    conn = get_db_connection()

    report = {
        "generated_at": now.isoformat(),
        "go_live_date": GO_LIVE_DATE,
        "bot_status": bot_status(),
        "last_scan": last_scan_time(),
        "recent_errors": recent_log_errors(),
        "account": mt5_account(),
        "trades": trade_stats(conn),
        "patterns": pattern_stats(conn),
        "benchmarks": {
            "backtest_pf": 1.53,
            "backtest_wr": 61.0,
            "expected_live_pf_range": [1.15, 1.30],
            "expected_max_dd_pct": 35,
            "milestone_trades": 50,
            "m8_review_threshold": 50,
        },
    }

    conn.close()
    print(json.dumps(report, indent=2, default=str))


if __name__ == "__main__":
    main()
