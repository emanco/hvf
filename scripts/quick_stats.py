"""Quick performance stats since go-live."""
import sqlite3

conn = sqlite3.connect(r"C:\hvf_trader\hvf_trader.db")
cur = conn.cursor()

GO_LIVE = "2026-03-25"

cur.execute(
    "SELECT COUNT(*), SUM(CASE WHEN pnl_pips > 0 THEN 1 ELSE 0 END), SUM(pnl_pips), SUM(pnl) "
    "FROM trade_records WHERE opened_at >= ? AND status = 'CLOSED'",
    (GO_LIVE,))
total, wins, pips, pnl = cur.fetchone()
wins = wins or 0
pips = pips or 0
pnl = pnl or 0
wr = wins / total * 100 if total else 0

print("=" * 60)
print("  KZ_HUNT Performance Since %s" % GO_LIVE)
print("=" * 60)
print("  Trades: %d  Wins: %d  WR: %.1f%%" % (total, wins, wr))
print("  PnL: %+.0f pips  $%+.0f" % (pips, pnl))

cur.execute(
    "SELECT SUM(pnl_pips) FROM trade_records WHERE opened_at >= ? AND status = 'CLOSED' AND pnl_pips > 0",
    (GO_LIVE,))
gp = cur.fetchone()[0] or 0
cur.execute(
    "SELECT ABS(SUM(pnl_pips)) FROM trade_records WHERE opened_at >= ? AND status = 'CLOSED' AND pnl_pips <= 0",
    (GO_LIVE,))
gl = cur.fetchone()[0] or 0.001
print("  PF: %.2f  (gross_profit=%+.0f, gross_loss=%.0f)" % (gp / gl, gp, gl))

print("\n  Per symbol:")
cur.execute(
    "SELECT symbol, COUNT(*), SUM(CASE WHEN pnl_pips > 0 THEN 1 ELSE 0 END), SUM(pnl_pips), SUM(pnl) "
    "FROM trade_records WHERE opened_at >= ? AND status = 'CLOSED' GROUP BY symbol ORDER BY SUM(pnl_pips) DESC",
    (GO_LIVE,))
for sym, cnt, w, p, u in cur.fetchall():
    wr2 = (w or 0) / cnt * 100 if cnt else 0
    print("  %-8s %3d trades  WR=%4.0f%%  pips=%+6.0f  USD=%+7.0f" % (sym, cnt, wr2, p or 0, u or 0))

print("\n  Close reasons:")
cur.execute(
    "SELECT close_reason, COUNT(*), SUM(pnl_pips) FROM trade_records "
    "WHERE opened_at >= ? AND status = 'CLOSED' GROUP BY close_reason ORDER BY COUNT(*) DESC",
    (GO_LIVE,))
for reason, cnt, p in cur.fetchall():
    print("  %-15s %3d trades  pips=%+6.0f" % (reason, cnt, p or 0))

print("\n  Last 10 trades:")
cur.execute(
    "SELECT id, symbol, direction, pnl_pips, pnl, close_reason, opened_at "
    "FROM trade_records WHERE status = 'CLOSED' ORDER BY id DESC LIMIT 10")
for tid, sym, d, p, u, r, opened in cur.fetchall():
    print("  #%-3d %-8s %-5s %+7.1fp  $%+7.0f  %s  %s" % (
        tid, sym, d, p or 0, u or 0, r, opened[:16] if opened else ""))

conn.close()
