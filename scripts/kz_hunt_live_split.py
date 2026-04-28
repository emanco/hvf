"""
KZ_HUNT live trade entry-quality investigation.

Goal: identify what distinguishes the 21 zero-excursion SL trades from the
35 winners. Computes MFE locally from M5 CSVs (no MT5 dependency).

Outputs:
  - Per-trade table with score components recomputed from KZ context
  - Splits by: score band, score components, KZ name, hour, ATR-rel rejection
    size, distance from rejection close to entry-confirmation, kz_range_atr
"""
import json
import os
import sqlite3
import statistics
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

DB = "/tmp/hvf_trader_snap.db"
DATA = Path("/Users/emanuelemanco/dev/hvf/backtests/data")
GO_LIVE = "2026-03-25"

PIP = {
    "EURUSD": 0.0001, "GBPUSD": 0.0001, "AUDUSD": 0.0001, "NZDUSD": 0.0001,
    "USDCAD": 0.0001, "USDCHF": 0.0001, "EURGBP": 0.0001, "EURAUD": 0.0001,
    "USDJPY": 0.01, "GBPJPY": 0.01, "EURJPY": 0.01, "CHFJPY": 0.01,
}
KZ = {"london": (8, 11), "ny_morning": (13, 15), "ny_evening": (16, 20), "asian": (0, 4)}


def load_m5(sym):
    f = DATA / f"{sym}_M5.csv"
    if not f.exists():
        return None
    df = pd.read_csv(f)
    df["dt"] = pd.to_datetime(df["time"], unit="s", utc=True)
    return df


def load_h1(sym):
    f = DATA / f"{sym}_H1.csv"
    if not f.exists():
        return None
    df = pd.read_csv(f)
    df["dt"] = pd.to_datetime(df["time"], unit="s", utc=True)
    # ATR(14) for context
    tr = pd.concat([
        df["high"] - df["low"],
        (df["high"] - df["close"].shift()).abs(),
        (df["low"] - df["close"].shift()).abs(),
    ], axis=1).max(axis=1)
    df["atr"] = tr.rolling(14).mean()
    df["ema_200"] = df["close"].ewm(span=200, adjust=False).mean()
    return df


