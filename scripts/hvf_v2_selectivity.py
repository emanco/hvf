"""How many funnels does the detector emit, against how many Hunt drew?

Acceptance (spec 8.6) measures RECALL: can we reproduce a setup Hunt posted?
Nothing measured PRECISION, and precision is what decides whether this is a
strategy. A detector that finds Hunt's funnel *and eighty others* is not a
detector, it is a haystack -- and Stage B already hints at that, with gold
emitting 8-81 admissible patterns depending on the prior-trend variant while
HYG emits exactly 1 under all six.

The benchmark is sharp and needs no new data. Hunt's charts are epoch-ms
timestamped 2026-03-12..2026-07-31 and there is ONE setup per instrument /
timeframe pair. So over the 2026 span, per chart, the target emission count is
of order 1. Report emissions per chart and per month, at the box size that
reproduces Hunt's own setup (spec 8.6) -- i.e. under conditions maximally
favourable to the detector.

Run over the three charts that reproduce. The other five are excluded for
stated reasons, not for convenience: three have no 2026 price chain in our feed
at all, and two are the held-out pair, whose reproducing box is unknown because
neither reproduces.
"""
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from hvf_trader.detector.hvf_v2 import (  # noqa: E402
    detect_hvf, load_ohlc, ratio_series, resample_ohlc,
    prior_trend_extreme_of_m, prior_trend_atr_span, prior_trend_slope,
)
from hvf_v2_charts import CHARTS, reference_prices  # noqa: E402

DATA = ROOT / "backtests" / "data" / "hvf_v2"
LIVE_FROM = pd.Timestamp("2026-01-01", tz="UTC")
BAR = "=" * 100

# Box and resample anchor that reproduce Hunt's setup, from spec 8.6.
REPRODUCING = {
    "GoldCFD 2h": (0.6153, 0),
    "USDJPY 4h": (0.4652, 1),
    "HYG 4h": (0.7076, 0),
}

TESTS = {
    # Ceiling case: no prior-trend gate at all. Separates "the geometry is
    # selective" from "the prior-trend gate is doing all the work", and bounds
    # recall -- a true funnel missed here is missed for a geometric reason.
    "none (geometry only)": lambda df, idx, direction: True,
    "extreme_of_m(100)": prior_trend_extreme_of_m(100),
    "extreme_of_m(50)": prior_trend_extreme_of_m(50),
    "atr_span(k=4,n=100)": prior_trend_atr_span(4.0, 100),
    "atr_span(k=3,n=50)": prior_trend_atr_span(3.0, 50),
    "slope(n=100,r2=0.5)": prior_trend_slope(100, 0.5),
    "slope(n=50,r2=0.3)": prior_trend_slope(50, 0.3),
}

# Bounded below by Hunt himself: the gold setup he posted carries RRR 1.47, so
# a 2.0 floor would reject one of his own three. Not a tuned value -- an
# observed one.
MIN_RRR = 1.4

print(BAR)
print("SELECTIVITY -- emissions per chart over 2026, at the reproducing box")
print("benchmark: Hunt posted 1 setup per instrument/timeframe in ~4.6 months")
print("'true?' columns: was Hunt's own funnel among the emissions, with dedupe")
print("off (spec 4.3 step 3) and on. They differ, and that is the headline.")
print(BAR)
print(f"{'chart':<12}{'prior-trend test':<21}{'raw':>5}{'/mo':>6}{'true':>6}"
      f"{'  |':>3}{'dedup':>7}{'/mo':>6}{'true':>6}{f'  RRR>={MIN_RRR}':>11}"
      f"   top rejections")
print("-" * 100)

for c in CHARTS:
    if c["name"] not in REPRODUCING:
        continue
    box, off = REPRODUCING[c["name"]]
    names, ref, kinds, ref_a, ref_b = reference_prices(c)
    src = load_ohlc(str(DATA / f"{c['src']}.csv"))
    if c["ratio"]:
        src = ratio_series(src, load_ohlc(str(DATA / f"{c['ratio']}.csv")))
    frame = src if off is None else resample_ohlc(src, c["hours"], off)

    span = frame[frame["dt"] >= LIVE_FROM]
    months = (span["dt"].iloc[-1] - span["dt"].iloc[0]).days / 30.44

    def run(test, dedupe):
        found, rej = detect_hvf(frame, bar_hours=c["hours"], box_pct=box,
                                prior_trend=test, dedupe=dedupe)
        live = [f for f in found if f.end_ts >= LIVE_FROM]
        # Did the emitted set include the funnel Hunt actually drew? Match on
        # the reference anchor prices, which are solved from the panel.
        hit = any(abs(f.b - ref_b) / ref_b < 5e-4 and abs(f.a - ref_a) / ref_a < 5e-4
                  for f in live)
        return live, hit, rej

    for label, test in TESTS.items():
        raw, raw_hit, rej = run(test, False)
        ded, ded_hit, _ = run(test, True)
        tradeable = [f for f in raw if f.rrr >= MIN_RRR]
        top = sorted(((v, k) for k, v in rej.as_dict().items()
                      if v and k not in ("candidates", "admitted", "deduped")),
                     reverse=True)[:2]
        print(f"{c['name']:<12}{label:<21}{len(raw):>5}{len(raw) / months:>6.1f}"
              f"{('YES' if raw_hit else 'no'):>6}{'  |':>3}"
              f"{len(ded):>7}{len(ded) / months:>6.1f}"
              f"{('YES' if ded_hit else 'no'):>6}{len(tradeable):>11}   "
              + ", ".join(f"{k}={v}" for v, k in top))
    print(f"{'':12}({months:.1f} months of 2026 data, box {box}%, anchor {off})")
    print()

print(BAR)
print("Read this as: emissions/month is the number of setups a trader would be")
print("shown. Hunt showed ~1 per pair over the whole 4.6-month window.")
print(BAR)
