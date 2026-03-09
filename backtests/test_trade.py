"""Test trade: open 0.01 EURUSD, wait 10s, close. Validates execution pipeline."""
import os, sys, time, traceback
sys.path.insert(0, "C:/")
os.chdir("C:/hvf_trader")

try:
    from dotenv import load_dotenv
    load_dotenv("C:/hvf_trader/.env")

    import MetaTrader5 as mt5

    path = os.getenv("MT5_PATH")
    if not mt5.initialize(path=path):
        raise RuntimeError(f"MT5 init failed: {mt5.last_error()}")
    if not mt5.login(int(os.getenv("MT5_LOGIN")), password=os.getenv("MT5_PASSWORD"),
                     server=os.getenv("MT5_SERVER")):
        raise RuntimeError(f"MT5 login failed: {mt5.last_error()}")

    symbol = "EURUSD"
    lot = 0.01

    # Ensure symbol is visible
    if not mt5.symbol_select(symbol, True):
        raise RuntimeError(f"Failed to select {symbol}")

    tick = mt5.symbol_info_tick(symbol)
    if tick is None:
        raise RuntimeError(f"No tick data for {symbol}")

    print(f"Current {symbol}: bid={tick.bid}, ask={tick.ask}, spread={tick.ask - tick.bid:.5f}")

    # ─── OPEN: Buy 0.01 EURUSD ────────────────────────────────────────────
    sl = round(tick.bid - 0.0050, 5)  # 50 pip SL — wide, just safety net

    open_request = {
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": symbol,
        "volume": lot,
        "type": mt5.ORDER_TYPE_BUY,
        "price": tick.ask,
        "sl": sl,
        "tp": 0.0,
        "deviation": 20,
        "magic": 999999,
        "comment": "TEST_TRADE",
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_IOC,
    }

    print(f"\nOpening BUY {lot} {symbol} @ {tick.ask}, SL={sl}...")
    result = mt5.order_send(open_request)

    if result is None:
        raise RuntimeError(f"order_send returned None: {mt5.last_error()}")
    if result.retcode != mt5.TRADE_RETCODE_DONE:
        raise RuntimeError(f"Open failed: retcode={result.retcode}, comment={result.comment}")

    ticket = result.order
    fill_price = result.price
    print(f"OPENED: ticket={ticket}, fill={fill_price}, volume={result.volume}")

    # ─── WAIT ──────────────────────────────────────────────────────────────
    print("\nWaiting 10 seconds...")
    time.sleep(10)

    # ─── CLOSE ─────────────────────────────────────────────────────────────
    tick2 = mt5.symbol_info_tick(symbol)
    print(f"Current {symbol}: bid={tick2.bid}, ask={tick2.ask}")

    # Find the position to get current volume
    positions = mt5.positions_get(ticket=ticket)
    if not positions:
        print("Position already closed (SL hit?)")
    else:
        pos = positions[0]
        close_request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": symbol,
            "volume": pos.volume,
            "type": mt5.ORDER_TYPE_SELL,  # Opposite to close
            "position": pos.ticket,
            "price": tick2.bid,
            "deviation": 20,
            "magic": 999999,
            "comment": "TEST_CLOSE",
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_IOC,
        }

        print(f"Closing SELL {pos.volume} {symbol} @ {tick2.bid}...")
        close_result = mt5.order_send(close_request)

        if close_result is None:
            raise RuntimeError(f"Close order_send returned None: {mt5.last_error()}")
        if close_result.retcode != mt5.TRADE_RETCODE_DONE:
            raise RuntimeError(f"Close failed: retcode={close_result.retcode}, comment={close_result.comment}")

        close_price = close_result.price
        pnl_pips = (close_price - fill_price) / 0.0001
        print(f"CLOSED: fill={close_price}, PnL={pnl_pips:+.1f} pips")

    # ─── VERIFY ────────────────────────────────────────────────────────────
    remaining = mt5.positions_get(symbol=symbol, magic=999999)
    if remaining:
        print(f"\nWARNING: {len(remaining)} test position(s) still open!")
    else:
        print("\nAll clear — no test positions remaining.")

    mt5.shutdown()
    print("\nTEST COMPLETE")

except Exception:
    traceback.print_exc()
    try:
        mt5.shutdown()
    except:
        pass
