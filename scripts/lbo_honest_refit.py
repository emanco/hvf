"""LONDON_BO honest re-fit: is there ANY parameterisation that survives a real fill model?

Context (2026-07-28). scripts/lbo_fill_model_compare.py showed the incumbent
validation (PF 1.63) fills 62% of trades at a price never available: the
deployed geometry ends its range at 04:00 UTC but opens its window at 08:00, a
4h blind gap, and the sim awards the level on days that opened through it.
scripts/lbo_geometry_x_fill.py showed incumbent PF tracks blind-gap size
monotonically (4h/1h/0h -> 1.75/1.11/0.88), and that on the zero-gap geometry
all fill models converge (~0.86).

But the retirement call was premature on two counts, both conceded:
  1. the 10-22p band was itself selected UNDER the fill fiction, so testing an
     honest geometry with it is not a fair test;
  2. only 3 geometries and one payoff shape (TP 1.0x, SL opposite edge, 13:00
     exit) were ever tried honestly.
This script fixes both: sweep the design space under an honest fill model, with
a train/test split and an adoption rule pre-committed below.

FILL MODEL (single, applied everywhere -- a real resting pending stop):
  - order rests at the breakout level from window open;
  - a bar that OPENS beyond the level fills at that open (gap), else at the
    level; SL/TP/size derive from the level, as the live code does;
  - if the FIRST window bar already opens through the level the stop order is
    invalid at placement (IC retcode 10015) -> no trade, as ASB behaves today.
  Zero-blind-gap geometries (window_start == range_end) have essentially no
  already-through case, which is precisely why they are worth testing.

PRE-COMMITTED ADOPTION RULE (fixed before any test-set number is computed):
  Train = sessions through 2023-12-31.  Test = 2024-01-01 onward.
  S1 select the single train cell with the highest avgR, requiring N_train>=60.
  S2 robustness: the median avgR of that cell's TP/SL neighbours must be > 0
     (a whole family must work, not one spike -- as with the ASB BE12 adoption).
  S3 adopt only if on TEST: PF >= 1.20 AND avgR > 0 AND N_test >= 30.
  If S1-S3 do not all pass, LONDON_BO is retired. No second look, no re-slice.

Reported alongside: the incumbent cell as a sanity row, and the fraction of the
whole grid that is positive on train vs test -- if most cells are positive the
selection means little, and if train-positive cells are ~50% positive on test
the grid is noise.

Read-only.
Usage: ssh hvf-vps "C:/hvf_trader/venv/Scripts/python.exe -" < scripts/lbo_honest_refit.py
"""
import os
import itertools
from datetime import datetime, timezone, timedelta
import numpy as np
import MetaTrader5 as mt5
from dotenv import load_dotenv

SYMS = {
    "GBPUSD": {"pip": 0.0001, "spread_p": 1.0, "comm_p": 0.7},
    "GBPJPY": {"pip": 0.01,   "spread_p": 1.9, "comm_p": 1.05},
}
DAYS = (0, 1)  # Mon/Tue, as deployed
SPLIT_YEAR = 2024  # train < 2024, test >= 2024

# ---- design grid -------------------------------------------------------
RANGE_ENDS   = (4, 5, 6, 7)          # UTC hour the Asian range stops forming
WINDOW_ENDS  = (13, 16)              # UTC force-close hour (13 = deployed)
TP_MULTS     = (0.5, 0.75, 1.0, 1.5, 2.0)   # x range
SL_MULTS     = (0.5, 0.75, 1.0)      # x range from the level (1.0 ~ opposite edge)
BANDS        = ((8, 999), (8, 25), (10, 22), (12, 20))
# window_start: range_end == zero blind gap (honest), or 8 == incumbent-style
def window_starts(re_):
    return sorted({re_, 8}) if re_ < 8 else [re_]

INCUMBENT = dict(range_end=4, win_start=8, win_end=13, tp=1.0, sl=1.0, band=(10, 22))

load_dotenv(r"C:/hvf_trader/.env")
mt5.shutdown()
assert mt5.initialize(path=os.getenv("MT5_PATH")), mt5.last_error()
assert mt5.login(int(os.getenv("MT5_LOGIN")), password=os.getenv("MT5_PASSWORD"),
                 server=os.getenv("MT5_SERVER")), mt5.last_error()


def eu_dst_offset(dt_utc):
    y = dt_utc.year
    mar = datetime(y, 3, 31, 1, tzinfo=timezone.utc)
    mar_last_sun = mar - timedelta(days=(mar.weekday() + 1) % 7)
    oct_ = datetime(y, 10, 31, 1, tzinfo=timezone.utc)
    oct_last_sun = oct_ - timedelta(days=(oct_.weekday() + 1) % 7)
    return 3 if mar_last_sun <= dt_utc < oct_last_sun else 2


