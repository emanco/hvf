"""Can the box size be chosen WITHOUT seeing the setup?

This is the gap between the acceptance result (spec 8.6-8.7) and a deployable
strategy. Every number so far is conditional on the box that reproduces Hunt's
own funnel, which was found by sweeping against a known answer. Live, there is
no answer to sweep against.

Spec 4.4 says the box cannot be a global constant -- gold needs ~0.62% at 2h,
USDJPY ~0.47% at 4h, HYG ~0.71% at 4h. The obvious candidate rule is that the
box tracks the instrument's own volatility at the chart timeframe, so that
box = k * vol for one k across all instruments.

Test that directly: compute several volatility measures at the chart timeframe
over a lookback ENDING BEFORE the funnel starts (so the rule uses only
information available at the time), and report box / vol. If the ratios cluster
across the three charts, there is a rule; if they scatter, there is not.

n = 3. This can support a clean negative or a suggestive positive, nothing
stronger, and there is no held-out chart left to check a positive against.
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from hvf_trader.detector.hvf_v2 import (  # noqa: E402
    _atr, detect_hvf, load_ohlc, resample_ohlc, prior_trend_extreme_of_m,
)
from hvf_v2_charts import CHARTS, reference_prices  # noqa: E402

DATA = ROOT / "backtests" / "data" / "hvf_v2"
BAR = "=" * 92

# box, resample anchor, and the bar index where Hunt's funnel begins (H1).
REPRODUCING = {
    "GoldCFD 2h": (0.6153, 0, pd.Timestamp("2026-06-15", tz="UTC")),
    "USDJPY 4h": (0.4652, 1, pd.Timestamp("2026-07-01", tz="UTC")),
    "HYG 4h": (0.7076, 0, pd.Timestamp("2026-03-27", tz="UTC")),
}
LOOKBACK = 100          # bars of the chart's own timeframe, ending at H1


def measures(win: pd.DataFrame) -> dict[str, float]:
    """Volatility of a window, as a percentage of price, several ways."""
    close = win["close"].to_numpy()
    rng = (win["high"].to_numpy() - win["low"].to_numpy()) / close * 100
    ret = np.diff(np.log(close)) * 100
    atr = _atr(win, 14).to_numpy()[-1] / close[-1] * 100
    return {
        "median bar range%": float(np.median(rng)),
        "mean bar range%": float(np.mean(rng)),
        "ATR14%": float(atr),
        "stdev log-ret%": float(np.std(ret, ddof=1)),
    }


print(BAR)
print(f"BOX RULE -- is box = k * volatility, for one k?   (lookback {LOOKBACK} "
      f"bars ending at H1)")
print(BAR)

rows = {}
for c in CHARTS:
    if c["name"] not in REPRODUCING:
        continue
    box, off, h1_ts = REPRODUCING[c["name"]]
    src = load_ohlc(str(DATA / f"{c['src']}.csv"))
    frame = resample_ohlc(src, c["hours"], off)
    end = int((frame["dt"] <= h1_ts).sum())
    win = frame.iloc[max(0, end - LOOKBACK):end]
    rows[c["name"]] = (box, measures(win))

keys = list(next(iter(rows.values()))[1])
print(f"{'chart':<12}{'box%':>7}" + "".join(f"{k:>20}" for k in keys))
print("-" * 92)
for name, (box, m) in rows.items():
    print(f"{name:<12}{box:>7.4f}" + "".join(f"{m[k]:>20.4f}" for k in keys))

print(f"\n{'ratio box/vol':<12}{'':>7}" + "".join(f"{k:>20}" for k in keys))
print("-" * 92)
ratios = {k: [] for k in keys}
for name, (box, m) in rows.items():
    print(f"{name:<12}{'':>7}" + "".join(f"{box / m[k]:>20.3f}" for k in keys))
    for k in keys:
        ratios[k].append(box / m[k])

print(f"\n{'spread (max/min)':<19}" + "".join(
    f"{max(v) / min(v):>20.2f}" for v in ratios.values()))
print("\nA usable rule needs spread near 1.0. Above ~1.5 the rule would put the")
print("box outside the admissible band, which spec 4.1 measured at 0.60-0.74%")
print("for gold -- roughly +/-10% around its centre.")

# If the tightest measure were used as the rule, would the resulting box still
# reproduce Hunt's funnel? That is the only test that matters.
best = min(ratios, key=lambda k: max(ratios[k]) / min(ratios[k]))
k_hat = float(np.median(ratios[best]))
print(f"\n{BAR}\nAPPLYING THE BEST RULE: box = {k_hat:.3f} x {best}")
print(BAR)
GATE = prior_trend_extreme_of_m(50)
print(f"{'chart':<12}{'true box%':>11}{'rule box%':>11}{'err':>8}"
      f"{'reproduces?':>13}{'emissions/mo':>14}")
print("-" * 92)
for c in CHARTS:
    if c["name"] not in REPRODUCING:
        continue
    box, off, h1_ts = REPRODUCING[c["name"]]
    _, ref, _, ra, rb = reference_prices(c)
    src = load_ohlc(str(DATA / f"{c['src']}.csv"))
    frame = resample_ohlc(src, c["hours"], off)
    rule_box = round(k_hat * rows[c["name"]][1][best], 4)
    found, _ = detect_hvf(frame, bar_hours=c["hours"], box_pct=rule_box,
                          prior_trend=GATE)
    live = [f for f in found if f.end_ts >= pd.Timestamp("2026-01-01", tz="UTC")]
    hit = any(abs(f.b - rb) / rb < 5e-4 and abs(f.a - ra) / ra < 5e-4 for f in live)
    span = frame[frame["dt"] >= pd.Timestamp("2026-01-01", tz="UTC")]["dt"]
    mo = (span.iloc[-1] - span.iloc[0]).days / 30.44
    print(f"{c['name']:<12}{box:>11.4f}{rule_box:>11.4f}"
          f"{100 * (rule_box - box) / box:>7.0f}%{('YES' if hit else 'no'):>13}"
          f"{len(live) / mo:>14.1f}")
print(BAR)
