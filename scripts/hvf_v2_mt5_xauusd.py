"""Backtest on live IC Markets MT5 data and exact broker terms. (8.45)

8.36-8.44 ran on Yahoo daily data with MODELLED costs. This runs the final 8.44
configuration against the broker the demo account actually trades on: bars pulled from the
IC Markets terminal on the VPS (`ssh hvf-vps`, account 52774919, ICMarketsSC-Demo), and
financing/spread read off `symbol_info` rather than assumed.

MT5 itself is Windows-only, so the Strategy Tester cannot run on this laptop. The terminal
lives on the VPS; data and instrument terms were pulled from it read-only, and the
simulation runs here against the same 8.36-8.44 harness so the numbers stay comparable to
everything already recorded.

INSTRUMENT CHOICE, stated before running. XAUUSD is picked on relevance, not performance:
Hunt's flagship underlying, liquid on IC Markets, tradable on the demo account. It is ALSO
one of the eight charts the 8.42 shape gate was calibrated on, so this is a deliberately
FAVOURABLE case and the inference is one-directional -- a good result here is not evidence,
a bad result here is strong.

THE FRAME SWEEP IS EXPLORATORY, NOT CONFIRMATORY. 8.44 closed the confirmatory programme
with a pre-registered NO GO. Six frames on one calibration-adjacent instrument is a
multiple comparison on used data and cannot reverse that verdict. It is run because 8.44
named exactly one place a real edge could still live -- "materially shorter holds", since
financing is leverage x holding time -- and H1 data is the first able to test it. Any
positive here is a hypothesis for a fresh universe, nothing more.

THREE CORRECTIONS to 8.44's cost model, all of them measurements replacing assumptions:

  1. REAL SPREAD, and it is WORSE than assumed. Live XAUUSD spread is 21 points = $0.21.
     The `spread` column inside historical bars medians 2 points, which is the field being
     unpopulated on backfill rather than a real quote, so the live figure is used
     throughout. Even at 21 points this is 0.005% of price and stays negligible in R.

  2. REAL FINANCING, and it is BETTER than assumed -- gold is -4.80%/yr long, not the
     modelled -7%. This matters: financing is the term that decided every table since 8.41.

  3. FINANCING IS DIRECTION-DEPENDENT, which the modelled version missed entirely. IC
     Markets CHARGES -4.80%/yr to hold gold long and PAYS +3.29%/yr to hold it short.
     Charging both sides symmetrically, as 8.36-8.44 did, is simply wrong.

And one correction to the signal, unchanged from the first draft of this section:
`hvf_v2_forming.direction_for` derives ONE direction per instrument from the last 500 bars
of the whole series and applies it to every trade in history, which is lookahead. Here the
trend is measured over the 500 bars ENDING AT THE SIGNAL BAR. This can only hurt, so it
does not threaten the 8.44 verdict; it is fixed because the graph is meant to be honest.

Config is otherwise exactly 8.44's: forming arm, RL2 stop, shape gate on, Hunt's exit
(half at TP2, breakeven, run TP3).
"""
import contextlib
import io
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

DATA = ROOT / "backtests" / "data" / "mt5"

# Read from symbol_info on ICMarketsSC-Demo, 2026-08-06 10:52 UTC. `swap_mode` decides
# how swap_long/swap_short are denominated, so each is converted to a plain fraction of
# notional per night by `carry_frac` below. `spread` is the live quoted spread in points.
SPEC = {
    "XAUUSD": dict(point=0.01,   contract=100,    mode="points",   spread=21,
                   swap_long=-56.01, swap_short=38.34,  price=4256.72),
    "XAGUSD": dict(point=0.001,  contract=1000,   mode="points",   spread=50,
                   swap_long=-8.32,  swap_short=5.71,   price=61.769),
    "XTIUSD": dict(point=0.01,   contract=100,    mode="points",   spread=2,
                   swap_long=1.00,   swap_short=-2.59,  price=75.590),
    "EURUSD": dict(point=1e-05,  contract=100000, mode="points",   spread=9,
                   swap_long=-8.24,  swap_short=1.51,   price=1.15414),
    "GBPJPY": dict(point=0.001,  contract=100000, mode="points",   spread=18,
                   swap_long=11.46,  swap_short=-22.95, price=212.451),
    "US500":  dict(point=0.01,   contract=1,      mode="currency", spread=50,
                   swap_long=-1.79,  swap_short=-0.08,  price=7730.0),
    "DE40":   dict(point=0.01,   contract=1,      mode="currency", spread=50,
                   swap_long=-5.00,  swap_short=-1.45,  price=26145.1),
    "BTCUSD": dict(point=0.01,   contract=1,      mode="interest", spread=1200,
                   swap_long=-20.0,  swap_short=0.0,    price=64751.86),
}

