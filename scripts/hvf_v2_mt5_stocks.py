"""The 8.46 confirmatory run: pre-registered, one look, on fresh instruments.

READ docs/research/HVF_V2_SPEC.md 8.46 FIRST. The design, the primary statistic and the
GO / PARTIAL / NO GO rule were written and committed (558ff30) BEFORE the data was pulled
and before any return here was computed. Nothing in this file may be tuned against its own
output; if something has to change, the pre-registration is void and a new one is required.

Why single-stock CFDs. 8.44's NO GO was reached honestly but rested on a financing model
that 8.45 showed was wrong in two ways at once (magnitude, and the fact that swap is
direction-dependent). That suspends the verdict rather than reversing it, and the only
thing that resolves it is one clean test. "Clean" needs instruments that took no part in
forming any hypothesis, and the three earlier universes between them used 211 names
covering essentially every liquid macro FX pair, index, commodity and ETF. The broker
survey found 7,277 stock CFDs against 60 forex and 26 indices, and NYSE/Nasdaq/EU/UK names
carry 1,600-2,400 D1 bars. They are the only genuinely untouched deep-history instruments
available.

Two limits of that choice, both recorded in the pre-registration rather than discovered
afterwards: Hunt trades macro, not single names, so this tests whether the geometry is a
general property of price series rather than his practice specifically; and stock CFD carry
is HARSHER than gold or GBPJPY on both sides, so a negative net confounds geometry with
financing. The gross / LIFT split is pre-specified precisely to separate those two, and the
PARTIAL branch exists so that a bad net cannot be waved away after the fact with an excuse
invented to fit it.

Config is frozen and identical to 8.45: forming arm, RL2 stop, the 8.42 shape gate at its
calibrated bounds, Hunt's exit, causal 500-bar trend, signed per-symbol carry and live
spread from `symbol_info`. H24 is primary; H48 is a robustness check and NOT a second shot.
"""
import contextlib
import io
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

with contextlib.redirect_stdout(io.StringIO()):
    from hvf_v2_forming import HI, LO, NSEED
    from hvf_v2_shape import shape_gate
    from hvf_v2_widestop import picks_for, simulate

DATA = ROOT / "backtests" / "data" / "mt5" / "stocks"
TERMS = DATA / "stock_terms.json"

TREND_LOOKBACK = 500
MIN_TRADES = 25          # per instrument, pre-registered
MIN_BARS = 600
PRIMARY, ROBUST = 24, 48

def _prior_symbols():
    """Every symbol used to form a hypothesis in 8.14-8.45, read from the fetchers.

    Derived rather than transcribed: a hand-copied list would make the disjointness
    assertion below decorative, which is the one thing this test cannot afford. Yahoo
    decorations are stripped so bare tickers compare against MT5 names like `KHC.NAS`.
    """
    with contextlib.redirect_stdout(io.StringIO()):
        from hvf_v2_fetch_fresh import FRESH
        from hvf_v2_fetch_third import THIRD
        from hvf_v2_fetch_universe import UNIVERSE
    out = set()
    for d in (UNIVERSE, FRESH, THIRD):
        for v in d.values():
            s = v[0] if isinstance(v, tuple) else v
            out.add(s.lstrip("^").split("=")[0].split(".")[0])
    return out


USED = _prior_symbols()   # 211 names, all macro or ETF -- no single stock among them


# ---------------------------------------------------------------- broker terms


def load_terms():
    """Load broker terms, dropping anything that is not fresh.

    The pre-registration assumed disjointness held by construction because no prior
    universe contained a single stock. That was wrong in one direction: IC files a handful
    of ETFs under "Stock CFD's", and EMB, EWZ and GDX are all in the earlier 211. They are
    removed on the name, before any return is computed -- enforcing the freshness rule,
    not selecting on outcome.
    """
    terms = json.loads(TERMS.read_text())
    drop = {k for k, t in terms.items() if t["symbol"].split(".")[0] in USED}
    if drop:
        print(f"  dropped {len(drop)} not-fresh: "
              f"{sorted(terms[k]['symbol'] for k in drop)}")
        terms = {k: v for k, v in terms.items() if k not in drop}
    return terms


def carry_frac(t, direction):
    """Financing per night as a signed fraction of notional. Negative = a cost.

    Same three swap_mode denominations as 8.45, read per symbol rather than hardcoded:
    0/1 = points, 2 = currency per lot, 3/4 = annual percent.
    """
    raw = t["swap_long"] if direction > 0 else t["swap_short"]
    mode, price = t["swap_mode"], t["price"]
    if mode in (0, 1):
        return raw * t["point"] / price
    if mode == 2:
        return raw / (t["contract"] * price)
    return raw / 100.0 / 365.0


