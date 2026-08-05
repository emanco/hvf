"""Fetch the expanded HVF instrument universe as daily OHLC (spec 8.36, steps 1-3).

8.34 put the sample requirement at ~50 instruments; 8.35 found we hold ~25 and that
Hunt's largest single category -- sovereign bond yields, 43% of his charts -- is entirely
absent. This closes the gap.

Source is Yahoo's chart endpoint: real OHLC, daily, no key, and it spans yields,
commodities, FX, indices and credit in one code path. Two sources were tried and
rejected -- stooq is behind a JavaScript proof-of-work challenge, and FRED's
international yield series are monthly (843 rows of history) and close-only, which is
both too coarse for a 3D/1W funnel and unable to supply the high/low that 8.35 confirmed
Hunt's tool uses (`Source H/L`).

**Why the yield block is US-only.** German, Swiss and Japanese yields traded below zero.
`load_ohlc` rejects non-positive prices outright, and more fundamentally a
fixed-PERCENTAGE ZigZag is undefined across zero -- a 0.5% box has no meaning when the
series crosses from +0.2 to -0.2. Hunt's own AU 10Y and NO 3Y charts sit in a positive-rate
era, but a backtest spanning 2010-2022 would not. So the non-US yields he trades are
excluded for a structural reason, not a sourcing one, and this is recorded as a genuine
gap rather than papered over.

Written as daily bars in the repo's own CSV convention (epoch-second `time`), so
`load_ohlc` reads them unchanged.
"""
import sys
import time
import urllib.request
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "backtests" / "data" / "hvf_v2"
UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"}

# name -> yahoo symbol. Grouped by the independence they are meant to buy;
# see 8.36 on why a ticker count is not a draw count.
UNIVERSE = {
    # -- US sovereign yields (step 1). Hunt's largest category, positive-rate only.
    "US13W_Y": "^IRX", "US05Y_Y": "^FVX", "US10Y_Y": "^TNX", "US30Y_Y": "^TYX",
    # -- Commodities (step 2)
    "BRENT": "BZ=F", "NATGAS": "NG=F", "COPPER": "HG=F", "PLATINUM": "PL=F",
    "PALLADIUM": "PA=F", "CORN": "ZC=F", "WHEAT": "ZW=F", "COFFEE": "KC=F",
    "SUGAR": "SB=F", "COTTON": "CT=F", "SOYBEAN": "ZS=F", "CATTLE": "LE=F",
    # -- FX, including the four crosses whose repo files carry a row index for a
    #    timestamp (step 3), plus Hunt's own USD/KRW.
    "GBPAUD": "GBPAUD=X", "GBPCAD": "GBPCAD=X", "GBPCHF": "GBPCHF=X",
    "GBPNZD": "GBPNZD=X", "USDKRW": "USDKRW=X", "AUDUSD": "AUDUSD=X",
    "USDCAD": "USDCAD=X", "USDNOK": "USDNOK=X", "USDSEK": "USDSEK=X",
    "USDMXN": "USDMXN=X", "USDZAR": "USDZAR=X", "USDTRY": "USDTRY=X",
    "USDINR": "USDINR=X", "EURCHF": "EURCHF=X", "AUDJPY": "AUDJPY=X",
    "DXY": "DX-Y.NYB",
    # -- Equity indices, spread across regions
    "SPX": "^GSPC", "NDX": "^NDX", "DJI": "^DJI", "RUT": "^RUT",
    "DAX": "^GDAXI", "FTSE": "^FTSE", "CAC": "^FCHI", "SMI": "^SSMI",
    "NIKKEI": "^N225", "HSI": "^HSI", "ASX": "^AXJO", "BVSP": "^BVSP",
    "SENSEX": "^BSESN", "KOSPI": "^KS11", "TSX": "^GSPTSE",
    # -- Credit and rates ETFs (Hunt trades HYG itself)
    "HYG_ETF": "HYG", "LQD_ETF": "LQD", "TLT_ETF": "TLT", "IEF_ETF": "IEF",
    "EMB_ETF": "EMB", "AGG_ETF": "AGG", "TIP_ETF": "TIP",
    # -- Volatility and metals not already held
    "VIX": "^VIX", "PALL_ETF": "PALL",
}


def fetch(sym):
    # `range=max` is a trap: Yahoo silently downgrades granularity to 3mo while
    # still echoing the requested interval, so it returns ~168 QUARTERLY bars
    # labelled daily. Explicit period1/period2 is the only way to get the real
    # series. Same family of silent defect as 8.30a's daily bars in an H1 file --
    # always assert on the granularity actually returned, never on what was asked.
    url = (f"https://query1.finance.yahoo.com/v8/finance/chart/"
           f"{urllib.request.quote(sym)}?period1=0&period2=9999999999&interval=1d")
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=45) as r:
        j = __import__("json").loads(r.read())
    res = j["chart"]["result"][0]
    gran = res["meta"].get("dataGranularity")
    if gran != "1d":
        raise ValueError(f"granularity is {gran}, not 1d")
    q = res["indicators"]["quote"][0]
    df = pd.DataFrame({
        "time": res["timestamp"],
        "open": q["open"], "high": q["high"], "low": q["low"], "close": q["close"],
        "tick_volume": q.get("volume") or [0] * len(res["timestamp"]),
    })
    df = df.dropna(subset=["open", "high", "low", "close"])
    df["tick_volume"] = df["tick_volume"].fillna(0)
    df["spread"] = 0
    # Yahoo occasionally emits a zero or negative print on thin index series;
    # load_ohlc would reject the whole file for it, so drop the bar instead.
    df = df[(df[["open", "high", "low", "close"]] > 0).all(axis=1)]
    return df.astype({"time": "int64"}).sort_values("time").reset_index(drop=True)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    ok, bad = [], []
    for name, sym in UNIVERSE.items():
        dest = OUT / f"{name}_D1.csv"
        if dest.exists():
            ok.append((name, len(pd.read_csv(dest)), "cached"))
            continue
        try:
            df = fetch(sym)
            if len(df) < 500:
                bad.append((name, sym, f"only {len(df)} bars"))
                continue
            df.to_csv(dest, index=False)
            yrs = (df["time"].iloc[-1] - df["time"].iloc[0]) / 31_557_600
            ok.append((name, len(df), f"{yrs:.0f}y"))
            print(f"  {name:<12} {sym:<12} {len(df):>7,} bars  {yrs:>5.0f}y", flush=True)
        except Exception as e:                                   # noqa: BLE001
            bad.append((name, sym, type(e).__name__ + ": " + str(e)[:50]))
            print(f"  {name:<12} {sym:<12} FAILED {e}", flush=True)
        time.sleep(0.6)

    print(f"\n{len(ok)} fetched, {len(bad)} failed")
    for n, s, why in bad:
        print(f"  FAIL {n:<12} {s:<12} {why}")
    return 0 if len(ok) >= 30 else 1


if __name__ == "__main__":
    sys.exit(main())
