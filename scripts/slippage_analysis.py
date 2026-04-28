"""KZ_HUNT slippage analysis. Reads trade dump and computes profiles."""
import statistics
from collections import defaultdict
from datetime import datetime

PIP_VALUES = {
    "EURUSD": 0.0001, "NZDUSD": 0.0001, "EURGBP": 0.0001, "USDCHF": 0.0001,
    "EURAUD": 0.0001, "GBPJPY": 0.01, "EURJPY": 0.01, "CHFJPY": 0.01,
}

# Approximate USD per pip per 1.0 lot for quick $ impact sizing.
# Roughly 10 USD/pip for non-JPY-quoted majors, 6.7 USD/pip for JPY pairs at recent rates.
USD_PER_PIP_PER_LOT = {
    "EURUSD": 10.0, "NZDUSD": 10.0, "EURGBP": 12.5, "USDCHF": 12.5,
    "EURAUD": 10.0, "GBPJPY": 6.7, "EURJPY": 6.7, "CHFJPY": 6.7,
}

# pasted dump (id|symbol|direction|intended|actual|slippage|opened_at|lot|status|pnl_pips|pattern)
RAW = """44|EURAUD|LONG|1.67041|1.67052|0.00011|2026-03-27 09:00:13|0.04|-7.2
45|NZDUSD|LONG|0.57715|0.57737|0.00022|2026-03-27 10:06:11|0.06|-9.1
46|NZDUSD|SHORT|0.5766|0.57649|0.00011|2026-03-27 11:00:21|0.02|5.6
47|USDCHF|SHORT|0.7975|0.79606|0.00144|2026-03-27 14:00:07|0.02|-14.5
48|EURUSD|SHORT|1.15293|1.15268|0.00025|2026-03-27 15:08:27|0.01|2.2
49|EURGBP|SHORT|0.86829|0.8676|0.00069|2026-03-30 04:00:20|0.03|-9.0
50|EURUSD|LONG|1.15191|1.15204|0.00013|2026-03-30 06:45:44|0.04|-12.5
51|NZDUSD|SHORT|0.574|0.57372|0.00028|2026-03-30 07:00:48|0.03|14.4
52|EURAUD|LONG|1.67406|1.67563|0.00157|2026-03-30 11:00:49|0.01|9.5
53|USDCHF|SHORT|0.79986|0.79954|0.00032|2026-03-30 13:00:26|0.03|-12.6
54|EURUSD|SHORT|1.1476|1.14744|0.00016|2026-03-31 02:00:42|0.02|-14.4
55|NZDUSD|LONG|0.57207|0.5727|0.00063|2026-03-31 02:00:42|0.04|-11.5
56|EURAUD|LONG|1.67256|1.67266|0.00010|2026-03-31 11:02:11|0.94|-22.7
57|EURGBP|SHORT|0.86876|0.86824|0.00052|2026-03-31 11:08:31|0.94|-8.0
58|USDCHF|LONG|0.79952|0.79962|0.00010|2026-03-31 12:01:22|0.78|32.5
59|EURAUD|SHORT|1.67387|1.67283|0.00104|2026-03-31 13:00:54|0.37|-40.8
60|USDCHF|SHORT|0.79992|0.79984|0.00008|2026-03-31 19:38:46|0.87|-15.4
61|NZDUSD|LONG|0.5762|0.57643|0.00023|2026-04-01 13:13:43|0.85|-5.2
62|EURAUD|SHORT|1.67267|1.67244|0.00023|2026-04-01 17:00:26|0.87|-17.1
63|EURAUD|LONG|1.67257|1.67338|0.00081|2026-04-01 20:00:23|0.37|6.5
64|NZDUSD|SHORT|0.57652|0.57517|0.00135|2026-04-01 23:00:49|0.63|-7.9
65|EURUSD|SHORT|1.15397|1.1538|0.00017|2026-04-02 03:57:06|0.31|-24.2
66|EURGBP|LONG|0.87202|0.87215|0.00013|2026-04-02 03:57:07|0.82|-3.6
67|USDCHF|SHORT|0.79895|0.79895|0.0|2026-04-02 13:01:18|0.35|3.7
68|USDCHF|LONG|0.79865|0.79873|0.00008|2026-04-02 15:57:45|0.66|-8.6
69|NZDUSD|SHORT|0.5726|0.57167|0.00093|2026-04-03 00:00:35|0.36|7.7
70|EURGBP|SHORT|0.87221|0.87204|0.00017|2026-04-03 02:00:45|0.41|-14.0
71|EURAUD|SHORT|1.67119|1.67095|0.00024|2026-04-03 13:00:39|0.99|-5.1
72|EURAUD|LONG|1.67119|1.67136|0.00017|2026-04-03 17:00:59|0.43|9.7
73|EURAUD|SHORT|1.67157|1.67137|0.00020|2026-04-05 23:00:27|0.59|26.1
74|EURGBP|SHORT|0.87282|0.87213|0.00069|2026-04-06 02:00:59|0.72|-6.6
75|EURUSD|LONG|1.15442|1.15448|0.00006|2026-04-06 16:00:06|0.66|-7.3
76|USDCHF|SHORT|0.7979|0.79782|0.00008|2026-04-06 16:01:07|0.52|-9.2
77|EURAUD|SHORT|1.66766|1.6675|0.00016|2026-04-07 00:29:26|0.43|-32.7
78|NZDUSD|SHORT|0.57211|0.5719|0.00021|2026-04-07 09:00:44|0.83|15.5
79|EURUSD|SHORT|1.15605|1.1559|0.00015|2026-04-07 13:29:48|0.49|-20.0
80|NZDUSD|LONG|0.5705|0.57073|0.00023|2026-04-07 14:22:02|0.65|22.7
81|USDCHF|SHORT|0.80006|0.79924|0.00082|2026-04-07 19:00:04|0.52|15.7
82|EURGBP|SHORT|0.87171|0.87158|0.00013|2026-04-08 00:53:09|0.63|14.6
83|USDCHF|LONG|0.78843|0.78857|0.00014|2026-04-08 13:32:16|0.35|38.3
84|EURAUD|SHORT|1.65665|1.65654|0.00011|2026-04-08 15:13:49|0.29|-31.6
85|NZDUSD|LONG|0.58201|0.58255|0.00054|2026-04-08 23:00:08|1.00|-1.1
86|EURUSD|LONG|1.16645|1.16669|0.00024|2026-04-09 05:00:03|1.11|-9.3
87|USDCHF|SHORT|0.7905|0.79044|0.00006|2026-04-09 13:00:32|0.65|-7.4
88|USDCHF|LONG|0.7905|0.79056|0.00006|2026-04-09 18:33:58|0.59|-18.0
89|NZDUSD|LONG|0.58499|0.58528|0.00029|2026-04-10 02:00:58|0.63|-9.1
90|EURUSD|LONG|1.16909|1.16928|0.00019|2026-04-10 05:00:19|0.69|-8.0
91|EURGBP|LONG|0.87081|0.87096|0.00015|2026-04-10 08:51:48|0.80|3.2
92|EURGBP|SHORT|0.87123|0.87097|0.00026|2026-04-10 15:36:51|0.87|-8.1
93|USDCHF|SHORT|0.78945|0.78936|0.00009|2026-04-10 17:16:17|0.42|-17.8
94|EURJPY|LONG|186.652|186.684|0.032|2026-04-13 00:39:36|0.56|10.3
95|EURUSD|LONG|1.16863|1.1687|0.00007|2026-04-13 02:01:00|0.97|-3.4
96|CHFJPY|SHORT|201.735|201.67|0.065|2026-04-13 03:00:15|0.71|-21.0
97|EURGBP|LONG|0.87099|0.87117|0.00018|2026-04-13 06:46:11|0.66|-9.8
98|EURAUD|SHORT|1.6572|1.65703|0.00017|2026-04-13 08:03:34|0.7|-18.8
99|USDCHF|SHORT|0.78945|0.78935|0.00010|2026-04-13 11:15:23|0.41|-17.6
100|NZDUSD|LONG|0.58252|0.58367|0.00115|2026-04-13 14:00:44|0.84|29.9
101|EURAUD|SHORT|1.6572|1.65715|0.00005|2026-04-13 14:21:59|0.72|-17.8
102|EURGBP|SHORT|0.87061|0.87029|0.00032|2026-04-14 05:00:42|0.81|-8.3
103|NZDUSD|LONG|0.59055|0.59068|0.00013|2026-04-14 23:45:56|0.91|-9.9
104|CHFJPY|LONG|203.526|203.537|0.011|2026-04-15 01:41:33|0.46|-20.1
105|EURGBP|LONG|0.86891|0.86901|0.00010|2026-04-15 03:00:57|0.81|4.5
106|EURJPY|LONG|187.46|187.483|0.023|2026-04-15 05:07:27|0.32|2.5
107|USDCHF|SHORT|0.78055|0.78047|0.00008|2026-04-15 08:12:17|0.62|-11.2
108|GBPJPY|LONG|215.415|215.429|0.014|2026-04-15 11:11:07|0.92|30.5
109|EURUSD|LONG|1.1788|1.18014|0.00134|2026-04-15 15:17:59|0.44|1.0
110|CHFJPY|SHORT|203.37|203.267|0.103|2026-04-15 17:00:53|0.36|20.1
111|USDCHF|SHORT|0.78254|0.78123|0.00131|2026-04-16 02:00:59|0.75|10.8
112|EURJPY|LONG|187.208|187.363|0.155|2026-04-16 07:22:34|0.43|12.9
113|EURUSD|SHORT|1.18033|1.1792|0.00113|2026-04-16 08:00:29|0.7|14.8
114|GBPJPY|LONG|215.573|215.591|0.018|2026-04-16 14:00:44|0.65|-22.9
115|CHFJPY|LONG|203.364|203.493|0.129|2026-04-17 01:00:40|0.44|5.4
116|EURUSD|LONG|1.17717|1.1776|0.00043|2026-04-17 06:48:27|0.94|20.2
117|CHFJPY|SHORT|203.561|203.333|0.228|2026-04-17 07:00:32|0.9|-16.4
118|USDCHF|SHORT|0.78324|0.78217|0.00107|2026-04-17 09:00:57|0.52|26.0
119|EURAUD|LONG|1.64454|1.64485|0.00031|2026-04-17 11:00:10|0.73|-17.6
120|EURGBP|LONG|0.87035|0.87059|0.00024|2026-04-17 14:41:13|0.33|5.4
121|EURAUD|LONG|1.64111|1.64399|0.00288|2026-04-19 23:00:25|0.54|13.3
122|EURGBP|SHORT|0.87099|0.87082|0.00017|2026-04-20 08:00:51|0.8|-2.3
123|CHFJPY|LONG|202.942|203.308|0.366|2026-04-20 09:03:41|0.77|28.6
124|EURAUD|SHORT|1.64405|1.64361|0.00044|2026-04-20 10:00:25|0.63|-21.1
125|USDCHF|SHORT|0.78094|0.77987|0.00107|2026-04-20 14:00:50|0.61|-12.2
126|GBPJPY|SHORT|214.742|214.634|0.108|2026-04-20 14:01:30|0.6|-25.1
127|EURJPY|SHORT|186.976|186.903|0.073|2026-04-20 15:13:30|0.53|-27.9
128|EURAUD|LONG|1.64244|1.64321|0.00077|2026-04-21 04:00:37|1.51|-2.7
129|EURUSD|SHORT|1.17755|1.17646|0.00109|2026-04-21 08:00:48|0.74|15.5
130|EURGBP|LONG|0.87092|0.87131|0.00039|2026-04-21 09:00:09|0.6|-8.5
131|EURAUD|SHORT|1.64231|1.64197|0.00034|2026-04-21 17:00:05|0.57|6.4
132|CHFJPY|SHORT|204.097|204.072|0.025|2026-04-21 20:00:19|0.65|-22.5
133|EURJPY|SHORT|187.313|187.146|0.167|2026-04-21 20:00:21|0.59|-24.7
134|CHFJPY|LONG|203.879|204.0|0.121|2026-04-22 10:01:11|0.77|-18.7
135|GBPJPY|LONG|215.184|215.107|-0.077|2026-04-22 11:37:31|0.87|-17.1
136|NZDUSD|LONG|0.59036|0.59077|0.00041|2026-04-22 12:00:42|0.6|3.0
137|EURUSD|SHORT|1.175|1.17417|0.00083|2026-04-22 14:00:28|0.52|24.3
138|NZDUSD|SHORT|0.5912|0.59036|0.00084|2026-04-22 19:00:06|0.81|-11.0
139|EURAUD|SHORT|1.63592|1.63538|0.00054|2026-04-23 15:00:07|0.39|-31.7
140|EURAUD|LONG|1.63592|1.63695|0.00103|2026-04-23 18:00:27|0.42|32.0
141|EURJPY|LONG|186.525|186.643|0.118|2026-04-23 23:00:51|0.79|-17.9
142|EURUSD|SHORT|1.16911|1.16891|0.00020|2026-04-24 10:18:24|0.54|-18.0
143|CHFJPY|SHORT|203.224|203.068|0.156|2026-04-24 10:18:25|0.41|27.0
144|EURGBP|SHORT|0.86762|0.86735|0.00027|2026-04-24 11:01:03|0.66|-9.6
145|USDCHF|SHORT|0.78555|0.78514|0.00041|2026-04-24 12:00:44|0.49|-13.5
146|GBPJPY|LONG|215.137|215.389|0.252|2026-04-24 13:00:59|0.34|27.3
147|EURAUD|SHORT|1.64073|1.63963|0.00110|2026-04-24 15:00:15|0.65|13.6
148|CHFJPY|LONG|202.724|202.938|0.214|2026-04-26 23:00:10|0.43|21.2
149|EURAUD|SHORT|1.64073|1.63877|0.00196|2026-04-27 00:00:21|0.73|19.8
150|USDCHF|LONG|0.78455|0.78533|0.00078|2026-04-27 17:00:35|0.52|12.7
151|EURGBP|SHORT|0.86673|0.86599|0.00074|2026-04-27 19:00:03|0.64|5.8
152|EURAUD|SHORT|1.63145|1.62999|0.00146|2026-04-28 08:39:47|0.44|-23.7
"""