# ---------------------------------------------------------------- data


def load(key):
    df = (pd.read_csv(DATA / f"{key}_D1_mt5.csv")
            .sort_values("time").reset_index(drop=True))
    px = df[["open", "high", "low", "close"]]
    bad = (px <= 0).any(axis=1) | px.isna().any(axis=1)
    if bad.any():
        df = df.loc[~bad].reset_index(drop=True)
    df["dt"] = pd.to_datetime(df["time"], unit="s", utc=True)
    return df


def resample(df, hours):
    out = (df.set_index("dt")
             .resample(pd.Timedelta(hours=hours), origin="epoch")
             .agg({"open": "first", "high": "max", "low": "min", "close": "last",
                   "tick_volume": "sum"}))
    return out.dropna(subset=["open", "high", "low", "close"]).reset_index()


def causal_direction(frame):
    """Trend over the TREND_LOOKBACK bars ending at each bar. No lookahead."""
    c = frame["close"].to_numpy(float)
    prior = np.concatenate([np.full(TREND_LOOKBACK, c[0]), c[:-TREND_LOOKBACK]])
    d = np.where(c > prior, 1, -1)
    d[:TREND_LOOKBACK] = 0
    return d


# ---------------------------------------------------------------- backtest


def gated_picks(frame, dirs):
    out = []
    for d in (1, -1):
        for p in picks_for(frame, d, "forming", "rl2", shape_gate):
            if dirs[p["arm"]] == d:
                out.append(p)
    return sorted(out, key=lambda x: x["arm"])


def net_r(frame, det, t, hours):
    cl = frame["close"].to_numpy(float)
    rows = []
    for banked, carry, lev, arm, d in det:
        fin = carry * carry_frac(t, d)
        sprd = (t["spread"] * t["point"]) / (abs(cl[arm]) / lev)
        rows.append((banked, fin, sprd, banked + fin - sprd, lev, carry / lev, arm, d))
    return pd.DataFrame(rows, columns=["gross", "fin", "spread", "net",
                                       "lev", "days", "arm", "d"])


def shift_null(frame, picks, t, hours, seed=20260806):
    rng = np.random.default_rng(seed)
    n, means = len(frame), []
    for _ in range(NSEED):
        sh = []
        for p in picks:
            q = dict(p)
            step = rng.integers(LO, HI) * (1 if rng.random() < 0.5 else -1)
            q["arm"] = int(np.clip(p["arm"] + step, 0, n - 2))
            sh.append(q)
        det = simulate(frame, sorted(sh, key=lambda x: x["arm"]), "hunt")
        if len(det) >= 10:
            means.append(float(net_r(frame, det, t, hours)["net"].mean()))
    return float(np.mean(means)) if means else np.nan


def run(key, t, hours):
    df = load(key)
    frame = resample(df, hours)
    if len(frame) < MIN_BARS:
        return None
    dirs = causal_direction(frame)
    picks = gated_picks(frame, dirs)
    if not picks:
        return None
    det = simulate(frame, picks, "hunt")
    if len(det) < MIN_TRADES:
        return None
    tr = net_r(frame, det, t, hours)
    tr["year"] = frame["dt"].iloc[tr["arm"].to_numpy()].dt.year.to_numpy()
    return dict(key=key, sym=t["symbol"], ex=t["exchange"], hours=hours,
                trades=tr, null=shift_null(frame, picks, t, hours))


# ---------------------------------------------------------------- statistics


def design_effect(per_year):
    """N_eff = n / (1 + (n-1) * rho_bar), rho_bar measured from annual net-R series.

    Single stocks co-move hard, so treating instruments as independent would inflate t by
    roughly sqrt(n/N_eff). Pairs need >= 4 overlapping years to contribute a correlation.
    """
    cols = list(per_year)
    rs = []
    for i in range(len(cols)):
        for j in range(i + 1, len(cols)):
            a, b = per_year[cols[i]], per_year[cols[j]]
            common = sorted(set(a) & set(b))
            if len(common) < 4:
                continue
            x = np.array([a[y] for y in common])
            y_ = np.array([b[y] for y in common])
            if x.std() == 0 or y_.std() == 0:
                continue
            rs.append(float(np.corrcoef(x, y_)[0, 1]))
    if not rs:
        return len(cols), 0.0, 0
    rho = float(np.mean(rs))
    n = len(cols)
    neff = n / (1.0 + (n - 1) * max(rho, 0.0))
    return neff, rho, len(rs)


