"""How many INDEPENDENT instruments does the universe actually contain? (spec 8.36, step 4)

8.35's warning, run before the backtest rather than after it: fifty tickers are not fifty
draws. US 5Y/10Y/30Y yields move together, the six crypto series are one crypto bet, the
GBP and EUR crosses share a leg, and the equity indices are one global risk factor wearing
fifteen hats. If the expanded universe is counted by ticker, we will believe we have
satisfied 8.34's requirement while having bought almost nothing.

The whole point of running this first is that its answer cannot then be negotiated after
seeing the returns.

Two estimators, both on daily log returns over the common window:

* **Participation ratio** of the correlation matrix's eigenvalues,
  `N_eff = (sum L)^2 / sum(L^2)`. This is the standard spectral measure of how many
  directions the data actually varies in.
* **Equicorrelation design effect**, `N_eff = N / (1 + (N-1) * rho_bar)`, using mean
  absolute off-diagonal correlation. Cruder, but it is the number that plugs directly
  into a power calculation.

The honest planning figure is the smaller of the two.
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from hvf_trader.detector.hvf_v2 import load_ohlc  # noqa: E402

DIRS = [ROOT / "backtests" / "data" / "hvf_v2", ROOT / "backtests" / "data"]
MIN_OVERLAP = 750          # trading days two series must share to be compared


def daily_close(path):
    df = load_ohlc(str(path))
    s = df.set_index("dt")["close"]
    return s.resample("1D").last().dropna()


def main():
    series, skipped = {}, []
    for d in DIRS:
        for f in sorted(list(d.glob("*_D1.csv")) + list(d.glob("*_H1.csv"))):
            name = f.stem.replace("_D1", "").replace("_H1", "")
            if name in series:
                continue                      # prefer the first dir (hvf_v2)
            try:
                s = daily_close(f)
            except Exception as e:            # noqa: BLE001
                skipped.append((f.stem, str(e)[:45]))
                continue
            if len(s) < MIN_OVERLAP:
                skipped.append((f.stem, f"only {len(s)} daily closes"))
                continue
            series[name] = s

    px = pd.DataFrame(series).sort_index()
    ret = np.log(px).diff()
    # Pairwise-complete correlation: these series start in different decades, so
    # requiring one common window would throw away most of the universe.
    C = ret.corr(min_periods=MIN_OVERLAP)
    keep = C.notna().sum() >= max(3, 0.5 * len(C))
    C = C.loc[keep, keep]
    names = list(C.columns)
    M = C.to_numpy(float)
    M = np.where(np.isnan(M), 0.0, M)
    np.fill_diagonal(M, 1.0)

    N = len(names)
    ev = np.linalg.eigvalsh((M + M.T) / 2.0)
    ev = np.clip(ev, 0, None)
    pr = ev.sum() ** 2 / (ev ** 2).sum()
    off = M[~np.eye(N, dtype=bool)]
    rho = np.abs(off).mean()
    deff = N / (1 + (N - 1) * rho)

    print(f"universe: {N} instruments with a usable return history")
    print(f"  skipped: {len(skipped)}")
    for s, why in skipped[:12]:
        print(f"    {s:<22}{why}")
    print(f"\nmean |pairwise correlation|   {rho:>8.3f}")
    print(f"N_eff  participation ratio    {pr:>8.1f}   of {N}")
    print(f"N_eff  equicorrelation        {deff:>8.1f}   of {N}")
    print(f"\n=> PLANNING FIGURE            {min(pr, deff):>8.1f} independent instruments")

    # Which blocks are redundant: greedy grouping at |r| >= 0.7.
    print("\nredundant blocks (|r| >= 0.7):")
    used, blocks = set(), []
    order = np.argsort(-np.abs(M).sum(axis=1))
    for i in order:
        if names[i] in used:
            continue
        grp = [names[j] for j in range(N)
               if abs(M[i, j]) >= 0.7 and names[j] not in used]
        if len(grp) > 1:
            blocks.append(grp)
            used.update(grp)
    for b in blocks:
        print(f"  {len(b):>2}  {', '.join(sorted(b))}")
    singles = [n for n in names if n not in used]
    print(f"\n{len(blocks)} blocks + {len(singles)} independent singles "
          f"= {len(blocks) + len(singles)} effective (block-count method)")


if __name__ == "__main__":
    main()
