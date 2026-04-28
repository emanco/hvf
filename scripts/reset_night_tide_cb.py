"""One-shot: reset NIGHT_TIDE per-pair circuit breaker counters.

Run on VPS to clear the 2 fake consecutive-loss entries created by the
2026-04-28 pipework test (manual closes mis-attributed as SL fills).
"""
import sqlite3

conn = sqlite3.connect(r"C:\hvf_trader\hvf_trader.db")
cur = conn.cursor()
cur.execute(
    "UPDATE pattern_circuit_breaker_states "
    "SET consecutive_losses = 0, paused_until = NULL "
    "WHERE pattern_type = 'NIGHT_TIDE'"
)
conn.commit()
print(f"Updated {cur.rowcount} row(s)")
cur.execute(
    "SELECT pattern_type, symbol, consecutive_losses, paused_until "
    "FROM pattern_circuit_breaker_states WHERE pattern_type = 'NIGHT_TIDE'"
)
for r in cur.fetchall():
    print(r)
conn.close()
