"""NIGHT_TIDE IC-native feed diagnostic + PF estimate.

Why this exists (2026-07-02 investigation): live NIGHT_TIDE fired ~6/mo vs the
Dukascopy backtest's ~25-34/mo expectation. Running the identical detector over
identical months on both feeds showed IC Markets' M15 feed produces ~4x fewer
BB+RSI co-extreme signals (~13.5/mo vs ~50/mo across the 4 pairs, stable since
2022 — a feed difference, not a regime change). EURCHF: near-zero setups on
IC's feed since 2025-10, explaining its zero live fires.

This script simulates the strategy over IC's own M15 history (2025-01 -> now)
with per-bar recorded spreads, in two evaluation modes:
  close = completed-bar close (Dukascopy-backtest semantics)
  stub  = forming bar evaluated once at open (what the live scanner does via
          copy_rates_from_pos position 0 + iloc[-1] + new-bar dedup)

Results 2026-07-02 (18mo, +0.8p commission):
  ALL [close]  N=233 WR=45% PF=0.80  -271p  dd=401p   <- LOSES on IC feed
  ALL [stub]   N=199 WR=59% PF=1.42  +377p  dd= 81p   <- current live behavior
The stub's one-bar-late persistence filter is load-bearing — do NOT switch the
scanner to completed-close evaluation unless this comparison says otherwise.
Stub trade count over the live period (13) matched actual fills (12).

Caveats: IC per-bar spread field is optimistic (median ~0.1p in-window on a Raw
demo account), so true live PF sits somewhat below the sim; the sim uses the
static 3p TP filter, not the stricter live real-time-spread check.

Usage (read-only — rates fetches only, safe while the bot is live):
    ssh hvf-vps "C:/hvf_trader/venv/Scripts/python.exe -" < scripts/nt_ic_feed_diag.py
"""
import os
import time as _time
import numpy as np
import pandas as pd
import MetaTrader5 as mt5
from dotenv import load_dotenv

PAIRS = ["AUDNZD", "NZDCAD", "AUDCAD", "EURCHF"]
PIP = 0.0001
SL_PIPS, MAX_HOLD = 12, 16
BB_P, BB_STD, RSI_P = 20, 2.0, 14
TP_MIN = 3.0
COMMISSION_PIPS = 0.8  # ~$7/lot round trip at ~$8-9/pip/lot on these crosses
START = pd.Timestamp("2025-01-01")

load_dotenv(r"C:/hvf_trader/.env")
mt5.shutdown()
assert mt5.initialize(path=os.getenv("MT5_PATH")), mt5.last_error()
assert mt5.login(int(os.getenv("MT5_LOGIN")), password=os.getenv("MT5_PASSWORD"),
                 server=os.getenv("MT5_SERVER")), mt5.last_error()
tick = mt5.symbol_info_tick("AUDCAD")
offset_h = round((tick.time - _time.time()) / 3600)


def rsi_sma(closes):
    d = np.diff(closes)
    g = np.where(d > 0, d, 0.0)[-RSI_P:]
    l = np.where(d < 0, -d, 0.0)[-RSI_P:]
    al = l.mean() or 1e-9
    return 100 - 100 / (1 + g.mean() / al)


def simulate(df, variant):
    closes, opens = df["close"].values, df["open"].values
    highs, lows = df["high"].values, df["low"].values
    hours = df["utc_hour"].values
    spreads = df["spread_pips"].values
    n = len(df)
    pnls = []
    i = BB_P + RSI_P + 2
    while i < n - 1:
        h = hours[i]
        if not (h >= 22 or h < 1):
            i += 1
            continue
        if variant == "close":
            w = closes[i - BB_P + 1: i + 1]
            price = closes[i]
            rsi = rsi_sma(closes[i - RSI_P - 1: i + 1])
        else:
            w = np.append(closes[i - BB_P + 1: i], opens[i])
            price = opens[i]
            rsi = rsi_sma(np.append(closes[i - RSI_P - 1: i], opens[i]))
        mid, sd = w.mean(), w.std(ddof=1)
        direction = None
        if price < mid - BB_STD * sd and rsi < 30:
            direction = "L"
        elif price > mid + BB_STD * sd and rsi > 70:
            direction = "S"
        tp_dist = abs(mid - price) / PIP if direction else 0
        if direction is None or tp_dist < TP_MIN:
            i += 1
            continue
        entry, tp = price, mid
        sp = spreads[i]
        sl = entry - SL_PIPS * PIP if direction == "L" else entry + SL_PIPS * PIP
        pnl = None
        exit_j = min(i + MAX_HOLD, n - 1)
        for j in range(i + 1, exit_j + 1):
            if direction == "L":
                if lows[j] <= sl:
                    pnl = (sl - entry) / PIP - sp
                elif highs[j] >= tp:
                    pnl = (tp - entry) / PIP - sp
            else:
                sp_price = sp * PIP
                if highs[j] >= sl - sp_price:
                    pnl = (entry - sl) / PIP - sp
                elif lows[j] <= tp - sp_price:
                    pnl = (entry - tp) / PIP - sp
            if pnl is not None:
                exit_j = j
                break
        if pnl is None:
            c = closes[exit_j]
            pnl = ((c - entry) if direction == "L" else (entry - c)) / PIP - sp
        pnls.append(pnl)
        i = exit_j + 1
    return np.array(pnls)


def stats(pnls, label):
    if len(pnls) == 0:
        print(f"{label}: no trades")
        return
    net = pnls - COMMISSION_PIPS
    for tag, arr in (("spread only", pnls), ("+0.8p comm", net)):
        wins = (arr > 0).sum()
        gp = arr[arr > 0].sum() if wins else 0.0
        gl = abs(arr[arr <= 0].sum()) or 0.001
        eq = np.cumsum(arr)
        dd = (np.maximum.accumulate(eq) - eq).max() if len(arr) > 1 else 0
        print(f"{label:<22}{tag:<13} N={len(arr):>3} WR={wins/len(arr)*100:>3.0f}% "
              f"PF={gp/gl:>5.2f} tot={arr.sum():>+8.1f}p dd={dd:>6.1f}p")


all_pnls = {"close": [], "stub": []}
for sym in PAIRS:
    rates = None
    for want in (99000, 50000, 20000, 10000):
        rates = mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_M15, 0, want)
        if rates is not None and len(rates) > 0:
            break
    df = pd.DataFrame(rates)
    df["utc_t"] = pd.to_datetime(df["time"], unit="s") - pd.Timedelta(hours=offset_h)
    df = df[df["utc_t"] >= START].reset_index(drop=True)
    df = df.iloc[:-1]
    df["utc_hour"] = df["utc_t"].dt.hour
    df["spread_pips"] = df["spread"] / 10.0
    win_mask = (df["utc_hour"] >= 22) | (df["utc_hour"] < 1)
    med_sp = df.loc[win_mask, "spread_pips"].median()
    print(f"# {sym}: {len(df)} bars from {df['utc_t'].iloc[0].date()}, "
          f"median in-window spread {med_sp:.1f}p")
    for variant in ("close", "stub"):
        p = simulate(df, variant)
        stats(p, f"{sym} [{variant}]")
        all_pnls[variant].append(p)
    print()

print("=== PORTFOLIO (4 pairs, 2025-01 -> now, IC feed) ===")
for variant in ("close", "stub"):
    stats(np.concatenate(all_pnls[variant]), f"ALL [{variant}]")
mt5.shutdown()