trades = []
for line in RAW.strip().splitlines():
    parts = line.split('|')
    if len(parts) < 9:
        continue
    tid, sym, direc, intended, actual, slip_raw, opened, lot, pnl_pips = parts[:9]
    sym = sym.strip()
    direc = direc.strip()
    intended = float(intended)
    actual = float(actual)
    pip = PIP_VALUES.get(sym, 0.0001)
    # Signed slippage in pips: + means we got a WORSE entry (paid more / received less)
    sign = 1 if direc == 'LONG' else -1
    slip_pips = sign * (actual - intended) / pip
    drift_abs_pips = abs(actual - intended) / pip
    dt = datetime.fromisoformat(opened.split('.')[0])
    trades.append({
        'id': int(tid),
        'sym': sym,
        'dir': direc,
        'lot': float(lot),
        'slip_pips': slip_pips,
        'drift_abs_pips': drift_abs_pips,
        'hour': dt.hour,
        'minute': dt.minute,
        'second': dt.second,
        'opened': dt,
        'pnl_pips': float(pnl_pips),
    })

print(f"=== KZ_HUNT TRADES SINCE 2026-03-25: {len(trades)} ===\n")

# Overall
slips = [t['slip_pips'] for t in trades]
drifts = [t['drift_abs_pips'] for t in trades]
print(f"Signed slippage (worse=+): mean={statistics.mean(slips):+.2f}p median={statistics.median(slips):+.2f}p max={max(slips):+.2f}p min={min(slips):+.2f}p")
print(f"Abs drift |actual-intended|: mean={statistics.mean(drifts):.2f}p median={statistics.median(drifts):.2f}p max={max(drifts):.2f}p")
adverse = [s for s in slips if s > 0]
favourable = [s for s in slips if s < 0]
print(f"Adverse fills (got worse price): {len(adverse)}/{len(slips)} ({100*len(adverse)/len(slips):.0f}%) avg adverse={statistics.mean(adverse):+.2f}p")
print(f"Favourable fills: {len(favourable)}/{len(slips)} avg fav={statistics.mean(favourable):+.2f}p")

