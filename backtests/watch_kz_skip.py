"""Local check on KZ_HUNT skip-conf cohort.

Run from your Mac. SSHes the VPS, pulls every KZ_HUNT trade opened since
the skip-conf live deploy (2026-05-12 10:50 UTC), and reports cohort
stats + per-trade detail. Compares against the backtest expectation
(PF ~1.15 over 100+ trades on EURGBP+NZDUSD).

Usage: python3 backtests/watch_kz_skip.py
"""
import subprocess
import sys
import tempfile
from pathlib import Path

# VPS clock is UTC+1; the deploy at 10:50 local = 09:50 UTC.
SKIP_CONF_DEPLOY_UTC = "2026-05-12 09:50:00"
EXPECTED_PF_RANGE = (1.05, 1.30)
EXPECTED_WR_RANGE = (40, 55)

REMOTE_SCRIPT = f"""
import sqlite3
conn = sqlite3.connect(r'C:\\\\hvf_trader\\\\hvf_trader.db')
cur = conn.cursor()
cur.execute('''
    SELECT t.id, t.symbol, t.direction, t.entry_price, p.entry_price,
           t.stop_loss, t.target_1, t.close_price, t.pnl_pips, t.pnl,
           t.close_reason, t.pnl_estimated, t.opened_at, t.closed_at,
           t.status
    FROM trade_records t
    LEFT JOIN pattern_records p ON t.pattern_id = p.id
    WHERE t.pattern_type = 'KZ_HUNT'
      AND t.opened_at >= '{SKIP_CONF_DEPLOY_UTC}'
    ORDER BY t.id
''')
for r in cur.fetchall():
    print('|'.join(str(x) if x is not None else '' for x in r))
conn.close()
"""


def run_remote(script: str) -> list[list[str]]:
    # Write the script to a temp file, scp it to the VPS, run it, delete it
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".py", delete=False,
    ) as f:
        f.write(script)
        local_path = f.name
    remote_path = "C:/hvf_trader/_watch_kz_temp.py"
    try:
        subprocess.run(
            ["scp", local_path, f"hvf-vps:{remote_path}"],
            check=True, capture_output=True, text=True, timeout=20,
        )
        result = subprocess.run(
            ["ssh", "hvf-vps",
             f"C:\\hvf_trader\\venv\\Scripts\\python.exe {remote_path}; "
             f"Remove-Item {remote_path} -ErrorAction SilentlyContinue"],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode != 0:
            print("SSH failed:", result.stderr, file=sys.stderr)
            sys.exit(1)
    finally:
        Path(local_path).unlink(missing_ok=True)
    rows = []
    for line in result.stdout.strip().splitlines():
        rows.append(line.split("|"))
    return rows


def main():
    rows = run_remote(REMOTE_SCRIPT)
    if not rows or rows == [[""]]:
        print(f"No KZ_HUNT trades since {SKIP_CONF_DEPLOY_UTC} UTC yet.")
        return

    print(f"KZ_HUNT skip-conf cohort (since {SKIP_CONF_DEPLOY_UTC} UTC)")
    print("=" * 100)
    print(
        f"{'id':<4} {'sym':<7} {'dir':<5} {'fill':<8} {'limit':<8} {'drift':<5} "
        f"{'pnl_p':>7} {'pnl$':>8} {'reason':<14} {'opened (UTC)':<19} {'status':<7}"
    )
    print("-" * 100)

    closed = []
    open_count = 0
    drift_sum = 0.0
    drift_n = 0
    for r in rows:
        tid = r[0]
        sym = r[1]
        direction = r[2]
        fill = float(r[3]) if r[3] else 0.0
        limit = float(r[4]) if r[4] else 0.0
        pnl_p = float(r[8]) if r[8] else 0.0
        pnl_d = float(r[9]) if r[9] else 0.0
        reason = r[10]
        opened = r[12][:19]
        status = r[14]
        # pip value heuristic
        pip = 0.01 if "JPY" in sym else 0.0001
        drift = (fill - limit) / pip if limit else 0.0
        # For SHORT we want fill <= limit (sold AT or ABOVE limit is good); for
        # LONG we want fill >= limit. So adverse drift = LONG: fill > limit,
        # SHORT: fill < limit. Sign convention: positive = adverse fill.
        adverse = drift if direction == "LONG" else -drift
        drift_sum += adverse
        drift_n += 1
        print(
            f"{tid:<4} {sym:<7} {direction:<5} {fill:<8.5f} {limit:<8.5f} "
            f"{adverse:>+4.1f}p {pnl_p:>+7.1f} {pnl_d:>+8.2f} "
            f"{reason or '':<14} {opened:<19} {status:<7}"
        )
        if status == "CLOSED":
            closed.append((pnl_p, pnl_d))
        else:
            open_count += 1

    print()
    print(f"Total fills: {len(rows)}  (open: {open_count}, closed: {len(closed)})")
    if drift_n:
        print(f"Avg adverse drift fill vs limit: {drift_sum/drift_n:+.2f} pips")

    if not closed:
        print("\nNo closed trades yet — keep watching.")
        return

    wins = [c for c in closed if c[0] > 0]
    losses = [c for c in closed if c[0] < 0]
    n = len(closed)
    wr = len(wins) / n * 100 if n else 0
    gw = sum(c[0] for c in wins) if wins else 0
    gl = abs(sum(c[0] for c in losses)) if losses else 0
    pf = gw / gl if gl else float("inf")
    total_p = sum(c[0] for c in closed)
    total_d = sum(c[1] for c in closed)
    print()
    print("Cohort performance (closed trades only):")
    print(f"  Wins / Losses: {len(wins)} / {len(losses)}")
    print(f"  Win rate:      {wr:.1f}%  (expected: {EXPECTED_WR_RANGE[0]}-{EXPECTED_WR_RANGE[1]}%)")
    print(f"  Profit factor: {pf:.2f}  (expected: {EXPECTED_PF_RANGE[0]}-{EXPECTED_PF_RANGE[1]})")
    print(f"  Total pips:    {total_p:+.1f}")
    print(f"  Total USD:     ${total_d:+.2f}")

    # Verdict heuristics
    print()
    flags = []
    if n < 10:
        flags.append(f"N={n} is too small for verdict. Need ~20 trades.")
    else:
        if pf < EXPECTED_PF_RANGE[0]:
            flags.append(f"PF {pf:.2f} below expected band — investigate.")
        elif pf > EXPECTED_PF_RANGE[1]:
            flags.append(f"PF {pf:.2f} ABOVE expected band — likely small-N noise.")
        if wr < EXPECTED_WR_RANGE[0]:
            flags.append(f"WR {wr:.1f}% below expected band.")
        if drift_n and drift_sum / drift_n > 1.0:
            flags.append(
                f"Avg adverse fill drift {drift_sum/drift_n:+.2f}p > 1p — "
                "live fills are materially worse than backtest limit prices."
            )
    if flags:
        print("FLAGS:")
        for f in flags:
            print(f"  - {f}")
    else:
        print("No flags — cohort tracking backtest expectation.")


if __name__ == "__main__":
    main()
