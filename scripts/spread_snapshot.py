"""On-demand spread snapshot.

Replaces the 24/7 spread_sampler_vps.py service (decommissioned 2026-06-01
after it kept dying silently across bot deploys and we used the data only
once anyway).

Run this when you actually need fresh spread data — e.g. to evaluate whether
NIGHT_TIDE is spread-eaten during its 22-01 UTC window, or to refresh the
backtest harness's per-(symbol, hour) estimates.

Usage on VPS (or via SSH from Mac):
    # Capture 60 minutes of all pairs, print summary per pair
    C:\\hvf_trader\\venv\\Scripts\\python.exe C:\\hvf_trader\\scripts\\spread_snapshot.py

    # Capture 3 hours of just the NIGHT_TIDE crosses
    C:\\hvf_trader\\venv\\Scripts\\python.exe C:\\hvf_trader\\scripts\\spread_snapshot.py \\
        --minutes 180 --pairs AUDNZD AUDCAD NZDCAD

    # Save raw samples to CSV for downstream analysis
    C:\\hvf_trader\\venv\\Scripts\\python.exe C:\\hvf_trader\\scripts\\spread_snapshot.py \\
        --minutes 60 --csv C:/hvf_trader/logs/spread_snapshot.csv

Output:
    Per-pair: N, mean, median, p95, max spread in pips over the window.
    Optional CSV with raw tick-by-tick samples.
"""
from __future__ import annotations
import argparse
import csv
import os
import statistics
import sys
import time
from datetime import datetime, timezone, timedelta

import MetaTrader5 as mt5
from dotenv import load_dotenv

DEFAULT_PAIRS = [
    "NZDUSD", "EURGBP", "EURJPY", "EURAUD",
    "EURCHF",
    "AUDNZD", "AUDCAD", "NZDCAD",
    "GBPUSD", "GBPJPY",
]


def _pip(symbol: str) -> float:
    return 0.01 if "JPY" in symbol else 0.0001


def _connect() -> bool:
    """Init MT5 + login. Returns True on success."""
    load_dotenv(r"C:/hvf_trader/.env")
    mt5.shutdown()  # clean slate (no-op if not connected)
    if not mt5.initialize(path=os.getenv("MT5_PATH")):
        print(f"MT5 init failed: {mt5.last_error()}", flush=True)
        return False
    if not mt5.login(
        int(os.getenv("MT5_LOGIN")),
        password=os.getenv("MT5_PASSWORD"),
        server=os.getenv("MT5_SERVER"),
    ):
        print(f"MT5 login failed: {mt5.last_error()}", flush=True)
        return False
    return True


def sample(pairs: list[str], minutes: int, interval_sec: int, csv_path: str | None) -> dict[str, list[float]]:
    """Capture spread samples for `minutes` minutes. Returns {symbol: [spread_pips...]}."""
    if not _connect():
        sys.exit(1)
    for sym in pairs:
        if not mt5.symbol_select(sym, True):
            print(f"WARN: symbol_select failed for {sym}", flush=True)

    deadline = datetime.now(timezone.utc) + timedelta(minutes=minutes)
    print(f"Sampling {len(pairs)} pairs for {minutes} min @ {interval_sec}s interval...", flush=True)
    print(f"  Deadline: {deadline.isoformat()}", flush=True)

    samples: dict[str, list[float]] = {sym: [] for sym in pairs}
    empty_streak = 0
    if csv_path:
        f_csv = open(csv_path, "w", newline="")
        w = csv.writer(f_csv)
        w.writerow(["timestamp_utc", "symbol", "bid", "ask", "spread_pips"])
    else:
        f_csv = None
        w = None

    try:
        while True:
            now = datetime.now(timezone.utc)
            if now >= deadline:
                break
            rows_this_batch = 0
            for sym in pairs:
                try:
                    tick = mt5.symbol_info_tick(sym)
                except Exception as e:
                    print(f"{now.isoformat()} tick error for {sym}: {e}", flush=True)
                    continue
                if tick is None or (tick.bid <= 0 and tick.ask <= 0):
                    continue
                pip = _pip(sym)
                sp = (tick.ask - tick.bid) / pip
                samples[sym].append(sp)
                rows_this_batch += 1
                if w is not None:
                    w.writerow([
                        now.isoformat(timespec="seconds"),
                        sym, f"{tick.bid:.5f}", f"{tick.ask:.5f}", f"{sp:.2f}",
                    ])

            if rows_this_batch == 0:
                empty_streak += 1
                if empty_streak >= 3:
                    print(f"{now.isoformat()} stale ticks; reconnecting...", flush=True)
                    if _connect():
                        for sym in pairs:
                            mt5.symbol_select(sym, True)
                        empty_streak = 0
            else:
                empty_streak = 0

            if w is not None:
                f_csv.flush()
                os.fsync(f_csv.fileno())
            time.sleep(interval_sec)
    finally:
        if f_csv is not None:
            f_csv.close()
        mt5.shutdown()
    return samples


def summarize(samples: dict[str, list[float]]) -> None:
    print()
    print("=" * 70)
    print(f"{'Pair':<8} {'N':>5} {'mean':>6} {'p50':>6} {'p95':>6} {'max':>6}")
    print("-" * 70)
    for sym, sps in sorted(samples.items()):
        if not sps:
            print(f"{sym:<8} no data")
            continue
        n = len(sps)
        mean = statistics.mean(sps)
        p50 = statistics.median(sps)
        p95 = sorted(sps)[int(n * 0.95)] if n >= 20 else max(sps)
        mx = max(sps)
        print(f"{sym:<8} {n:>5} {mean:>6.2f} {p50:>6.2f} {p95:>6.2f} {mx:>6.2f}")


def main():
    p = argparse.ArgumentParser(description="On-demand spread snapshot")
    p.add_argument("--minutes", type=int, default=60, help="capture duration (default 60)")
    p.add_argument("--interval-sec", type=int, default=15, help="sample interval (default 15s)")
    p.add_argument("--pairs", nargs="+", default=DEFAULT_PAIRS, help="pairs to sample")
    p.add_argument("--csv", default=None, help="optional CSV path for raw samples")
    args = p.parse_args()
    samples = sample(args.pairs, args.minutes, args.interval_sec, args.csv)
    summarize(samples)


if __name__ == "__main__":
    main()