def load_sessions(sym):
    rates = mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_H1, 0, 50000)
    sess = {}
    for r in rates:
        t_broker = datetime.fromtimestamp(r[0], tz=timezone.utc)  # mislabeled UTC
        off = eu_dst_offset(t_broker - timedelta(hours=3))
        t = t_broker - timedelta(hours=off)
        if t.weekday() >= 5 or t.weekday() not in DAYS:
            continue
        sess.setdefault(t.date(), []).append(
            {"uh": t.hour, "o": r[1], "hi": r[2], "lo": r[3], "cl": r[4]})
    return {d: sorted(b, key=lambda x: x["uh"]) for d, b in sess.items()}


def run(sym, sessions, p, year_filter):
    """p: dict of range_end/win_start/win_end/tp/sl/band. Returns list of R."""
    cfg = SYMS[sym]
    pip = cfg["pip"]
    sp = cfg["spread_p"] * pip
    cost_p = cfg["spread_p"] + cfg["comm_p"]
    lo_b, hi_b = p["band"]
    out = []
    for d in sorted(sessions):
        if not year_filter(d.year):
            continue
        bars = sessions[d]
        asian = [b for b in bars if b["uh"] < p["range_end"]]
        if len(asian) < 3:
            continue
        a_hi = max(b["hi"] for b in asian)
        a_lo = min(b["lo"] for b in asian)
        rng = (a_hi - a_lo) / pip
        if not (lo_b <= rng <= hi_b):
            continue
        win = [b for b in bars if p["win_start"] <= b["uh"] < p["win_end"]]
        if not win:
            continue

        up_lvl, dn_lvl = a_hi + sp, a_lo - sp
        first = win[0]
        # pending stop invalid at placement -> no trade
        if first["o"] > up_lvl or first["o"] < dn_lvl:
            continue

        direction = None
        for i, b in enumerate(win):
            if b["hi"] > up_lvl:
                # gap through on this bar's open? fill worse, else at level
                entry = max(up_lvl, b["o"]) if b["o"] > up_lvl else up_lvl
                direction, start = "LONG", i
                break
            if b["lo"] < dn_lvl:
                entry = min(dn_lvl, b["o"]) if b["o"] < dn_lvl else dn_lvl
                direction, start = "SHORT", i
                break
        if direction is None:
            continue

        risk_d = rng * p["sl"] * pip
        tp_d = rng * p["tp"] * pip
        if direction == "LONG":
            lvl = up_lvl
            sl, tp = lvl - risk_d, lvl + tp_d
        else:
            lvl = dn_lvl
            sl, tp = lvl + risk_d, lvl - tp_d
        intended_risk = risk_d / pip

        pnl_p = None
        for rb in win[start:]:
            if direction == "LONG":
                if rb["lo"] <= sl:
                    pnl_p = (sl - entry) / pip
                    break
                if rb["hi"] >= tp:
                    pnl_p = (tp - entry) / pip
                    break
            else:
                if rb["hi"] >= sl:
                    pnl_p = (entry - sl) / pip
                    break
                if rb["lo"] <= tp:
                    pnl_p = (entry - tp) / pip
                    break
        if pnl_p is None:
            last = win[-1]["cl"]
            pnl_p = (last - entry) / pip if direction == "LONG" else (entry - last) / pip
        out.append((pnl_p - cost_p) / intended_risk)
    return out


def m(R):
    if not R:
        return dict(N=0, WR=0, PF=0, avgR=0, totR=0, ddR=0)
    v = np.array(R)
    gp = v[v > 0].sum()
    gl = abs(v[v <= 0].sum()) or 1e-9
    eq = np.cumsum(v)
    return dict(N=len(v), WR=(v > 0).mean() * 100, PF=gp / gl, avgR=v.mean(),
                totR=v.sum(), ddR=float((np.maximum.accumulate(eq) - eq).max()))


def fmt(s):
    return (f"N={s['N']:>4} WR={s['WR']:>3.0f}% PF={s['PF']:>5.2f} "
            f"avgR={s['avgR']:>+6.3f} totR={s['totR']:>+7.1f} ddR={s['ddR']:>5.1f}")


GRID = []
for re_, we, tp, sl, band in itertools.product(
        RANGE_ENDS, WINDOW_ENDS, TP_MULTS, SL_MULTS, BANDS):
    for ws in window_starts(re_):
        if ws >= we:
            continue
        GRID.append(dict(range_end=re_, win_start=ws, win_end=we,
                         tp=tp, sl=sl, band=band))

SYM = "GBPUSD"
sessions = load_sessions(SYM)
print(f"{SYM}: {len(sessions)} Mon/Tue sessions, "
      f"{min(sessions)} .. {max(sessions)}   grid = {len(GRID)} cells")