# Drift distribution
gt2 = sum(1 for d in drifts if d > 2)
gt5 = sum(1 for d in drifts if d > 5)
gt10 = sum(1 for d in drifts if d > 10)
gt20 = sum(1 for d in drifts if d > 20)
print(f"\nDrift > 2p: {gt2}/{len(drifts)} ({100*gt2/len(drifts):.0f}%)")
print(f"Drift > 5p: {gt5}/{len(drifts)} ({100*gt5/len(drifts):.0f}%)")
print(f"Drift > 10p: {gt10}/{len(drifts)} ({100*gt10/len(drifts):.0f}%)")
print(f"Drift > 20p: {gt20}/{len(drifts)} ({100*gt20/len(drifts):.0f}%)")

# Per pair (signed slip)
print("\n=== BY PAIR (signed slip pips, +=worse) ===")
by_pair = defaultdict(list)
for t in trades:
    by_pair[t['sym']].append(t)
for sym in sorted(by_pair.keys()):
    arr = by_pair[sym]
    s = [t['slip_pips'] for t in arr]
    d = [t['drift_abs_pips'] for t in arr]
    print(f"{sym}: n={len(arr)} mean_slip={statistics.mean(s):+.2f}p mean_drift={statistics.mean(d):.2f}p max_drift={max(d):.2f}p")

