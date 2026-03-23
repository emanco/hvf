"""Walk-forward validation of current live config. All 5 pairs, HVF+KZ_HUNT. Runs on VPS."""
import os, sys, traceback
sys.path.insert(0, "C:/")
os.chdir("C:/hvf_trader")

try:
    from dotenv import load_dotenv
    load_dotenv("C:/hvf_trader/.env")

    import logging
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    logger = logging.getLogger("bt_wf")

    import MetaTrader5 as mt5
    import pandas as pd
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np
    from collections import defaultdict

    from hvf_trader import config
    from hvf_trader.data.data_fetcher import add_indicators
    from hvf_trader.backtesting.walk_forward import run_walk_forward

    path = os.getenv("MT5_PATH")
    if not mt5.initialize(path=path):
        raise RuntimeError("MT5 init failed")
    if not mt5.login(int(os.getenv("MT5_LOGIN")), password=os.getenv("MT5_PASSWORD"),
                     server=os.getenv("MT5_SERVER")):
        raise RuntimeError("MT5 login failed")

    PAIRS = config.INSTRUMENTS
    PATTERNS = config.ENABLED_PATTERNS
    EQUITY = 700.0
    H1_BARS = 70000
    H4_BARS = 18000
    TRAIN_MONTHS = 12   # 12-month train (more data = more stable parameters)
    TEST_MONTHS = 3     # 3-month test (quarterly out-of-sample)
    STEP_MONTHS = 3     # Slide by 3 months (non-overlapping OOS windows)

    logger.info("=" * 90)
    logger.info("WALK-FORWARD VALIDATION — LIVE CONFIG")
    logger.info(f"  Train: {TRAIN_MONTHS}m, Test: {TEST_MONTHS}m, Step: {STEP_MONTHS}m")
    logger.info(f"  Patterns: {PATTERNS}")
    logger.info(f"  Pairs: {PAIRS}")
    logger.info(f"  Exclusions: {dict(config.PATTERN_SYMBOL_EXCLUSIONS)}")
    logger.info(f"  Starting equity: ${EQUITY}")
    logger.info("=" * 90)

    # Fetch data
    data = {}
    for symbol in PAIRS:
        r1 = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_H1, 0, H1_BARS)
        r4 = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_H4, 0, H4_BARS)
        if r1 is None or r4 is None:
            logger.warning(f"Skipping {symbol}: no data")
            continue
        d1 = pd.DataFrame(r1); d1["time"] = pd.to_datetime(d1["time"], unit="s", utc=True)
        d4 = pd.DataFrame(r4); d4["time"] = pd.to_datetime(d4["time"], unit="s", utc=True)
        d1 = add_indicators(d1); d4 = add_indicators(d4)
        d1 = d1.dropna(subset=["atr", "ema_200", "adx"]).reset_index(drop=True)
        years = (d1["time"].iloc[-1] - d1["time"].iloc[0]).days / 365.25
        logger.info(f"{symbol}: {len(d1)} H1 bars ({years:.1f} years)")
        data[symbol] = (d1, d4)
    mt5.shutdown()

    # Run walk-forward per pair
    wf_results = {}
    for symbol in PAIRS:
        if symbol not in data:
            continue
        d1, d4 = data[symbol]
        logger.info(f"\n{'='*60}")
        logger.info(f"  WALK-FORWARD: {symbol}")
        logger.info(f"{'='*60}")
        wf = run_walk_forward(
            df_1h=d1, symbol=symbol, df_4h=d4,
            train_months=TRAIN_MONTHS, test_months=TEST_MONTHS,
            starting_equity=EQUITY, step_months=STEP_MONTHS,
            enabled_patterns=PATTERNS,
        )
        wf_results[symbol] = wf
        logger.info(f"\n{wf.summary()}")

    # ─── Aggregate all OOS trades across all pairs ────────────────────────
    logger.info("\n" + "=" * 90)
    logger.info("COMBINED WALK-FORWARD RESULTS (ALL PAIRS)")
    logger.info("=" * 90)

    all_oos_trades = []
    for symbol, wf in wf_results.items():
        for w in wf.windows:
            if w.test_result:
                for t in w.test_result.trades:
                    all_oos_trades.append(t)

    if all_oos_trades:
        total = len(all_oos_trades)
        winners = [t for t in all_oos_trades if t.pnl_pips > 0]
        losers = [t for t in all_oos_trades if t.pnl_pips <= 0]
        wr = len(winners) / total * 100
        gross_w = sum(t.pnl_pips for t in winners)
        gross_l = abs(sum(t.pnl_pips for t in losers))
        pf = gross_w / gross_l if gross_l > 0 else float("inf")
        total_pips = sum(t.pnl_pips for t in all_oos_trades)

        logger.info(f"  Total OOS trades: {total}")
        logger.info(f"  OOS Win Rate: {wr:.1f}%")
        logger.info(f"  OOS Profit Factor: {pf:.2f}")
        logger.info(f"  OOS Total Pips: {total_pips:+.1f}")

        # Per-pattern breakdown
        by_pat = defaultdict(list)
        for t in all_oos_trades:
            by_pat[t.pattern_type].append(t)

        logger.info(f"\n  {'Pattern':<12} {'Trades':>7} {'WR':>6} {'PF':>7} {'Pips':>10}")
        logger.info(f"  {'-'*48}")
        for pat in PATTERNS:
            trades = by_pat.get(pat, [])
            n = len(trades)
            if n == 0:
                logger.info(f"  {pat:<12} {'0':>7}")
                continue
            w = [t for t in trades if t.pnl_pips > 0]
            gw = sum(t.pnl_pips for t in w)
            gl = abs(sum(t.pnl_pips for t in trades if t.pnl_pips <= 0))
            p = gw / gl if gl > 0 else float("inf")
            tp = sum(t.pnl_pips for t in trades)
            pf_s = f"{p:.2f}" if p < 100 else "inf"
            logger.info(f"  {pat:<12} {n:>7} {len(w)/n*100:>5.0f}% {pf_s:>7} {tp:>+10.1f}")

        # Per-pair breakdown
        by_pair = defaultdict(list)
        for t in all_oos_trades:
            by_pair[t.symbol].append(t)

        logger.info(f"\n  {'Pair':<10} {'Trades':>7} {'WR':>6} {'PF':>7} {'Pips':>10} {'Windows':>10}")
        logger.info(f"  {'-'*56}")
        for sym in PAIRS:
            trades = by_pair.get(sym, [])
            n = len(trades)
            wf = wf_results.get(sym)
            n_win = wf.oos_positive_windows if wf else 0
            n_total = len(wf.windows) if wf else 0
            if n == 0:
                logger.info(f"  {sym:<10} {'0':>7} {'':>6} {'':>7} {'':>10} {n_win}/{n_total}")
                continue
            w = [t for t in trades if t.pnl_pips > 0]
            gw = sum(t.pnl_pips for t in w)
            gl = abs(sum(t.pnl_pips for t in trades if t.pnl_pips <= 0))
            p = gw / gl if gl > 0 else float("inf")
            tp = sum(t.pnl_pips for t in trades)
            pf_s = f"{p:.2f}" if p < 100 else "inf"
            logger.info(f"  {sym:<10} {n:>7} {len(w)/n*100:>5.0f}% {pf_s:>7} {tp:>+10.1f} {n_win}/{n_total}")

    # ─── Stability metrics ────────────────────────────────────────────────
    logger.info(f"\n  STABILITY METRICS:")
    total_windows = 0
    positive_windows = 0
    for sym, wf in wf_results.items():
        for w in wf.windows:
            if w.test_result and w.test_result.total_trades > 0:
                total_windows += 1
                if w.test_result.total_pnl_pips > 0:
                    positive_windows += 1

    if total_windows > 0:
        logger.info(f"  Positive OOS windows: {positive_windows}/{total_windows} "
                    f"({positive_windows/total_windows*100:.0f}%)")
        logger.info(f"  (>50% = strategy is stable, >60% = robust)")

    # ─── Chart: OOS equity per window ─────────────────────────────────────
    # Build OOS equity curve from all trades sorted by time
    all_oos_trades.sort(key=lambda t: t.exit_time if t.exit_time else t.entry_time)
    if all_oos_trades:
        eq = [EQUITY]
        times = [all_oos_trades[0].entry_time]
        for t in all_oos_trades:
            eq.append(eq[-1] + t.pnl_currency)
            times.append(t.exit_time if t.exit_time else t.entry_time)

        peak = np.maximum.accumulate(eq)
        dd = (np.array(eq) - peak) / peak * 100
        max_dd = abs(dd.min())
        final_eq = eq[-1]
        ret_pct = (final_eq - EQUITY) / EQUITY * 100

        fig, axes = plt.subplots(3, 1, figsize=(18, 14), height_ratios=[3, 1, 3],
                                  gridspec_kw={"hspace": 0.35})

        # Top: Combined OOS equity
        ax1 = axes[0]
        ax1.plot(times, eq, color="steelblue", linewidth=1.5)
        ax1.fill_between(times, EQUITY, eq, alpha=0.1, color="steelblue")
        ax1.axhline(y=EQUITY, color="gray", linestyle="--", alpha=0.3)

        pf_str = f"PF={pf:.2f}" if pf < 100 else "PF=inf"
        ax1.set_title(
            f"Walk-Forward OOS Equity — ${EQUITY:.0f} -> ${final_eq:,.0f} ({ret_pct:+,.0f}%)\n"
            f"{total} OOS trades, {total_pips:+,.0f}p, {pf_str}, WR={wr:.0f}%, MaxDD={max_dd:.1f}%\n"
            f"Train={TRAIN_MONTHS}m / Test={TEST_MONTHS}m / Step={STEP_MONTHS}m | "
            f"Positive windows: {positive_windows}/{total_windows}",
            fontsize=12, fontweight="bold", linespacing=1.4,
        )
        ax1.set_ylabel("Equity ($)", fontsize=11)
        ax1.grid(True, alpha=0.2)

        # Middle: Drawdown
        ax2 = axes[1]
        ax2.fill_between(times, dd, 0, color="red", alpha=0.25)
        ax2.plot(times, dd, color="red", linewidth=0.5, alpha=0.6)
        ax2.set_ylabel("DD (%)", fontsize=10)
        ax2.grid(True, alpha=0.2)
        ax2.set_ylim(top=1)

        # Bottom: Per-pair OOS equity curves
        ax3 = axes[2]
        pair_colors = {
            "EURUSD": "#2196F3", "NZDUSD": "#4CAF50", "EURGBP": "#FF9800",
            "USDCHF": "#9C27B0", "EURAUD": "#F44336",
        }
        for sym in PAIRS:
            trades = sorted(by_pair.get(sym, []),
                          key=lambda t: t.exit_time if t.exit_time else t.entry_time)
            if not trades:
                continue
            peq = [EQUITY]
            ptimes = [trades[0].entry_time]
            for t in trades:
                peq.append(peq[-1] + t.pnl_currency)
                ptimes.append(t.exit_time if t.exit_time else t.entry_time)
            col = pair_colors.get(sym, "gray")
            wf = wf_results.get(sym)
            n_w = wf.oos_positive_windows if wf else 0
            n_t = len(wf.windows) if wf else 0
            tp = sum(t.pnl_pips for t in trades)
            ax3.plot(ptimes, peq, color=col, linewidth=1.0,
                    label=f"{sym}: {len(trades)}T, {tp:+,.0f}p, {n_w}/{n_t} windows")

        ax3.axhline(y=EQUITY, color="gray", linestyle="--", alpha=0.3)
        ax3.set_title("Per-Pair OOS Equity", fontsize=11, fontweight="bold")
        ax3.set_ylabel("Equity ($)", fontsize=10)
        ax3.legend(fontsize=9)
        ax3.grid(True, alpha=0.2)

        plt.savefig("C:/hvf_trader/bt_walkforward.png", dpi=150, bbox_inches="tight")
        plt.close()
        logger.info("\nSaved bt_walkforward.png")

    logger.info("\nDONE")

    with open("C:/hvf_trader/bt_walkforward_status.txt", "w") as f:
        f.write("COMPLETE\n")

except Exception:
    with open("C:/hvf_trader/bt_walkforward_error.txt", "w") as f:
        traceback.print_exc(file=f)
    traceback.print_exc()
