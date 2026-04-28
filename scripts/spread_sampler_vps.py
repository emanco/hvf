"""Sample live bid/ask spreads on cross pairs during quiet hours.

Runs on the VPS alongside the bot. Polls mt5.symbol_info_tick() every 10s
for each pair during 20:00-02:00 UTC (covers the BB+RSI strategy's 21:00-01:00
window with margin). Writes CSV with timestamp, bid, ask, spread_pips.

Usage on VPS (PowerShell):
    Start-Process C:\hvf_trader\venv\Scripts\python.exe \
        -ArgumentList "C:\hvf_trader\spread_sampler_vps.py" \
        -RedirectStandardOutput C:\hvf_trader\logs\spread_sampler.log \
        -NoNewWindow

Stops automatically after end_time (configurable via env var SAMPLER_HOURS).
"""
import csv
import os
import sys
import time
from datetime import datetime, timezone, timedelta

from dotenv import load_dotenv
load_dotenv(r"C:/hvf_trader/.env")
import MetaTrader5 as mt5

PAIRS = ["AUDNZD", "NZDCAD", "AUDCAD", "EURCHF"]
SAMPLE_INTERVAL_SEC = 10
WINDOW_START_HOUR = 20  # UTC — start a bit before 21:00 to catch ramp
WINDOW_END_HOUR = 2     # UTC — end a bit after 01:00

# Total runtime — quit after this many hours of wall clock to avoid running forever
HOURS = float(os.environ.get("SAMPLER_HOURS", "12"))

PIP = 0.0001  # all 4 pairs are 4-digit


def in_window(hour):
    if WINDOW_START_HOUR <= WINDOW_END_HOUR:
        return WINDOW_START_HOUR <= hour < WINDOW_END_HOUR
    return hour >= WINDOW_START_HOUR or hour < WINDOW_END_HOUR


def main():
    if not mt5.initialize(path=os.getenv("MT5_PATH")):
        print(f"MT5 init failed: {mt5.last_error()}", flush=True)
        sys.exit(1)
    if not mt5.login(int(os.getenv("MT5_LOGIN")),
                    password=os.getenv("MT5_PASSWORD"),
                    server=os.getenv("MT5_SERVER")):
        print(f"MT5 login failed: {mt5.last_error()}", flush=True)
        sys.exit(1)

    # Subscribe each pair to make sure ticks flow
    for sym in PAIRS:
        if not mt5.symbol_select(sym, True):
            print(f"WARN: symbol_select failed for {sym}", flush=True)
        else:
            print(f"  subscribed {sym}", flush=True)

    out_path = r"C:/hvf_trader/_export_m15/spread_samples.csv"
    os.makedirs(os.path.dirname(out_path), exist_ok=True)

    deadline = datetime.now(timezone.utc) + timedelta(hours=HOURS)
    print(f"Sampler started. Running until {deadline.isoformat()}", flush=True)
    print(f"Window: {WINDOW_START_HOUR:02d}:00-{WINDOW_END_HOUR:02d}:00 UTC", flush=True)
    print(f"Output: {out_path}", flush=True)

    # Open CSV in append mode so re-runs don't overwrite
    write_header = not os.path.exists(out_path)
    with open(out_path, "a", newline="") as f:
        w = csv.writer(f)
        if write_header:
            w.writerow(["timestamp_utc", "symbol", "bid", "ask", "spread_pips"])

        last_status_hour = None
        samples_this_hour = 0
        while True:
            now = datetime.now(timezone.utc)
            if now >= deadline:
                print(f"Reached deadline at {now.isoformat()}, exiting.", flush=True)
                break

            if in_window(now.hour):
                for sym in PAIRS:
                    tick = mt5.symbol_info_tick(sym)
                    if tick is None:
                        continue
                    spread_pips = (tick.ask - tick.bid) / PIP
                    w.writerow([
                        now.isoformat(timespec="seconds"),
                        sym,
                        f"{tick.bid:.5f}",
                        f"{tick.ask:.5f}",
                        f"{spread_pips:.2f}",
                    ])
                f.flush()
                samples_this_hour += 1

                # Hourly status print
                if last_status_hour != now.hour:
                    print(f"{now.strftime('%H:%M UTC')}  in window  samples this hour: {samples_this_hour}", flush=True)
                    last_status_hour = now.hour
                    samples_this_hour = 0
            else:
                if last_status_hour != now.hour:
                    print(f"{now.strftime('%H:%M UTC')}  outside window — sleeping", flush=True)
                    last_status_hour = now.hour

            time.sleep(SAMPLE_INTERVAL_SEC)

    mt5.shutdown()
    print("Sampler done.", flush=True)


if __name__ == "__main__":
    main()