# By hour
print("\n=== BY UTC HOUR (signed slip pips) ===")
by_hour = defaultdict(list)
for t in trades:
    by_hour[t['hour']].append(t)
for hr in sorted(by_hour.keys()):
    arr = by_hour[hr]
    s = [t['slip_pips'] for t in arr]
    print(f"{hr:02d}:00  n={len(arr):>2}  mean={statistics.mean(s):+6.2f}p  max_adv={max(s):+6.2f}p")

# By lot size bucket
print("\n=== BY LOT SIZE BUCKET ===")
buckets = [(0, 0.1), (0.1, 0.5), (0.5, 1.0), (1.0, 5.0)]
for lo, hi in buckets:
    arr = [t for t in trades if lo <= t['lot'] < hi]
    if not arr:
        continue
    s = [t['slip_pips'] for t in arr]
    d = [t['drift_abs_pips'] for t in arr]
    print(f"lots [{lo:.2f},{hi:.2f}): n={len(arr):>2} mean_slip={statistics.mean(s):+.2f}p mean_drift={statistics.mean(d):.2f}p")

# Bar-close timing: how long after :00 does order fire?
# H1 bars close on the hour. Order fires from confirmation in the next 60s scanner cycle.
print("\n=== TIMING: SECONDS AFTER H1 BAR-CLOSE TO ORDER FILL ===")
# bar_close = top of the hour the order opened in (or earliest such candidate)
# For mid-hour entries (e.g. 11:08:31), bar-close was 11:00 -> 8m 31s late
# But entries within 0-90s of :00 were likely fired same cycle as bar close.
secs_late = []
for t in trades:
    secs = t['minute'] * 60 + t['second']
    secs_late.append(secs)
