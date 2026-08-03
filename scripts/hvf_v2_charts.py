"""Hunt's charted setups, and the reference prices solved from them.

Shared by `hvf_v2_acceptance.py` and the diagnostics, so the panel transcription
and the anchor solve exist once. Only the charts whose instrument IC Markets
actually carries are listed; the five unreachable ones (four bond yields, two
USDKRW periods) are recorded in spec 8.2, not here.

Reference prices are *solved*, never pixel-read: entry sits at RH3 and stop at
RL3 (mirrored for shorts), so the price distance between them over the fib
distance recovers the range, and every pivot price follows from its fib.
"""

# name, source file, ratio denominator, chart period, direction, fib coords, entry, stop
CHARTS = [
    dict(name="GoldCFD 2h", src="XAUUSD_H1", ratio=None, hours=2, dir=+1,
         rh2=0.78, rl2=0.12, rh3=0.69, rl3=0.19, entry=4349.762, stop=4317.250),
    dict(name="BTCUSD 1h", src="BTCUSD_H1", ratio=None, hours=1, dir=+1,
         rh2=0.84, rl2=0.08, rh3=0.65, rl3=0.14, entry=70805.0, stop=69376.0),
    dict(name="XAU/XAG 8h", src="XAUUSD_H1", ratio="XAGUSD_H1", hours=8, dir=+1,
         rh2=0.77, rl2=0.18, rh3=0.47, rl3=0.28, entry=63.759, stop=60.543),
    dict(name="USDJPY 4h", src="USDJPY_H1", ratio=None, hours=4, dir=+1,
         rh2=0.94, rl2=0.34, rh3=0.85, rl3=0.47, entry=162.482, stop=161.599),
    dict(name="USDJPY 1W", src="USDJPY_W1", ratio=None, hours=168, dir=+1,
         rh2=0.86, rl2=0.01, rh3=0.51, rl3=0.26, entry=150.918, stop=145.638),
    dict(name="WTI 18h", src="XTIUSD_H1", ratio=None, hours=18, dir=-1,
         rh2=0.84, rl2=0.05, rh3=0.70, rl3=0.29, entry=88.66, stop=105.21),
    dict(name="XAUEUR 1h", src="XAUEUR_H1", ratio=None, hours=1, dir=-1,
         rh2=0.82, rl2=0.09, rh3=0.63, rl3=0.12, entry=3990.733, stop=4032.228),
    dict(name="HYG 4h", src="HYG_NYSE_H1", ratio=None, hours=4, dir=-1,
         rh2=0.82, rl2=0.30, rh3=0.73, rl3=0.36, entry=79.36, stop=80.16),
]


def reference_prices(c):
    """Solve (a, b) from entry/stop, then price every pivot from its fib."""
    span = abs(c["entry"] - c["stop"]) / (c["rh3"] - c["rl3"])
    a = (c["stop"] - c["rl3"] * span) if c["dir"] > 0 else (c["entry"] - c["rl3"] * span)
    b = a + span
    def px(f):
        return a + f * span
    if c["dir"] > 0:
        names = ["H1", "RL1", "RH2", "RL2", "RH3", "RL3"]
        vals = [b, a, px(c["rh2"]), px(c["rl2"]), px(c["rh3"]), px(c["rl3"])]
        kinds = "HLHLHL"
    else:
        names = ["L1", "RH1", "RL2", "RH2", "RL3", "RH3"]
        vals = [a, b, px(c["rl2"]), px(c["rh2"]), px(c["rl3"]), px(c["rh3"])]
        kinds = "LHLHLH"
    return names, vals, kinds, a, b