TREND_LOOKBACK = 500   # bars, matching direction_for's horizon
MIN_TRADES = 25        # below this a cell is reported but not interpreted

# (hours, use_h1_source). Sub-daily frames need H1 and pay for it with a shorter, trimmed
# history; a day or coarser reads D1, where the full history is genuine.
FRAMES = [(4, True), (8, True), (12, True), (24, False), (48, False), (72, False)]


# ---------------------------------------------------------------- broker terms


def carry_frac(sym, direction):
    """Financing per night as a signed fraction of notional. Negative = a cost.

    The three swap_mode denominations in this universe:
      points    swap is in price points per lot   -> swap*point / price
      currency  swap is in account currency/lot   -> swap / (contract*price)
      interest  swap is already an annual percent -> swap/100/365
    """
    s = SPEC[sym]
    raw = s["swap_long"] if direction > 0 else s["swap_short"]
    if s["mode"] == "points":
        return raw * s["point"] / s["price"]
    if s["mode"] == "currency":
        return raw / (s["contract"] * s["price"])
    return raw / 100.0 / 365.0


def spread_px(sym):
    return SPEC[sym]["spread"] * SPEC[sym]["point"]


# ---------------------------------------------------------------- data


def load(sym, tf, trim_to_h1=False):
    """Load an MT5 export, drop bad prints, and optionally trim to genuine H1 bars.

    Two defects, both present in this pull and both silent if ignored:

    Every H1 export is a SPLICE -- IC serves sparse pre-2016 history (daily or worse)
    from the same H1 endpoint. Resampling that into a 4h frame gives one 4h bar per
    trading DAY for the first third of the series, which is not a 4h frame at all and
    would fabricate structure. So any frame finer than a day trims to the point where
    3600s spacing becomes sustained; frames of a day or coarser read D1 instead, where
    the whole history is genuine.

    BTCUSD carries a `low = 0.0` print (IC's 2018-03-17 feed glitch, already documented
    in detector.load_ohlc). A percentage ZigZag would select it as the dominant pivot of
    the decade, so bad rows are dropped rather than tolerated.
    """
    df = pd.read_csv(DATA / f"{sym}_{tf}_mt5.csv").sort_values("time").reset_index(drop=True)
    px = df[["open", "high", "low", "close"]]
    bad = (px <= 0).any(axis=1) | px.isna().any(axis=1)
    if bad.any():
        print(f"    ! {sym} {tf}: dropped {int(bad.sum())} bad print(s)")
        df = df.loc[~bad].reset_index(drop=True)
    df["dt"] = pd.to_datetime(df["time"], unit="s", utc=True)
    if trim_to_h1:
        h1 = df["time"].diff().eq(3600)
        start = int(h1.rolling(200).sum().ge(150).idxmax())
        df = df.loc[start:].reset_index(drop=True)
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
    d[:TREND_LOOKBACK] = 0            # not enough history to call a trend
    return d


# ---------------------------------------------------------------- backtest


def gated_picks(frame, dirs):
    """Both directions, keeping each pick only if it agrees with the trend prevailing
    at ITS OWN signal bar."""
    out = []
    for d in (1, -1):
        for p in picks_for(frame, d, "forming", "rl2", shape_gate):
            if dirs[p["arm"]] == d:
                out.append(p)
    return sorted(out, key=lambda x: x["arm"])


def net_r(frame, det, sym, hours):
    """Per-trade net R: gross, minus direction-correct financing, minus one real spread."""
    cl = frame["close"].to_numpy(float)
    day = hours / 24.0
    rows = []
    for banked, carry, lev, arm, d in det:
        # simulate accumulates carry as n_bars * lev * day, so nights held = carry/lev
        # and the financing already carries the leverage factor.
        fin = carry * carry_frac(sym, d)
        # risk in price is |entry|/lev by construction, so spread in R is just the ratio
        sprd = spread_px(sym) / (abs(cl[arm]) / lev)
        rows.append((banked, fin, sprd, banked + fin - sprd, lev, carry / lev, arm, d))
    return pd.DataFrame(rows, columns=["gross", "fin", "spread", "net",
                                       "lev", "days", "arm", "d"])