def main():
    conn = sqlite3.connect(DB)
    rows = conn.execute(f"""
        SELECT t.id, t.symbol, t.direction, t.opened_at, t.closed_at,
               t.entry_price, t.stop_loss, t.target_1, t.target_2,
               t.pnl, t.pnl_pips, t.close_reason,
               p.score, p.pattern_metadata, p.detected_at
        FROM trade_records t
        LEFT JOIN pattern_records p ON p.id = t.pattern_id
        WHERE t.pattern_type='KZ_HUNT' AND t.opened_at >= '{GO_LIVE}'
        ORDER BY t.opened_at
    """).fetchall()
    conn.close()

    h1_cache = {}
    m5_cache = {}

    enriched = []
    for r in rows:
        (tid, sym, direction, oa, ca, ent, sl, t1, t2,
         pnl, pip_pnl, reason, score, meta_str, det_at) = r

        meta = {}
        if meta_str:
            try:
                meta = json.loads(meta_str)
            except Exception:
                pass

        pip = PIP.get(sym, 0.0001)
        op = pd.Timestamp(oa, tz="UTC") if oa else None
        cl = pd.Timestamp(ca, tz="UTC") if ca else None
        det = pd.Timestamp(det_at, tz="UTC") if det_at else None

        # MFE from local M5 (only if covered by data)
        mfe_pips = None
        held_h = None
        if op is not None and cl is not None:
            held_h = (cl - op).total_seconds() / 3600
        if op is not None and cl is not None:
            if sym not in m5_cache:
                m5_cache[sym] = load_m5(sym)
            m5 = m5_cache[sym]
            if m5 is not None and op <= m5["dt"].max():
                clamp = min(cl, m5["dt"].max())
                window = m5[(m5["dt"] >= op) & (m5["dt"] <= clamp)]
                if not window.empty:
                    if direction == "LONG":
                        mfe_pips = (window["high"].max() - ent) / pip
                    else:
                        mfe_pips = (ent - window["low"].min()) / pip

        # Recompute KZ-related features from H1
        kz_high = meta.get("kz_high")
        kz_low = meta.get("kz_low")
        kz_range = meta.get("kz_range")
        kz_name = meta.get("kz_name")
        rej_close = meta.get("rejection_price")

        rej_wick_to_body = None
        rej_size_atr = None
        kz_range_atr = None
        ema_distance_pct = None
        bars_since_rejection = None

        if det is not None:
            if sym not in h1_cache:
                h1_cache[sym] = load_h1(sym)
            h1 = h1_cache[sym]
            if h1 is not None:
                # The rejection bar may have closed up to 30 H1 bars before
                # detection (search_end = search_start+30 in detector). Match
                # by close price to rejection_price (preferred) or entry_price.
                target_close = rej_close if rej_close is not None else ent
                cutoff = det - pd.Timedelta(minutes=55)
                window = h1[(h1["dt"] >= det - pd.Timedelta(hours=72)) & (h1["dt"] <= cutoff)]
                bar = None
                if not window.empty and target_close is not None:
                    diffs = (window["close"] - target_close).abs()
                    # Tolerance: 2 pips (broker bar / CSV tickrate differences)
                    if diffs.min() < pip * 2.0:
                        bar = window.loc[diffs.idxmin()]
                if bar is None and not window.empty:
                    bar = window.iloc[-1]

                if bar is not None:
                    # bars_since_rejection: how stale was the rejection bar?
                    bars_since_rejection = (det - bar["dt"]).total_seconds() / 3600
                    body = abs(bar["close"] - bar["open"]) or 1e-9
                    if direction == "LONG":
                        wick = min(bar["open"], bar["close"]) - bar["low"]
                    else:
                        wick = bar["high"] - max(bar["open"], bar["close"])
                    rej_wick_to_body = wick / body
                    if not np.isnan(bar["atr"]) and bar["atr"] > 0:
                        rej_size_atr = (bar["high"] - bar["low"]) / bar["atr"]
                        # If kz_range absent in metadata, derive from t1 vs sl.
                        # For LONG: kz_high = target_1, kz_low = stop_loss + 0.5*ATR
                        # For SHORT: kz_low  = target_1, kz_high = stop_loss - 0.5*ATR
                        if kz_range is None and t1 is not None and sl is not None:
                            if direction == "LONG":
                                kz_low_est = sl + 0.5 * bar["atr"]
                                kz_high_est = t1
                            else:
                                kz_high_est = sl - 0.5 * bar["atr"]
                                kz_low_est = t1
                            kz_range = abs(kz_high_est - kz_low_est)
                        if kz_range is not None:
                            kz_range_atr = kz_range / bar["atr"]
                    if not np.isnan(bar["ema_200"]) and bar["ema_200"] > 0:
                        ema_distance_pct = (bar["close"] - bar["ema_200"]) / bar["ema_200"] * 100

        sl_pips = abs(ent - sl) / pip
        win = (pnl or 0) > 0

        enriched.append({
            "id": tid, "sym": sym, "dir": direction,
            "score": score or 0,
            "pnl": pnl or 0, "pnl_pips": pip_pnl or 0,
            "reason": reason, "win": win,
            "sl_pips": sl_pips, "mfe_pips": mfe_pips, "held_h": held_h,
            "kz_name": kz_name, "kz_range": kz_range,
            "kz_range_atr": kz_range_atr,
            "rej_wick_to_body": rej_wick_to_body,
            "rej_size_atr": rej_size_atr,
            "ema_distance_pct": ema_distance_pct,
            "bars_since_rejection": bars_since_rejection,
            "hour": op.hour if op else None,
        })

    df = pd.DataFrame(enriched)
    print(f"=== {len(df)} KZ_HUNT trades since {GO_LIVE} ===")
    print(f"Wins: {df['win'].sum()}  WR: {df['win'].mean():.1%}  Sum PnL: ${df['pnl'].sum():+.2f}")
    print(f"Local M5 coverage: {df['mfe_pips'].notna().sum()}/{len(df)} trades")
    print()

    # ── Zero-excursion SL trades vs winners ───────────────────────────────
    sl_zero = df[(df["reason"] == "STOP_LOSS") & (df["mfe_pips"].notna()) & (df["mfe_pips"] <= 5)]
    sl_other = df[(df["reason"] == "STOP_LOSS") & (df["mfe_pips"].notna()) & (df["mfe_pips"] > 5)]
    winners = df[df["win"]]

    def stats(name, sub):
        if sub.empty:
            return
        print(f"  {name} (n={len(sub)}):")
        for col in ["score", "kz_range_atr", "rej_wick_to_body", "rej_size_atr", "ema_distance_pct", "kz_range", "sl_pips"]:
            s = sub[col].dropna()
            if not s.empty:
                print(f"    {col:<22} mean={s.mean():+.3f}  median={s.median():+.3f}  n={len(s)}")

    print("=== Feature comparison: zero-excursion SL vs winners ===")
    stats("zero-excursion SL (MFE<=5p)", sl_zero)
    stats("other SL (MFE>5p)", sl_other)
    stats("winners", winners)
    print()

    # ── Per-component breakdown ───────────────────────────────────────────
    def split(name, mask_lo, mask_hi):
        lo = df[mask_lo]
        hi = df[mask_hi]
        print(f"  {name}:")
        for label, sub in [("LO", lo), ("HI", hi)]:
            if sub.empty:
                print(f"    {label}: empty")
                continue
            print(f"    {label} n={len(sub):3d}  WR={sub['win'].mean():.1%}  PnL=${sub['pnl'].sum():+8.2f}  avg=${sub['pnl'].mean():+6.2f}")

    print("=== Per-feature splits ===")
    s = df["score"]
    split("score (<70 / >=70)", s < 70, s >= 70)
    split("score (<75 / >=75)", s < 75, s >= 75)

    rwb = df["rej_wick_to_body"]
    split("rej_wick_to_body (<3 / >=3)", rwb < 3, rwb >= 3)
    split("rej_wick_to_body (<4 / >=4)", rwb < 4, rwb >= 4)

    rsa = df["rej_size_atr"]
    split("rej_size_atr (<0.6 / >=0.6)", rsa < 0.6, rsa >= 0.6)
    split("rej_size_atr (<1.0 / >=1.0)", rsa < 1.0, rsa >= 1.0)

    kra = df["kz_range_atr"]
    split("kz_range_atr (<1 / >=1)", kra < 1.0, kra >= 1.0)
    split("kz_range_atr (1-3 / not)", (kra >= 1.0) & (kra <= 3.0), (kra < 1.0) | (kra > 3.0))

    ema = df["ema_distance_pct"].abs()
    split("|ema_distance_pct| (<0.5 / >=0.5)", ema < 0.5, ema >= 0.5)

    bsr = df["bars_since_rejection"]
    split("bars_since_rejection (<2h / >=2h)", bsr < 2, bsr >= 2)
    split("bars_since_rejection (<4h / >=4h)", bsr < 4, bsr >= 4)
    split("bars_since_rejection (<8h / >=8h)", bsr < 8, bsr >= 8)
    print()

    print("=== Detailed bars_since_rejection buckets ===")
    for lo, hi in [(0, 2), (2, 4), (4, 8), (8, 16), (16, 100)]:
        sub = df[(bsr >= lo) & (bsr < hi)]
        if not sub.empty:
            print(f"  {lo}-{hi}h: n={len(sub):2d}  WR={sub['win'].mean():.1%}  PnL=${sub['pnl'].sum():+.2f}  avg=${sub['pnl'].mean():+.2f}")
    print()

    print("=== Per KZ ===")
    for kz_name, sub in df.groupby("kz_name"):
        if not kz_name:
            continue
        print(f"  {kz_name:<12} n={len(sub):3d}  WR={sub['win'].mean():.1%}  PnL=${sub['pnl'].sum():+.2f}")
    print()

    # ── Hour bucket ───────────────────────────────────────────────────────
    print("=== Per entry hour (UTC) ===")
    hr_groups = df.groupby("hour")
    for h, sub in hr_groups:
        if h is None:
            continue
        print(f"  {h:02d}: n={len(sub):2d}  WR={sub['win'].mean():.1%}  PnL=${sub['pnl'].sum():+.2f}")
    print()

    # Save full enriched table for follow-up
    df.to_csv("/tmp/kz_hunt_live_enriched.csv", index=False)
    print(f"Saved /tmp/kz_hunt_live_enriched.csv")


if __name__ == "__main__":
    main()