def summarise(res, label):
    means = np.array([r["trades"]["net"].mean() for r in res])
    gross = np.array([r["trades"]["gross"].mean() for r in res])
    nulls = np.array([r["null"] for r in res])
    lifts = means - nulls
    per_year = {r["key"]: r["trades"].groupby("year")["net"].mean().to_dict() for r in res}
    neff, rho, npairs = design_effect(per_year)

    def tstat(x):
        x = x[np.isfinite(x)]
        return float(x.mean() / (x.std(ddof=1) / np.sqrt(neff))) if x.std(ddof=1) else 0.0

    n_tr = sum(len(r["trades"]) for r in res)
    pos = float((means > 0).mean())
    # Hold is reported as a median to match 8.45's table; the mean is 5-6x larger because
    # TP3 runners have no time stop, and it is the mean that drives the financing bill.
    hold_med = np.mean([r["trades"]["days"].median() for r in res])
    hold_mean = np.mean([r["trades"]["days"].mean() for r in res])
    print(f"\n{label}")
    print(f"  instruments {len(res)}   trades {n_tr}   "
          f"hold {hold_med:.0f}d median / {hold_mean:.0f}d mean   "
          f"lev {np.mean([r['trades']['lev'].mean() for r in res]):.0f}x")
    print(f"  rho_bar {rho:+.3f} over {npairs} pairs  ->  N_eff {neff:.1f} of {len(res)}")
    print(f"  gross {gross.mean():+.4f}R   net {means.mean():+.4f}R   "
          f"t {tstat(means):+.2f}   instruments net-positive {pos:.0%}")
    print(f"  null  {np.nanmean(nulls):+.4f}R   LIFT {np.nanmean(lifts):+.4f}R   "
          f"t {tstat(lifts):+.2f}")
    return dict(n=len(res), trades=n_tr, gross=float(gross.mean()),
                net=float(means.mean()), t_net=tstat(means), pos=pos,
                lift=float(np.nanmean(lifts)), t_lift=tstat(lifts),
                neff=neff, rho=rho)


MIN_NEFF = 8   # below this the run cannot resolve anything -- see spec 8.46.1(b)


def verdict(pri, rob):
    """The pre-registered rule, applied verbatim. See spec 8.46 and 8.46.1."""
    print("\n" + "=" * 78)
    if pri["neff"] < MIN_NEFF:
        # Distinguish the two ways power can fail. 8.46.1(b) anticipated co-movement; the
        # run actually failed the other way, on instrument count, and saying so matters.
        if pri["n"] < MIN_NEFF:
            print(f"  Only {pri['n']} instruments cleared MIN_TRADES={MIN_TRADES}, so N_eff "
                  f"{pri['neff']:.1f} < {MIN_NEFF}")
            print(f"  is a shortage of INSTRUMENTS, not co-movement (rho_bar "
                  f"{pri['rho']:+.3f}).")
        else:
            print(f"  N_eff {pri['neff']:.1f} < {MIN_NEFF} from rho_bar {pri['rho']:+.3f}: "
                  f"this universe co-moves")
            print("  too hard to resolve an effect of this size either way.")
        print("\n  VERDICT: UNDERPOWERED -- no conclusion. 8.44 stays suspended.")
        print("=" * 78)
        return "UNDERPOWERED"
    go = pri["net"] > 0 and pri["t_net"] >= 2 and rob["net"] > 0 and pri["pos"] >= 0.55
    partial = (not go) and pri["lift"] > 0 and pri["t_lift"] >= 2
    print(f"  H24 net {pri['net']:+.4f} (>0? {pri['net'] > 0})   "
          f"t {pri['t_net']:+.2f} (>=2? {pri['t_net'] >= 2})")
    print(f"  H48 net {rob['net']:+.4f} (>0? {rob['net'] > 0})   "
          f"instruments positive {pri['pos']:.0%} (>=55%? {pri['pos'] >= 0.55})")
    print(f"  LIFT {pri['lift']:+.4f}  t {pri['t_lift']:+.2f}")
    name = "GO" if go else ("PARTIAL" if partial else "NO GO")
    print(f"\n  VERDICT: {name}")
    if name == "PARTIAL":
        print("  PARTIAL IS NOT A GO. It licenses one further pre-registered test on")
        print("  cheap-to-carry instruments, and nothing else. No capital.")
    print("=" * 78)
    return name


def main():
    terms = load_terms()
    print(f"universe: {len(terms)} fresh single-stock CFDs, disjoint from all prior work")
    out = {}
    for hours, label in ((PRIMARY, "PRIMARY"), (ROBUST, "ROBUSTNESS")):
        res = []
        for key, t in sorted(terms.items()):
            r = run(key, t, hours)
            if r:
                res.append(r)
        out[hours] = summarise(res, f"H{hours}  [{label}]")
    verdict(out[PRIMARY], out[ROBUST])


if __name__ == "__main__":
    main()
