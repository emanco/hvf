"""How many funnels does the MEF rule emit when it is NOT handed Hunt's range?

The acceptance search prunes on AMP_TOL, i.e. on a number read off the chart we
are trying to find. A live system has no such number, so the emission rate that
matters is the ungated one. Compared against spec 8.7's detector rates.
"""
import sys, time
sys.path.insert(0, '.'); sys.path.insert(0, 'scripts')
from hvf_trader.detector.hvf_v2 import load_ohlc, resample_ohlc, zigzag_pct
from hvf_v2_mef import mef_candidates

CASES = [("XAUUSD_H1", "GoldCFD 2h", 2, 0, +1, 1.1),
         ("USDJPY_H1", "USDJPY 4h", 4, 1, +1, 0.4),
         ("HYG_NYSE_H1", "HYG 4h", 4, 0, -1, 0.2)]
BOXES = [0.1, 0.5, 1.0, 2.0]

print(f"{'chart':<12}{'box%':>6}{'pivots':>9}{'funnels':>10}{'per month':>11}"
      f"{'v8.7':>7}{'x':>8}{'s':>7}")
print("-" * 70)
for src, label, hours, off, d, ref in CASES:
    base = load_ohlc(f"backtests/data/hvf_v2/{src}.csv")
    frame = resample_ohlc(base, hours, off)
    months = (frame["dt"].iloc[-1] - frame["dt"].iloc[0]).days / 30.44
    for box in BOXES:
        piv = zigzag_pct(frame, box)
        t0 = time.time()
        # dedupe on the last pivot: one funnel per (RH3, RL3) is the trade
        arms, n = set(), 0
        for idx in mef_candidates(piv, d):
            n += 1
            arms.add((idx[4], idx[5]))
        dt = time.time() - t0
        rate = len(arms) / months
        print(f"{label:<12}{box:>6}{len(piv):>9,}{n:>10,}{rate:>11.1f}"
              f"{ref:>7}{rate/ref:>8.0f}{dt:>7.1f}", flush=True)
