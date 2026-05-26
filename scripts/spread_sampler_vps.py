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

# All KZ_HUNT pairs + QL + NIGHT_TIDE + LB + ASB pairs the bot might trade
PAIRS = [
    "NZDUSD", "EURGBP", "EURJPY", "EURAUD",  # KZ_HUNT (disabled but historical)
    "EURCHF",                                  # Quantum London
    "AUDNZD", "AUDCAD", "NZDCAD",              # Night Tide
    "GBPUSD",                                  # London Breakout
    "GBPJPY",                                  # ASB
]
SAMPLE_INTERVAL_SEC = int(os.environ.get("SAMPLE_INTERVAL_SEC", "60"))

# Default 14 days = 336 hours; the spread_model.py code reads the result.
HOURS = float(os.environ.get("SAMPLER_HOURS", "336"))

# How many consecutive empty-tick batches before forcing an MT5 reconnect.
# Each batch = 60s, so 3 = 3 minutes of dead ticks before we react.
RECONNECT_AFTER_EMPTY_BATCHES = 3


def _pip_size(symbol: str) -> float:
    """Pip size for a symbol — JPY pairs are 3-digit, rest are 5-digit."""
    return 0.01 if "JPY" in symbol else 0.0001


def _connect_mt5() -> bool:
    """(Re)initialize and login. Returns True on success."""
    mt5.shutdown()  # clean slate; no-op if not connected
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
    for sym in PAIRS:
        mt5.symbol_select(sym, True)
    return True


def main():
    if not _connect_mt5():
        sys.exit(1)

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

    last_status_hour = None
    samples_this_hour = 0
    empty_ticks_streak = 0
    rows_written_total = 0
    while True:
        now = datetime.now(timezone.utc)
        if now >= deadline:
            print(f"Deadline reached @ {now.isoformat()}, exiting.", flush=True)
            break

        rows = []
        none_pairs = []
        for sym in PAIRS:
            tick = mt5.symbol_info_tick(sym)
            if tick is None or (tick.bid <= 0 and tick.ask <= 0):
                none_pairs.append(sym)
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

        # Detect MT5 stale-connection class: every pair returned None/0 for
        # 3 consecutive batches. Log loudly, then reconnect. This was the
        # silent-failure mode that cost us 8 days of data 2026-05-18 → 26.
        if not rows:
            empty_ticks_streak += 1
            print(
                f"{now.isoformat()} EMPTY batch (none_pairs={len(none_pairs)}) "
                f"streak={empty_ticks_streak}",
                flush=True,
            )
            if empty_ticks_streak >= RECONNECT_AFTER_EMPTY_BATCHES:
                print(
                    f"{now.isoformat()} Reconnecting MT5 after "
                    f"{empty_ticks_streak} empty batches...",
                    flush=True,
                )
                if _connect_mt5():
                    print(f"{now.isoformat()} MT5 reconnected.", flush=True)
                    empty_ticks_streak = 0
                else:
                    print(
                        f"{now.isoformat()} MT5 reconnect failed, "
                        f"will retry next batch.",
                        flush=True,
                    )
        else:
            empty_ticks_streak = 0
            try:
                with open(out_path, "a", newline="") as f:
                    w = csv.writer(f)
                    w.writerows(rows)
                    f.flush()
                    os.fsync(f.fileno())
                rows_written_total += len(rows)
            except Exception as e:
                print(
                    f"{now.isoformat()} CSV write failed: {e}",
                    flush=True,
                )
        samples_this_hour += 1

        if last_status_hour != now.hour:
            # Hourly heartbeat: report both attempts AND rows actually written
            print(
                f"{now.strftime('%Y-%m-%d %H:%M UTC')} status: "
                f"prev-hour attempts={samples_this_hour} "
                f"rows_total={rows_written_total}",
                flush=True,
            )
            last_status_hour = now.hour
            samples_this_hour = 0

        time.sleep(SAMPLE_INTERVAL_SEC)

    mt5.shutdown()
    print("Spread sampler done.", flush=True)


if __name__ == "__main__":
    main()