print(f"\nPRE-COMMITTED RULE: select max train avgR (N_train>=60); require median")
print(f"neighbour avgR > 0; adopt iff TEST PF>=1.20 AND avgR>0 AND N_test>=30.")

TRAIN = lambda y: y < SPLIT_YEAR
TEST = lambda y: y >= SPLIT_YEAR

print(f"\n=== sanity: incumbent cell under the honest fill model ===")
print(f"  train  {fmt(m(run(SYM, sessions, INCUMBENT, TRAIN)))}")

train_res = []
for p in GRID:
    train_res.append((p, m(run(SYM, sessions, p, TRAIN))))

pos = sum(1 for _, s in train_res if s["avgR"] > 0)
print(f"\n=== TRAIN (pre-{SPLIT_YEAR}) ===")
print(f"  grid cells positive on train: {pos}/{len(train_res)} ({pos*100//len(train_res)}%)")

elig = [(p, s) for p, s in train_res if s["N"] >= 60]
print(f"  cells meeting N_train>=60: {len(elig)}")
elig.sort(key=lambda x: -x[1]["avgR"])
print("\n  top 10 by train avgR:")
for p, s in elig[:10]:
    print(f"    rng<{p['range_end']} win {p['win_start']}-{p['win_end']} "
          f"tp{p['tp']} sl{p['sl']} band{p['band']}  {fmt(s)}")

best_p, best_s = elig[0]
print(f"\n  S1 SELECTED: rng<{best_p['range_end']} win {best_p['win_start']}-{best_p['win_end']} "
      f"tp{best_p['tp']} sl{best_p['sl']} band{best_p['band']}")
print(f"     train {fmt(best_s)}")

# S2 neighbourhood in TP/SL space
ti, si = TP_MULTS.index(best_p["tp"]), SL_MULTS.index(best_p["sl"])
nb = []
for dt_, ds in itertools.product((-1, 0, 1), (-1, 0, 1)):
    if dt_ == 0 and ds == 0:
        continue
    a, b = ti + dt_, si + ds
    if 0 <= a < len(TP_MULTS) and 0 <= b < len(SL_MULTS):
        q = dict(best_p, tp=TP_MULTS[a], sl=SL_MULTS[b])
        nb.append(m(run(SYM, sessions, q, TRAIN))["avgR"])
med_nb = float(np.median(nb))
s2 = med_nb > 0
print(f"  S2 neighbourhood median avgR = {med_nb:+.3f} over {len(nb)} cells -> "
      f"{'PASS' if s2 else 'FAIL'}")

print(f"\n=== TEST ({SPLIT_YEAR}+) — first look ===")
test_s = m(run(SYM, sessions, best_p, TEST))
print(f"  selected cell: {fmt(test_s)}")
print(f"  incumbent    : {fmt(m(run(SYM, sessions, INCUMBENT, TEST)))}")

test_all = [m(run(SYM, sessions, p, TEST)) for p, _ in train_res]
tpos = sum(1 for s in test_all if s["avgR"] > 0)
tr_pos_idx = [i for i, (_, s) in enumerate(train_res) if s["avgR"] > 0]
carry = sum(1 for i in tr_pos_idx if test_all[i]["avgR"] > 0)
print(f"\n  grid positive on test: {tpos}/{len(test_all)} ({tpos*100//len(test_all)}%)")
if tr_pos_idx:
    print(f"  train-positive cells that stay positive on test: "
          f"{carry}/{len(tr_pos_idx)} ({carry*100//len(tr_pos_idx)}%)  "
          f"[~50% = noise]")

s3 = test_s["PF"] >= 1.20 and test_s["avgR"] > 0 and test_s["N"] >= 30
print(f"\n=== VERDICT ===")
print(f"  S1 selected (N_train={best_s['N']}>=60)      PASS")
print(f"  S2 family robust (median nb avgR {med_nb:+.3f})  {'PASS' if s2 else 'FAIL'}")
print(f"  S3 test PF {test_s['PF']:.2f}>=1.20, avgR {test_s['avgR']:+.3f}>0, "
      f"N {test_s['N']}>=30   {'PASS' if s3 else 'FAIL'}")
print(f"  -> {'ADOPT' if (s2 and s3) else 'RETIRE LONDON_BO'}")

if s2 and s3:
    print(f"\n  confirmation on GBPJPY (not part of selection):")
    gj = load_sessions("GBPJPY")
    print(f"    train {fmt(m(run('GBPJPY', gj, best_p, TRAIN)))}")
    print(f"    test  {fmt(m(run('GBPJPY', gj, best_p, TEST)))}")

mt5.shutdown()
