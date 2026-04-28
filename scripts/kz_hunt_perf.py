"""KZ_HUNT performance breakdown since go-live."""
import sqlite3
from collections import defaultdict
from datetime import datetime

GO_LIVE = "2026-03-25"
conn = sqlite3.connect(r"C:\hvf_trader\hvf_trader.db")
cur = conn.cursor()

cur.execute("""
SELECT id, symbol, direction, opened_at, closed_at, status, pnl, pnl_pips,
       entry_price, stop_loss, target_1, target_2, lot_size, close_reason
FROM trade_records
WHERE pattern_type = 'KZ_HUNT'
  AND opened_at >= ?
ORDER BY opened_at
""", (GO_LIVE,))

rows = cur.fetchall()
print(f"Total KZ_HUNT trades since {GO_LIVE}: {len(rows)}")
closed = [r for r in rows if r[5] == "CLOSED"]
open_ = [r for r in rows if r[5] != "CLOSED"]
print(f"Closed: {len(closed)}, Open/other: {len(open_)}")
print()

if closed:
    pnls = [r[6] or 0 for r in closed]
    pips = [r[7] or 0 for r in closed]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]
    total_pnl = sum(pnls)
    total_pips = sum(pips)
    print(f"Total PnL: ${total_pnl:+.2f}  Total pips: {total_pips:+.1f}")
    print(f"Wins: {len(wins)} / Losses: {len(losses)} (WR {len(wins)/len(closed)*100:.0f}%)")
    if wins and losses:
        gp = sum(wins); gl = abs(sum(losses))
        print(f"Avg win: ${sum(wins)/len(wins):+.2f}  Avg loss: ${sum(losses)/len(losses):+.2f}")
        print(f"Gross profit: ${gp:.2f}  Gross loss: ${gl:.2f}  PF: {gp/gl:.2f}")

    # Per pair
    print("\nPer pair:")
    by_sym = defaultdict(list)
    for r in closed:
        by_sym[r[1]].append((r[6] or 0, r[7] or 0))
    for sym in sorted(by_sym, key=lambda s: -sum(p for p, _ in by_sym[s])):
        ts = by_sym[sym]
        n = len(ts)
        w = sum(1 for p, _ in ts if p > 0)
        tot_pnl = sum(p for p, _ in ts)
        tot_pips = sum(pp for _, pp in ts)
        print(f"  {sym}: n={n:3d} WR={w/n*100:.0f}% Tot=${tot_pnl:+8.2f} ({tot_pips:+.0f}p)")

    # Per close reason
    print("\nPer close reason:")
    by_reason = defaultdict(list)
    for r in closed:
        by_reason[r[13] or "UNKNOWN"].append((r[6] or 0, r[7] or 0))
    for reason, ts in sorted(by_reason.items(), key=lambda x: -sum(p for p, _ in x[1])):
        n = len(ts)
        tot = sum(p for p, _ in ts)
        print(f"  {reason}: n={n:3d} Tot=${tot:+.2f}")

    # Weekly progression
    print("\nWeekly:")
    by_week = defaultdict(list)
    for r in closed:
        d = datetime.fromisoformat(r[3]).isocalendar()
        key = f"{d.year}-W{d.week:02d}"
        by_week[key].append(r[6] or 0)
    cum = 0
    for wk in sorted(by_week):
        arr = by_week[wk]
        wk_pnl = sum(arr)
        cum += wk_pnl
        n = len(arr)
        w = sum(1 for p in arr if p > 0)
        print(f"  {wk}: n={n:3d} WR={w/n*100:.0f}% Wk=${wk_pnl:+8.2f} Cum=${cum:+.2f}")

conn.close()