print(f"Seconds-into-bar at fill: mean={statistics.mean(secs_late):.0f}s median={statistics.median(secs_late):.0f}s max={max(secs_late):.0f}s")
within_60 = sum(1 for s in secs_late if s <= 60)
within_120 = sum(1 for s in secs_late if s <= 120)
print(f"Filled within 60s of bar-close: {within_60}/{len(secs_late)} ({100*within_60/len(secs_late):.0f}%)")
print(f"Filled within 120s of bar-close: {within_120}/{len(secs_late)} ({100*within_120/len(secs_late):.0f}%)")

# Loss recovery estimate
print("\n=== EXPECTED RECOVERY ===")
total_adv_pips_lost = sum(s for s in slips if s > 0)
total_drift_pips = sum(drifts)
print(f"Total adverse slip across {len(trades)} trades: {total_adv_pips_lost:.0f} pips")
print(f"Total |drift| across {len(trades)} trades: {total_drift_pips:.0f} pips")

# Convert to USD using actual lot per trade
total_usd_adverse = 0.0
total_usd_drift = 0.0
for t in trades:
    upp = USD_PER_PIP_PER_LOT.get(t['sym'], 10.0)
    if t['slip_pips'] > 0:
        total_usd_adverse += t['slip_pips'] * t['lot'] * upp
    total_usd_drift += t['drift_abs_pips'] * t['lot'] * upp
print(f"USD impact (adverse only): ${total_usd_adverse:.0f}")
print(f"USD impact (|drift|): ${total_usd_drift:.0f}")

# If we eliminated slippage entirely, projected per-100 trades
avg_adv_pips_per_trade = total_adv_pips_lost / len(trades)
print(f"\nAvg adverse slippage per trade: {avg_adv_pips_per_trade:.2f}p")
print(f"If reduced 5.2p -> 1.0p: save ~{(5.2-1.0)*len(trades):.0f} pips total")
