"""A THIRD instrument universe, for the 8.42 shape gate.

The fresh 72 has now taken two draws -- 8.40 (forming arm) and 8.41 (stop width) -- and
the original 56 took three before that. The shape gate is a larger change than either, so
it gets clean data rather than a third draw.

Disjointness from BOTH prior universes is asserted at import, not checked by eye.

Class is declared per name rather than inferred. `hvf_v2_forming.klass` guesses from the
string -- "etf" if the name ends _ETF, "fx" if six upper-case letters, "commodity" if in a
hand-kept set, else "index" -- and that silently mislabels GOLD, SILVER and the bond
futures as indices, which would charge them the wrong financing rate. The costs are the
whole argument at this point, so they are stated explicitly.

The majors (EURUSD, GBPUSD, USDJPY, USDCHF, EURGBP) appear here for the first time: the
original universe skipped them and `FRESH` deliberately avoided "majors-of-majors". Gold,
silver and WTI likewise -- these are Hunt's own instruments and it is worth having them
in a test set rather than only in his screenshots.
"""
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from hvf_v2_fetch_fresh import FRESH                    # noqa: E402
from hvf_v2_fetch_universe import OUT, UNIVERSE, fetch  # noqa: E402

# name -> (yahoo symbol, cost class)
THIRD = {
    # -- FX: the majors, plus crosses untouched by either prior universe
    "EURUSD": ("EURUSD=X", "fx"), "GBPUSD": ("GBPUSD=X", "fx"),
    "USDJPY": ("USDJPY=X", "fx"), "USDCHF": ("USDCHF=X", "fx"),
    "EURGBP": ("EURGBP=X", "fx"), "NZDUSD": ("NZDUSD=X", "fx"),
    "USDCNY": ("USDCNY=X", "fx"), "USDHKD": ("USDHKD=X", "fx"),
    "USDIDR": ("USDIDR=X", "fx"), "USDMYR": ("USDMYR=X", "fx"),
    "USDTWD": ("USDTWD=X", "fx"), "USDBRL": ("USDBRL=X", "fx"),
    "USDRON": ("USDRON=X", "fx"), "USDISK": ("USDISK=X", "fx"),
    "USDSAR": ("USDSAR=X", "fx"), "USDAED": ("USDAED=X", "fx"),
    "USDPKR": ("USDPKR=X", "fx"), "USDKZT": ("USDKZT=X", "fx"),
    "USDUAH": ("USDUAH=X", "fx"), "USDKES": ("USDKES=X", "fx"),
    "CHFNOK": ("CHFNOK=X", "fx"), "CHFSEK": ("CHFSEK=X", "fx"),
    "CHFPLN": ("CHFPLN=X", "fx"), "NOKSEK": ("NOKSEK=X", "fx"),
    "NOKJPY": ("NOKJPY=X", "fx"), "SEKJPY": ("SEKJPY=X", "fx"),
    "PLNJPY": ("PLNJPY=X", "fx"), "TRYJPY": ("TRYJPY=X", "fx"),
    "ZARJPY": ("ZARJPY=X", "fx"), "MXNJPY": ("MXNJPY=X", "fx"),
    "EURMXN": ("EURMXN=X", "fx"), "EURILS": ("EURILS=X", "fx"),
    "EURSGD": ("EURSGD=X", "fx"), "EURKRW": ("EURKRW=X", "fx"),
    "EURINR": ("EURINR=X", "fx"), "GBPSGD": ("GBPSGD=X", "fx"),
    "GBPHUF": ("GBPHUF=X", "fx"), "GBPCZK": ("GBPCZK=X", "fx"),
    "AUDPLN": ("AUDPLN=X", "fx"), "AUDNOK": ("AUDNOK=X", "fx"),
    "AUDSEK": ("AUDSEK=X", "fx"), "AUDMXN": ("AUDMXN=X", "fx"),
    "CADNOK": ("CADNOK=X", "fx"), "NZDSGD": ("NZDSGD=X", "fx"),
    # -- Commodities, including Hunt's own three
    "GOLD": ("GC=F", "commodity"), "SILVER": ("SI=F", "commodity"),
    "WTI": ("CL=F", "commodity"), "LUMBER": ("LBS=F", "commodity"),
    "KCWHEAT": ("KE=F", "commodity"), "SPRINGWHEAT": ("MW=F", "commodity"),
    # -- Bond futures: financed like an index, not like a commodity
    "TBOND": ("ZB=F", "index"), "TNOTE10": ("ZN=F", "index"),
    "TNOTE5": ("ZF=F", "index"), "TNOTE2": ("ZT=F", "index"),
    # -- Equity indices
    "STOXX50": ("^STOXX50E", "index"), "STOXX600": ("^STOXX", "index"),
    "SP400": ("^SP400", "index"), "SP600": ("^SP600", "index"),
    "NYSE": ("^NYA", "index"), "DJTRANS": ("^DJT", "index"),
    "DJUTIL": ("^DJU", "index"), "SP100": ("^OEX", "index"),
    "RUSSELL1000": ("^RUI", "index"), "XU100": ("^XU100", "index"),
    "TA35": ("^TA35.TA", "index"), "SETI": ("^SET.BK", "index"),
    "N100": ("^N100", "index"),
    # -- ETFs
    "SPY_ETF": ("SPY", "etf"), "QQQ_ETF": ("QQQ", "etf"),
    "IWM_ETF": ("IWM", "etf"), "DIA_ETF": ("DIA", "etf"),
    "GLD_ETF": ("GLD", "etf"), "XLI_ETF": ("XLI", "etf"),
    "XLP_ETF": ("XLP", "etf"), "XLY_ETF": ("XLY", "etf"),
    "XLB_ETF": ("XLB", "etf"), "SMH_ETF": ("SMH", "etf"),
    "EWJ_ETF": ("EWJ", "etf"), "EWZ_ETF": ("EWZ", "etf"),
    "EWG_ETF": ("EWG", "etf"), "EWU_ETF": ("EWU", "etf"),
    "FXI_ETF": ("FXI", "etf"),
}

