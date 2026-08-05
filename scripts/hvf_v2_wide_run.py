"""The wide run: frozen spec, expanded universe (spec 8.36, step 5).

Nothing here is tuned. Detection, direction gate, 0.5% box, entry at the 5th pivot, stop
at the 6th, three-wave centre-anchored exit with breakeven at TP1, `top()` selection --
all exactly as they stand after 8.31. The only new thing is the instrument list.

**Pre-registered choices, fixed before any result was seen** (8.36 step 4 was run first
precisely so these could not be negotiated afterwards):

* One timeframe per instrument, no sweep. D1-sourced instruments run at **3D**, which is
  what Hunt draws his bond-yield charts on. H1-sourced instruments run at **4h**. The
  eight original charts keep their own timeframes.
* The new instruments have never been looked at, so their **entire history is
  out-of-sample** -- there is no need to truncate at 2023 the way 8.30 had to, and doing
  so would only discard blind data.
* Inference is at the **instrument level**, not the trade level. Each instrument
  contributes one number (its mean net R). This is the correct unit given how badly
  trades cluster within an instrument, and it is why 8.36 step 4 measured N_eff first.

Financing is charged as in 8.33, per asset class, on the decaying position.
"""
import contextlib
import io
import pickle
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

with contextlib.redirect_stdout(io.StringIO()):
    import hvf_v2_mef_waves as W
    from hvf_trader.detector.hvf_v2 import load_ohlc, resample_ohlc
    from hvf_v2_mef_carry_blind import simulate_detail

CACHE = Path("/private/tmp/claude-501/-Users-manu-Dev-atspass/"
             "a663a16a-0df5-4d89-a954-fdf163a2a14e/scratchpad/wide.pkl")
DIRS = [ROOT / "backtests" / "data" / "hvf_v2", ROOT / "backtests" / "data"]

# Annual financing on notional, %/yr, by asset class (8.33's sweep, central values).
# Yields are not directly tradeable -- they stand in for the futures/ETF that is, so
# their rate is the general funding rate rather than a published swap line.
RATE = {"yield": 5.0, "etf": 5.0, "index": 5.0, "fx": 2.0,
        "commodity": 7.0, "metal": 7.0, "crypto": 20.0}

CRYPTO = {"BTCUSD", "ETHUSD", "LTCUSD", "ADAUSD", "BNBUSD", "DOGUSD", "SOLUSD"}
METAL = {"XAUUSD", "XAGUSD", "XAUEUR", "PLATINUM", "PALLADIUM", "COPPER", "PALL_ETF"}
COMMOD = {"XTIUSD", "BRENT", "NATGAS", "CORN", "WHEAT", "COFFEE", "SUGAR",
          "COTTON", "SOYBEAN", "CATTLE"}
INDEX = {"SPX", "NDX", "DJI", "RUT", "DAX", "FTSE", "CAC", "SMI", "NIKKEI", "HSI",
         "ASX", "BVSP", "SENSEX", "KOSPI", "TSX", "US500", "DE40", "UK100", "JP225",
         "VIX", "DXY"}


def klass(name):
    if name.endswith("_Y"):
        return "yield"
    if name.endswith("_ETF"):
        return "etf"
    if name in CRYPTO:
        return "crypto"
    if name in METAL:
        return "metal"
    if name in COMMOD:
        return "commodity"
    if name in INDEX:
        return "index"
    return "fx"


def universe():
    """Every file that load_ohlc accepts, at its pre-registered timeframe."""
    out, seen = [], set()
    for d in DIRS:
        for f in sorted(list(d.glob("*_D1.csv")) + list(d.glob("*_H1.csv"))):
            name = f.stem.rsplit("_", 1)[0]
            if name in seen:
                continue
            hours = 72.0 if f.stem.endswith("_D1") else 4.0
            try:
                df = load_ohlc(str(f))
            except Exception:                                  # noqa: BLE001
                continue
            seen.add(name)
            out.append((name, f, hours, df))
    return out


def main():
    store = {}
    if CACHE.exists():
        store = pickle.loads(CACHE.read_bytes())

    rows = []
    for name, f, hours, df in universe():
        if name not in store:
            frame = resample_ohlc(df, hours) if hours != 1.0 else df
            if len(frame) < 600:
                store[name] = None
            else:
                c0 = dict(name=name, hours=hours, src=f.stem, ratio=None)
                try:
                    picks = W.top(W.enumerate_window(c0, W.BOX, frame))
                    det = simulate_detail(frame, picks, hours, "waves")
                except Exception as e:                          # noqa: BLE001
                    print(f"  {name:<12} FAILED {type(e).__name__}: {e}", flush=True)
                    store[name] = None
                    det = None
                if det is not None:
                    r = RATE[klass(name)]
                    store[name] = dict(
                        bars=len(frame), n=len(det),
                        net=[x[0] - x[1] * r / 100.0 / 365.0 for x in det],
                        gross=[x[0] for x in det],
                        days=[x[2] for x in det], klass=klass(name))
                    print(f"  {name:<12} {hours:>5.0f}h  {len(frame):>7,} bars  "
                          f"{len(det):>4} trades", flush=True)
            CACHE.write_bytes(pickle.dumps(store))
        s = store[name]
        if s and s["n"] >= 15:
            rows.append(dict(name=name, klass=s["klass"], n=s["n"],
                             gross=float(np.mean(s["gross"])),
                             net=float(np.mean(s["net"])),
                             med_d=float(np.median(s["days"]))))

    df = pd.DataFrame(rows).sort_values("net", ascending=False)
    print(f"\n{'=' * 78}\nPER-INSTRUMENT, frozen spec, three-wave exit, net of financing")
    print("=" * 78)
    print(f"{'instrument':<14}{'class':<11}{'n':>6}{'med d':>8}{'gross':>9}{'net':>9}")
    print("-" * 78)
    for _, r in df.iterrows():
        print(f"{r['name']:<14}{r['klass']:<11}{r['n']:>6}{r['med_d']:>8.1f}"
              f"{r['gross']:>9.2f}{r['net']:>9.2f}")
    print("-" * 78)

    print(f"\n{'class':<12}{'k':>5}{'trades':>9}{'mean net':>11}")
    for k, g in df.groupby("klass"):
        print(f"{k:<12}{len(g):>5}{g['n'].sum():>9}{g['net'].mean():>11.3f}")

    # Instrument-level inference. N_eff from 8.36 step 4 (participation ratio).
    N_EFF = 15.7
    m = df["net"].to_numpy(float)
    k = len(m)
    print(f"\n{'=' * 78}\nINSTRUMENT-LEVEL INFERENCE\n{'=' * 78}")
    print(f"  instruments (nominal)      {k:>8}")
    print(f"  total trades               {int(df['n'].sum()):>8,}")
    print(f"  mean of per-instrument net {m.mean():>8.3f} R")
    print(f"  sd across instruments      {m.std(ddof=1):>8.3f} R")
    print(f"  positive instruments       {int((m > 0).sum()):>8} / {k}")
    eff = min(N_EFF, k)
    se = m.std(ddof=1) / np.sqrt(eff)
    print(f"  N_eff (8.36 step 4)        {eff:>8.1f}")
    print(f"  SE on N_eff draws          {se:>8.3f}")
    print(f"  t                          {m.mean() / se:>8.2f}   (need ~1.65)")


if __name__ == "__main__":
    main()
