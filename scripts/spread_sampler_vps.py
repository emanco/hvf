"""Sample live bid/ask spreads on all bot pairs, 24/7, for 14 days.

Feeds the hardened-harness spread_model.py with real broker spread data
instead of my hard-coded estimates. After ~2 weeks of samples, aggregate
to per-(symbol, hour_utc) median + p95 and save to backtests/data/spreads.csv.

Runs on the VPS alongside the bot. Independent MT5 connection.

Usage on VPS (PowerShell):
    Start-Process C:\\hvf_trader\\venv\\Scripts\\python.exe `
        -ArgumentList "C:\\hvf_trader\\spread_sampler_vps.py" `
        -RedirectStandardOutput C:\\hvf_trader\\logs\\spread_sampler.log `
        -RedirectStandardError C:\\hvf_trader\\logs\\spread_sampler_err.log `
        -WindowStyle Hidden

Configurable via env vars:
    SAMPLER_HOURS  (default 336 = 14 days)
    SAMPLE_INTERVAL_SEC (default 60)
"""
import csv
import os
import sys
import time
from datetime import datetime, timezone, timedelta

from dotenv import load_dotenv
load_dotenv(r"C:/hvf_trader/.env")
import MetaTrader5 as mt5

# All KZ_HUNT pairs + QL + NIGHT_TIDE + LB pairs the bot might trade
PAIRS = [
    # KZ_HUNT (recently disabled but back on)
    "NZDUSD", "EURGBP", "EURJPY", "EURAUD",
    # Quantum London
    "EURCHF",
    # Night Tide cross pairs
    "AUDNZD", "AUDCAD", "NZDCAD",
    # London Breakout
    "GBPUSD",
]
SAMPLE_INTERVAL_SEC = int(os.environ.get("SAMPLE_INTERVAL_SEC", "60"))

# Default 14 days = 336 hours; the spread_model.py code reads the result.
HOURS = float(os.environ.get("SAMPLER_HOURS", "336"))


def _pip_size(symbol: str) -> float:
    """Pip size for a symbol — JPY pairs are 3-digit, rest are 5-digit."""
    return 0.01 if "JPY" in symbol else 0.0001


def main():
    if not mt5.initialize(path=os.getenv("MT5_PATH")):
        print(f"MT5 init failed: {mt5.last_error()}", flush=True)
        sys.exit(1)
    if not mt5.login(int(os.getenv("MT5_LOGIN")),
                    password=os.getenv("MT5_PASSWORD"),
                    server=os.getenv("MT5_SERVER")):
        print(f"MT5 login failed: {mt5.last_error()}", flush=True)
        sys.exit(1)

    for sym in PAIRS:
        if not mt5.symbol_select(sym, True):
            print(f"WARN: symbol_select failed for {sym}", flush=True)
        else:
            print(f"  subscribed {sym}", flush=True)

    out_path = r"C:/hvf_trader/logs/spread_samples.csv"
    os.makedirs(os.path.dirname(out_path), exist_ok=True)

    deadline = datetime.now(timezone.utc) + timedelta(hours=HOURS)
    print(
        f"Spread sampler started "
        f"@ {datetime.now(timezone.utc).isoformat(timespec='seconds')}",
        flush=True,
    )
    print(f"  Pairs: {PAIRS}", flush=True)
    print(f"  Interval: {SAMPLE_INTERVAL_SEC}s", flush=True)
    print(f"  Deadline: {deadline.isoformat()}", flush=True)
    print(f"  Output: {out_path}", flush=True)

    # Write header once if needed
    if not os.path.exists(out_path):
        with open(out_path, "w", newline="") as f:
            csv.writer(f).writerow(
                ["timestamp_utc", "symbol", "bid", "ask", "spread_pips"]
            )

    # Open-and-close per batch — Windows file-handle / AV / fs-cache quirks
    # caused the long-lived handle pattern to silently lose writes after
    # ~2h. Per-batch open is slower but durable; 1 second of overhead is
    # nothing compared to the 60s sample interval.
    last_status_hour = None
    samples_this_hour = 0
    while True:
        now = datetime.now(timezone.utc)
        if now >= deadline:
            print(
                f"Deadline reached @ {now.isoformat()}, exiting.",
                flush=True,
            )
            break

        rows = []
        for sym in PAIRS:
            tick = mt5.symbol_info_tick(sym)
            if tick is None:
                continue
            pip = _pip_size(sym)
            spread_pips = (tick.ask - tick.bid) / pip
            rows.append([
                now.isoformat(timespec="seconds"),
                sym,
                f"{tick.bid:.5f}",
                f"{tick.ask:.5f}",
                f"{spread_pips:.2f}",
            ])
        if rows:
            try:
                with open(out_path, "a", newline="") as f:
                    w = csv.writer(f)
                    w.writerows(rows)
                    f.flush()
                    os.fsync(f.fileno())
            except Exception as e:
                print(
                    f"{now.isoformat()} CSV write failed: {e}",
                    flush=True,
                )
        samples_this_hour += 1

        if last_status_hour != now.hour:
            print(
                f"{now.strftime('%Y-%m-%d %H:%M UTC')} status: "
                f"prev hour samples per pair={samples_this_hour}",
                flush=True,
            )
            last_status_hour = now.hour
            samples_this_hour = 0

        time.sleep(SAMPLE_INTERVAL_SEC)

    mt5.shutdown()
    print("Spread sampler done.", flush=True)


if __name__ == "__main__":
    main()