CLASS = {k: v[1] for k, v in THIRD.items()}

_prior_names = set(UNIVERSE) | set(FRESH)
_prior_syms = set(UNIVERSE.values()) | set(FRESH.values())
_n = set(THIRD) & _prior_names
_s = {v[0] for v in THIRD.values()} & _prior_syms
assert not _n, f"name collision with a spent universe: {sorted(_n)}"
assert not _s, f"symbol collision with a spent universe: {sorted(_s)}"


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    ok, bad = [], []
    for i, (name, (sym, _)) in enumerate(sorted(THIRD.items()), 1):
        path = OUT / f"{name}_D1.csv"
        if path.exists():
            ok.append(name)
            print(f"[{i:>3}/{len(THIRD)}] {name:<14} cached", flush=True)
            continue
        try:
            df = fetch(sym)
            if len(df) < 600:
                raise ValueError(f"only {len(df)} bars")
            df.to_csv(path, index=False)
            ok.append(name)
            print(f"[{i:>3}/{len(THIRD)}] {name:<14} {sym:<14} {len(df):>7,} bars",
                  flush=True)
        except Exception as e:                                  # noqa: BLE001
            bad.append((name, sym, str(e)[:70]))
            print(f"[{i:>3}/{len(THIRD)}] {name:<14} {sym:<14} FAILED  {e}", flush=True)
        time.sleep(0.4)

    print(f"\nfetched {len(ok)} / {len(THIRD)}")
    for n, s, e in bad:
        print(f"  {n:<14} {s:<14} {e}")
    return 0 if len(ok) >= 50 else 1


if __name__ == "__main__":
    sys.exit(main())
