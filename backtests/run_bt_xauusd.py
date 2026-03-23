"""10-year HVF backtest on XAUUSD (Gold). Runs on VPS."""
import os, sys, traceback
sys.path.insert(0, "C:/")
os.chdir("C:/hvf_trader")

try:
    from dotenv import load_dotenv
    load_dotenv("C:/hvf_trader/.env")

    import logging
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    logger = logging.getLogger("bt_xauusd")

    import MetaTrader5 as mt5
    import pandas as pd
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np
    from collections import defaultdict

    from hvf_trader import config
    from hvf_trader.data.data_fetcher import add_indicators
    from hvf_trader.backtesting.backtest_engine import BacktestEngine

    path = os.getenv("MT5_PATH")
    if not mt5.initialize(path=path):
        raise RuntimeError("MT5 init failed")
    if not mt5.login(int(os.getenv("MT5_LOGIN")), password=os.getenv("MT5_PASSWORD"),
                     server=os.getenv("MT5_SERVER")):
        raise RuntimeError("MT5 login failed")

    SYMBOL = "XAUUSD"
    PATTERNS = ["HVF"]  # Only testing HVF on gold
    EQUITY = 700.0
    H1_BARS = 70000
    H4_BARS = 18000

    # Ensure pip value is set
    config.PIP_VALUES[SYMBOL] = 0.01

    logger.info("=" * 80)
    logger.info(f"XAUUSD HVF BACKTEST")
    logger.info(f"  PIP_VALUE: {config.PIP_VALUES[SYMBOL]}")
    logger.info(f"  MIN_RRR: {config.MIN_RRR_BY_PATTERN.get('HVF', config.HVF_MIN_RRR)}")
    logger.info(f"  RISK_PCT: {config.RISK_PCT_BY_PATTERN.get('HVF', config.RISK_PCT)}")
    logger.info(f"  PARTIAL_CLOSE: {config.PARTIAL_CLOSE_PCT}")
    logger.info(f"  TRAILING_ATR_MULT: {config.TRAILING_STOP_ATR_MULT_BY_PATTERN.get('HVF', config.TRAILING_STOP_ATR_MULT)}")
    logger.info(f"  SCORE_THRESHOLD: {config.SCORE_THRESHOLD_BY_PATTERN.get('HVF', config.SCORE_THRESHOLD)}")
    logger.info(f"  ZIGZAG_ATR_MULT: {config.ZIGZAG_ATR_MULTIPLIER}")
    logger.info("=" * 80)

    # Fetch data
    r1 = mt5.copy_rates_from_pos(SYMBOL, mt5.TIMEFRAME_H1, 0, H1_BARS)
    r4 = mt5.copy_rates_from_pos(SYMBOL, mt5.TIMEFRAME_H4, 0, H4_BARS)
    r_d1 = mt5.copy_rates_from_pos(SYMBOL, mt5.TIMEFRAME_D1, 0, 3650)
    mt5.shutdown()

    if r1 is None or r4 is None:
        raise RuntimeError(f"No data for {SYMBOL}")

    d1 = pd.DataFrame(r1); d1["time"] = pd.to_datetime(d1["time"], unit="s", utc=True)
    d4 = pd.DataFrame(r4); d4["time"] = pd.to_datetime(d4["time"], unit="s", utc=True)
    d1 = add_indicators(d1); d4 = add_indicators(d4)
    d1 = d1.dropna(subset=["atr", "ema_200", "adx"]).reset_index(drop=True)

    years = (d1["time"].iloc[-1] - d1["time"].iloc[0]).days / 365.25
    logger.info(f"{SYMBOL}: {len(d1)} H1 bars, {len(d4)} H4 bars, "
                f"{d1['time'].iloc[0].date()} to {d1['time'].iloc[-1].date()} ({years:.1f} years)")

    # ATR stats for gold
    avg_atr = d1["atr"].mean()
    avg_close = d1["close"].mean()
    logger.info(f"  Avg ATR: ${avg_atr:.2f}, Avg Close: ${avg_close:.2f}")
    logger.info(f"  ATR as % of price: {avg_atr/avg_close*100:.3f}%")
    logger.info(f"  Zigzag threshold: {avg_atr/avg_close*100*config.ZIGZAG_ATR_MULTIPLIER:.3f}%")

    # Run backtest
    logger.info(f"\nRunning HVF backtest on {SYMBOL}...")
    eng = BacktestEngine(starting_equity=EQUITY, enabled_patterns=PATTERNS)
    res = eng.run(d1, SYMBOL, d4)

    # Results
    logger.info("=" * 80)
    logger.info(f"RESULTS: {SYMBOL} HVF")
    logger.info(f"  Total trades: {res.total_trades}")
    logger.info(f"  Win rate: {res.win_rate:.1f}%")
    logger.info(f"  Profit factor: {res.profit_factor:.2f}")
    logger.info(f"  Total pips: {res.total_pnl_pips:+.1f}")
    logger.info(f"  Total PnL: ${res.total_pnl_currency:+.2f}")
    logger.info(f"  Max drawdown: {res.max_drawdown_pct:.1f}%")
    logger.info(f"  Avg win: {res.avg_win_pips:.1f} pips")
    logger.info(f"  Avg loss: {res.avg_loss_pips:.1f} pips")

    if res.total_trades > 0:
        trades_per_year = res.total_trades / years if years > 0 else 0
        logger.info(f"  Trades/year: {trades_per_year:.1f}")

    # Direction breakdown
    longs = [t for t in res.trades if t.direction == "LONG"]
    shorts = [t for t in res.trades if t.direction == "SHORT"]
    for label, trades in [("LONG", longs), ("SHORT", shorts)]:
        n = len(trades)
        if n == 0:
            logger.info(f"  {label}: 0 trades")
            continue
        wins = [t for t in trades if t.pnl_pips > 0]
        total_pips = sum(t.pnl_pips for t in trades)
        wr = len(wins) / n * 100
        gross_w = sum(t.pnl_pips for t in wins)
        gross_l = abs(sum(t.pnl_pips for t in trades if t.pnl_pips <= 0))
        pf = gross_w / gross_l if gross_l > 0 else float("inf")
        logger.info(f"  {label}: {n}T, WR={wr:.0f}%, PF={pf:.2f}, {total_pips:+.1f}p")

    # Also test with KZ_HUNT
    logger.info("\n" + "=" * 80)
    logger.info(f"Running HVF+KZ_HUNT backtest on {SYMBOL}...")
    eng2 = BacktestEngine(starting_equity=EQUITY, enabled_patterns=["HVF", "KZ_HUNT"])
    res2 = eng2.run(d1, SYMBOL, d4)
    logger.info(f"RESULTS: {SYMBOL} HVF+KZ_HUNT")
    logger.info(f"  Total trades: {res2.total_trades}")
    logger.info(f"  Win rate: {res2.win_rate:.1f}%")
    logger.info(f"  Profit factor: {res2.profit_factor:.2f}")
    logger.info(f"  Total pips: {res2.total_pnl_pips:+.1f}")

    # Per-pattern breakdown for combined
    by_pat = defaultdict(list)
    for t in res2.trades:
        by_pat[t.pattern_type].append(t)
    for pat, trades in by_pat.items():
        n = len(trades)
        wins = [t for t in trades if t.pnl_pips > 0]
        total_pips = sum(t.pnl_pips for t in trades)
        wr = len(wins) / n * 100
        gross_w = sum(t.pnl_pips for t in wins)
        gross_l = abs(sum(t.pnl_pips for t in trades if t.pnl_pips <= 0))
        pf = gross_w / gross_l if gross_l > 0 else float("inf")
        logger.info(f"  {pat}: {n}T, WR={wr:.0f}%, PF={pf:.2f}, {total_pips:+.1f}p")

    # ─── Chart ─────────────────────────────────────────────────────────────
    if res.total_trades > 0:
        eq_vals = [EQUITY]
        eq_times = [res.trades[0].entry_time]
        for t in res.trades:
            eq_vals.append(eq_vals[-1] + t.pnl_currency)
            eq_times.append(t.exit_time if t.exit_time else t.entry_time)

        peak = np.maximum.accumulate(eq_vals)
        dd = (np.array(eq_vals) - peak) / peak * 100
        max_dd = abs(dd.min())
        final_eq = eq_vals[-1]
        ret_pct = (final_eq - EQUITY) / EQUITY * 100

        fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(16, 10),
                                        height_ratios=[3, 1], sharex=True)

        ax1.plot(eq_times, eq_vals, color="#FFD700", linewidth=1.5, label="XAUUSD HVF")
        ax1.fill_between(eq_times, EQUITY, eq_vals, alpha=0.15, color="#FFD700")
        ax1.axhline(y=EQUITY, color="gray", linestyle="--", alpha=0.3)

        # Trade dots
        req = EQUITY
        for t in res.trades:
            req += t.pnl_currency
            marker = "^" if t.pnl_pips > 0 else "v"
            color = "green" if t.pnl_pips > 0 else "red"
            ttime = t.exit_time if t.exit_time else t.entry_time
            ax1.scatter(ttime, req, color=color, marker=marker, s=15, alpha=0.5)

        pf_str = f"PF={res.profit_factor:.2f}" if res.profit_factor < 100 else "PF=inf"
        ax1.set_title(
            f"XAUUSD HVF 10-Year Backtest — ${EQUITY:.0f} -> ${final_eq:,.0f} ({ret_pct:+,.0f}%)\n"
            f"{res.total_trades}T, {res.total_pnl_pips:+,.0f}p, {pf_str}, "
            f"WR={res.win_rate:.0f}%, MaxDD={max_dd:.1f}%",
            fontsize=12, fontweight="bold",
        )
        ax1.set_ylabel("Equity ($)", fontsize=11)
        ax1.legend(fontsize=10)
        ax1.grid(True, alpha=0.2)

        ax2.fill_between(eq_times, dd, 0, color="red", alpha=0.25)
        ax2.plot(eq_times, dd, color="red", linewidth=0.5, alpha=0.6)
        ax2.set_ylabel("DD (%)", fontsize=10)
        ax2.set_title(f"Drawdown (max {max_dd:.1f}%)", fontsize=10)
        ax2.grid(True, alpha=0.2)
        ax2.set_ylim(top=1)

        plt.tight_layout()
        plt.savefig("C:/hvf_trader/bt_xauusd_hvf.png", dpi=150, bbox_inches="tight")
        plt.close()
        logger.info("Saved bt_xauusd_hvf.png")

    logger.info("DONE")

    with open("C:/hvf_trader/bt_xauusd_status.txt", "w") as f:
        f.write("COMPLETE\n")

except Exception:
    with open("C:/hvf_trader/bt_xauusd_error.txt", "w") as f:
        traceback.print_exc(file=f)
    traceback.print_exc()