def shift_null(frame, picks, sym, hours, exit_style, seed=20260806):
    """Same geometry, randomly relocated. Charged the same costs."""
    rng = np.random.default_rng(seed)
    n, means = len(frame), []
    for _ in range(NSEED):
        sh = []
        for p in picks:
            q = dict(p)
            step = rng.integers(LO, HI) * (1 if rng.random() < 0.5 else -1)
            q["arm"] = int(np.clip(p["arm"] + step, 0, n - 2))
            sh.append(q)
        det = simulate(frame, sorted(sh, key=lambda x: x["arm"]), exit_style)
        if len(det) >= 10:
            means.append(float(net_r(frame, det, sym, hours)["net"].mean()))
    return np.array(means) if means else np.array([np.nan])


def run_frame(sym, hours, h1_src, exit_style="hunt", with_null=True):
    df = load(sym, "H1", trim_to_h1=True) if h1_src else load(sym, "D1")
    frame = resample(df, hours)
    if len(frame) < 600:
        return None
    dirs = causal_direction(frame)
    picks = gated_picks(frame, dirs)
    if not picks:
        return None
    det = simulate(frame, picks, exit_style)
    if not det:
        return None
    return dict(sym=sym, hours=hours, frame=frame, dirs=dirs, picks=picks,
                t=net_r(frame, det, sym, hours),
                null=shift_null(frame, picks, sym, hours, exit_style)
                if with_null else np.array([np.nan]),
                span=(df.dt.min(), df.dt.max()),
                ungated=sum(len(picks_for(frame, d, "forming", "rl2", None))
                            for d in (1, -1)))


HDR = (f"{'frame':>7}{'bars':>7}{'setups':>8}{'trades':>8}{'lev':>6}{'hold':>7}"
       f"{'win':>6}{'gross':>9}{'fin':>8}{'sprd':>7}{'NET':>9}{'t':>7}"
       f"{'LIFT':>8}{'totR':>8}")


def row(r):
    t, u, hours = r["t"], r["null"], r["hours"]
    tstat = t.net.mean() / (t.net.std(ddof=1) / np.sqrt(len(t))) if len(t) > 1 else 0
    flag = "" if len(t) >= MIN_TRADES else "  <- thin"
    return (f"{f'H{hours}':>7}{len(r['frame']):>7}{r['ungated']:>8}{len(t):>8}"
            f"{t.lev.mean():>5.0f}x{t.days.median():>6.0f}d{(t.gross > 0).mean():>6.0%}"
            f"{t.gross.mean():>9.3f}{t.fin.mean():>8.3f}{-t.spread.mean():>7.3f}"
            f"{t.net.mean():>9.3f}{tstat:>7.2f}"
            f"{t.net.mean() - np.nanmean(u):>8.3f}{t.net.sum():>8.1f}{flag}")


def main():
    sym = "XAUUSD"
    print("=" * 104)
    print(f"8.45  {sym} -- IC Markets MT5 data + exact broker terms, 8.44 config "
          f"(EXPLORATORY sweep)")
    print("=" * 104)
    s = SPEC[sym]
    print(f"  financing  long {365 * carry_frac(sym, 1) * 100:+.2f}%/yr   "
          f"short {365 * carry_frac(sym, -1) * 100:+.2f}%/yr   "
          f"spread {s['spread']} pts = ${spread_px(sym):.2f} "
          f"({spread_px(sym) / s['price'] * 100:.4f}% of price)")
    print(HDR)
    print("-" * 104)
    out = {}
    for hours, h1_src in FRAMES:
        r = run_frame(sym, hours, h1_src)
        if r is None:
            print(f"{f'H{hours}':>7}  no usable frame")
            continue
        print(row(r))
        out[hours] = r
    print("-" * 104)
    print("  setups = ungated candidates before the shape gate and the causal trend filter")
    print("  LIFT   = net minus the shift-null (same geometry, randomly relocated)")
    print(f"  cells under {MIN_TRADES} trades are shown for completeness, not interpreted")

    print(f"\n{'=' * 104}\n  Same config, H24, across every instrument pulled from the "
          f"terminal (context only, not a universe test)\n{'=' * 104}")
    print(f"{'symbol':>8}{'carry L/S %/yr':>18}" + HDR[7:])
    print("-" * 104)
    for other in SPEC:
        r = run_frame(other, 24, False, with_null=True)
        if r is None:
            print(f"{other:>8}  no usable frame")
            continue
        c = f"{365 * carry_frac(other, 1) * 100:+.1f}/{365 * carry_frac(other, -1) * 100:+.1f}"
        print(f"{other:>8}{c:>18}" + row(r)[7:])
        out[other] = r
    return out


if __name__ == "__main__":
    main()
