"""Debug wrapper to catch all crashes."""
import sys, os, traceback
sys.path.insert(0, "C:/")
os.chdir("C:/hvf_trader")

try:
    from dotenv import load_dotenv
    load_dotenv("C:/hvf_trader/.env")

    with open("C:/hvf_trader/trader_debug.txt", "w") as f:
        f.write("STARTING\n")
        f.flush()

    from hvf_trader.main import HVFTrader

    with open("C:/hvf_trader/trader_debug.txt", "a") as f:
        f.write("IMPORTED\n")
        f.flush()

    trader = HVFTrader()

    with open("C:/hvf_trader/trader_debug.txt", "a") as f:
        f.write("CREATED\n")
        f.flush()

    trader.start()

except Exception:
    with open("C:/hvf_trader/trader_debug.txt", "a") as f:
        f.write("CRASHED\n")
        traceback.print_exc(file=f)
    with open("C:/hvf_trader/trader_error.txt", "w") as f:
        traceback.print_exc(file=f)
