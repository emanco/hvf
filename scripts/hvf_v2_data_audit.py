"""Audit every H1 file for usable HVF history (spec 8.35).

8.30a found the trap: these H1 CSVs carry DAILY bars in their early years -- ~260 rows
where an hourly file should have thousands -- so a naive "history starts 2004" reads 16
years of junk resolution as real. Every instrument added to the universe has to be checked
the same way before it can contribute a single trade.

For each file: report the first year whose row count clears a fraction of the expected
hourly density, and how many usable years follow.
"""
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

DIRS = [ROOT / "backtests" / "data", ROOT / "backtests" / "data" / "hvf_v2"]
DENSE = 0.35          # fraction of a 24x365 year that counts as genuinely hourly
FX_YEAR = 24 * 252    # ~6,048 bars: FX/CFD trade ~5 days a week


def main():
    seen, rows = {}, []
    for d in DIRS:
        for f in sorted(d.glob("*_H1.csv")):
            if f.stem in seen:
                continue
            seen[f.stem] = f
            try:
                df = pd.read_csv(f, usecols=[0], names=["dt"], header=0)
                col = df["dt"]
                # These files store epoch SECONDS, not datetime strings; parsing them
                # as strings silently yields 1970 for every row.
                num = pd.to_numeric(col, errors="coerce")
                if num.notna().mean() > 0.9:
                    dt = pd.to_datetime(num, unit="s", utc=True, errors="coerce")
                else:
                    dt = pd.to_datetime(col, format="mixed", utc=True, errors="coerce")
                dt = dt.dropna()
            except Exception as e:                      # noqa: BLE001
                rows.append((f.stem, "UNREADABLE", str(e)[:40], 0, 0, ""))
                continue
            per = dt.dt.year.value_counts().sort_index()
            dense = per[per >= DENSE * FX_YEAR]
            if dense.empty:
                rows.append((f.stem, "-", "no dense year", len(dt), 0, ""))
                continue
            y0 = int(dense.index[0])
            usable = int(dense.index[-1]) - y0 + 1
            rows.append((f.stem, str(y0), f"{int(per.loc[y0]):,}/yr",
                         len(dt), usable, f"{dense.index[-1]}"))

    rows.sort(key=lambda r: (-r[4], r[0]))
    print(f"{'file':<20}{'dense from':>12}{'that yr':>12}{'total rows':>13}"
          f"{'usable yrs':>12}{'to':>7}")
    print("-" * 76)
    for r in rows:
        print(f"{r[0]:<20}{r[1]:>12}{r[2]:>12}{r[3]:>13,}{r[4]:>12}{r[5]:>7}")
    print("-" * 76)
    ok = [r for r in rows if r[4] >= 6]
    print(f"{len(rows)} H1 files, {len(ok)} with >=6 usable years")


if __name__ == "__main__":
    main()
