"""A FRESH instrument universe -- never touched by any test in this programme.

Why this exists. The 79 instruments of 8.36 have now absorbed three "one principled
change" tests: 8.20's rank, 8.32's RRR band and 8.39's limit entry. That is multiple
comparisons against a single sample, and it is how the 8.36c and 8.37b verdicts rotted.
The forming arm (hvf_signal.scan) is the fourth such change and by far the largest --
every one of the 53,653 historical picks was detected on a CONFIRMED funnel, which is
the exact mechanism that put 34.1% of entries behind price -- so it deserves clean data
rather than the fourth draw on a spent holdout.

Every symbol below is disjoint from UNIVERSE in hvf_v2_fetch_universe.py. Verified at
import, not by eye: see the assertion at the bottom.

Class mix is kept close to the original so the result generalises the same way. It does
not need to be for the comparison itself to be sound -- forming vs confirmed is measured
on the SAME instruments, so composition cancels in the pairing -- but a wildly different
mix would change what the average means.

Crypto is deliberately absent. BTCUSD's shift-null diverged in 8.36a because a
$0.05-to-$100k history puts displaced offsets in a different price regime entirely, and
nothing here should carry that defect.
"""
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from hvf_v2_fetch_universe import OUT, UNIVERSE, fetch  # noqa: E402

FRESH = {
    # -- FX, majors-of-majors avoided; these are all crosses the repo has never held
    "EURJPY": "EURJPY=X", "EURAUD": "EURAUD=X", "EURCAD": "EURCAD=X",
    "EURNZD": "EURNZD=X", "EURSEK": "EURSEK=X", "EURNOK": "EURNOK=X",
    "EURPLN": "EURPLN=X", "EURHUF": "EURHUF=X", "EURTRY": "EURTRY=X",
    "EURZAR": "EURZAR=X", "GBPJPY": "GBPJPY=X", "GBPSEK": "GBPSEK=X",
    "GBPNOK": "GBPNOK=X", "GBPPLN": "GBPPLN=X", "GBPZAR": "GBPZAR=X",
    "CHFJPY": "CHFJPY=X", "CADJPY": "CADJPY=X", "NZDJPY": "NZDJPY=X",
    "SGDJPY": "SGDJPY=X", "NZDCAD": "NZDCAD=X", "NZDCHF": "NZDCHF=X",
    "AUDCAD": "AUDCAD=X", "AUDCHF": "AUDCHF=X", "AUDNZD": "AUDNZD=X",
    "AUDSGD": "AUDSGD=X", "CADCHF": "CADCHF=X", "USDSGD": "USDSGD=X",
    "USDTHB": "USDTHB=X", "USDPLN": "USDPLN=X", "USDHUF": "USDHUF=X",
    "USDCZK": "USDCZK=X", "USDILS": "USDILS=X", "USDPHP": "USDPHP=X",
    "USDCLP": "USDCLP=X", "USDDKK": "USDDKK=X",
    # -- Commodities
    "HEATOIL": "HO=F", "GASOLINE": "RB=F", "OATS": "ZO=F", "SOYOIL": "ZL=F",
    "SOYMEAL": "ZM=F", "LEANHOGS": "HE=F", "COCOA": "CC=F", "ORANGEJUICE": "OJ=F",
    "ROUGHRICE": "ZR=F", "FEEDER": "GF=F", "ALUMINIUM": "ALI=F",
    # -- Equity indices, deliberately spread beyond the G7
    "IBEX": "^IBEX", "AEX": "^AEX", "BEL20": "^BFX", "OMXS30": "^OMX",
    "ATX": "^ATX", "MERVAL": "^MERV", "IPC": "^MXX", "JKSE": "^JKSE",
    "STI": "^STI", "TWII": "^TWII", "KLSE": "^KLSE", "NZ50": "^NZ50",
    "NIFTY": "^NSEI", "SSEC": "000001.SS", "MIB": "FTSEMIB.MI",
    "PSI20": "^PSI20", "TA125": "^TA125.TA",
    # -- Sector and regional ETFs (the class ran negative pre-cost in 8.37; kept
    #    proportionate rather than dropped, so the mix still resembles the original)
    "XLE_ETF": "XLE", "XLF_ETF": "XLF", "XLK_ETF": "XLK", "XLV_ETF": "XLV",
    "XLU_ETF": "XLU", "GDX_ETF": "GDX", "SLV_ETF": "SLV", "USO_ETF": "USO",
    "EEM_ETF": "EEM", "EFA_ETF": "EFA",
}

_overlap = set(FRESH) & set(UNIVERSE)
_shared = set(FRESH.values()) & set(UNIVERSE.values())
assert not _overlap, f"name collision with the spent universe: {sorted(_overlap)}"
assert not _shared, f"symbol collision with the spent universe: {sorted(_shared)}"


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    ok, bad = [], []
    for i, (name, sym) in enumerate(sorted(FRESH.items()), 1):
        path = OUT / f"{name}_D1.csv"
        if path.exists():
            ok.append(name)
            print(f"[{i:>3}/{len(FRESH)}] {name:<14} cached", flush=True)
            continue
        try:
            df = fetch(sym)
            if len(df) < 600:
                raise ValueError(f"only {len(df)} bars")
            df.to_csv(path, index=False)
            ok.append(name)
            print(f"[{i:>3}/{len(FRESH)}] {name:<14} {sym:<14} {len(df):>7,} bars",
                  flush=True)
        except Exception as e:                                  # noqa: BLE001
            bad.append((name, sym, str(e)[:70]))
            print(f"[{i:>3}/{len(FRESH)}] {name:<14} {sym:<14} FAILED  {e}",
                  flush=True)
        time.sleep(0.4)

    print(f"\nfetched {len(ok)} / {len(FRESH)}")
    if bad:
        print("failures:")
        for n, s, e in bad:
            print(f"  {n:<14} {s:<14} {e}")
    return 0 if len(ok) >= 50 else 1


if __name__ == "__main__":
    sys.exit(main())
