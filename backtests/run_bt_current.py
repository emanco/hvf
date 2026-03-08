"""Full system backtest with current live config (V2 aggressive + HVF RRR=1.5).
Equity curve + per-pattern per-pair breakdown. Runs on VPS."""
import os, sys, traceback
sys.path.insert(0, "C:/")
os.chdir("C:/hvf_trader")

try:
    from dotenv import load_dotenv
    load_dotenv("C:/hvf_trader/.env")

    import logging
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    logger = logging.getLogger("bt_current")

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

    PAIRS = config.INSTRUMENTS  # ["EURUSD", "NZDUSD", "EURGBP", "USDCHF", "EURAUD"]
    PATTERNS = config.ENABLED_PATTERNS  # ["HVF", "VIPER", "KZ_HUNT"]
    EQUITY = 700.0
    BARS = 10000

    for p in PAIRS:
        if p not in config.PIP_VALUES:
            config.PIP_VALUES[p] = 0.0001

    # Fetch data
    data = {}
    for symbol in PAIRS:
        r1 = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_H1, 0, BARS)
        r4 = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_H4, 0, 2500)
        if r1 is None or r4 is None:
            logger.warning(f"Skipping {symbol}: no data")
            continue
        d1 = pd.DataFrame(r1); d1["time"] = pd.to_datetime(d1["time"], unit="s", utc=True)
        d4 = pd.DataFrame(r4); d4["time"] = pd.to_datetime(d4["time"], unit="s", utc=True)
        d1 = add_indicators(d1); d4 = add_indicators(d4)
        d1 = d1.dropna(subset=["atr", "ema_200", "adx"]).reset_index(drop=True)
        data[symbol] = (d1, d4)
        logger.info(f"{symbol}: {len(d1)} H1 bars, range {d1['time'].iloc[0].date()} to {d1['time'].iloc[-1].date()}")
    mt5.shutdown()

    # Run backtest per pair
    results = {}
    for symbol in PAIRS:
        if symbol not in data:
            continue
        d1, d4 = data[symbol]
        eng = BacktestEngine(starting_equity=EQUITY, enabled_patterns=PATTERNS)
        res = eng.run(d1, symbol, d4)
        results[symbol] = res

    # ─── Per-pattern per-pair breakdown ──────────────────────────────────────
    logger.info("=" * 90)
    logger.info("PER-PATTERN PER-PAIR BREAKDOWN")
    logger.info(f"{'Pair':<10} {'Pattern':<12} {'Trades':>7} {'WR':>6} {'PF':>7} {'Pips':>10} {'AvgW':>8} {'AvgL':>8}")
    logger.info("-" * 90)

    pair_totals = {}
    pattern_totals = defaultdict(lambda: {"trades": 0, "pips": 0.0, "wins": 0, "gross_win": 0.0, "gross_loss": 0.0})
    grand = {"trades": 0, "pips": 0.0, "wins": 0, "gross_win": 0.0, "gross_loss": 0.0}

    for symbol in PAIRS:
        if symbol not in results:
            continue
        res = results[symbol]

        # Group trades by pattern
        by_pattern = defaultdict(list)
        for t in res.trades:
            by_pattern[t.pattern_type].append(t)

        pair_t, pair_p = 0, 0.0
        for pat in PATTERNS:
            trades = by_pattern.get(pat, [])
            n = len(trades)
            if n == 0:
                logger.info(f"  {symbol:<10} {pat:<12} {'0':>7} {'—':>6} {'—':>7} {'—':>10} {'—':>8} {'—':>8}")
                continue

            wins = [t for t in trades if t.pnl_pips > 0]
            losses = [t for t in trades if t.pnl_pips <= 0]
            total_pips = sum(t.pnl_pips for t in trades)
            wr = len(wins) / n * 100
            gross_win = sum(t.pnl_pips for t in wins)
            gross_loss = abs(sum(t.pnl_pips for t in losses))
            pf = gross_win / gross_loss if gross_loss > 0 else float("inf")
            avg_w = gross_win / len(wins) if wins else 0
            avg_l = gross_loss / len(losses) if losses else 0

            pf_str = f"{pf:.2f}" if pf < 100 else "inf"
            logger.info(f"  {symbol:<10} {pat:<12} {n:>7} {wr:>5.0f}% {pf_str:>7} {total_pips:>+10.1f} {avg_w:>8.1f} {avg_l:>8.1f}")

            pair_t += n; pair_p += total_pips
            pattern_totals[pat]["trades"] += n
            pattern_totals[pat]["pips"] += total_pips
            pattern_totals[pat]["wins"] += len(wins)
            pattern_totals[pat]["gross_win"] += gross_win
            pattern_totals[pat]["gross_loss"] += gross_loss
            grand["trades"] += n; grand["pips"] += total_pips
            grand["wins"] += len(wins)
            grand["gross_win"] += gross_win; grand["gross_loss"] += gross_loss

        # Pair total
        pair_wr = res.win_rate
        pair_pf = f"{res.profit_factor:.2f}" if res.profit_factor < 100 else "inf"
        logger.info(f"  {symbol:<10} {'TOTAL':<12} {res.total_trades:>7} {pair_wr:>5.0f}% {pair_pf:>7} {res.total_pnl_pips:>+10.1f}")
        logger.info("")
        pair_totals[symbol] = res

    # Pattern totals
    logger.info("-" * 90)
    logger.info("PATTERN TOTALS")
    for pat in PATTERNS:
        pt = pattern_totals[pat]
        if pt["trades"] == 0:
            continue
        wr = pt["wins"] / pt["trades"] * 100
        pf = pt["gross_win"] / pt["gross_loss"] if pt["gross_loss"] > 0 else float("inf")
        pf_str = f"{pf:.2f}" if pf < 100 else "inf"
        logger.info(f"  {'ALL':<10} {pat:<12} {pt['trades']:>7} {wr:>5.0f}% {pf_str:>7} {pt['pips']:>+10.1f}")

    # Grand total
    logger.info("-" * 90)
    g_wr = grand["wins"] / grand["trades"] * 100 if grand["trades"] > 0 else 0
    g_pf = grand["gross_win"] / grand["gross_loss"] if grand["gross_loss"] > 0 else float("inf")
    g_pf_str = f"{g_pf:.2f}" if g_pf < 100 else "inf"
    logger.info(f"  {'ALL':<10} {'ALL':<12} {grand['trades']:>7} {g_wr:>5.0f}% {g_pf_str:>7} {grand['pips']:>+10.1f}")

    # ─── Equity curve: combined portfolio ────────────────────────────────────
    all_trades = []
    for sym, res in results.items():
        for t in res.trades:
            all_trades.append(t)
    all_trades.sort(key=lambda t: t.exit_time if t.exit_time else t.entry_time)

    eq = [EQUITY]
    times = [all_trades[0].entry_time if all_trades else pd.Timestamp.now(tz="UTC")]
    for t in all_trades:
        eq.append(eq[-1] + t.pnl_currency)
        times.append(t.exit_time if t.exit_time else t.entry_time)

    peak = np.maximum.accumulate(eq)
    dd = (np.array(eq) - peak) / peak * 100
    max_dd = abs(dd.min())

    final_eq = eq[-1]
    ret_pct = (final_eq - EQUITY) / EQUITY * 100

    logger.info("=" * 90)
    logger.info(f"PORTFOLIO: £{EQUITY:.0f} → £{final_eq:.0f} ({ret_pct:+.0f}%), MaxDD {max_dd:.1f}%, {grand['trades']}T, {grand['pips']:+.0f}p")

    # ─── Chart ───────────────────────────────────────────────────────────────
    fig, axes = plt.subplots(2, 1, figsize=(16, 10), gridspec_kw={"height_ratios": [3, 1]})

    # Top: equity curve coloured by pattern
    ax = axes[0]
    # Plot base equity line
    ax.plot(times, eq, color="steelblue", linewidth=1.8, alpha=0.9, zorder=2)
    ax.fill_between(times, EQUITY, eq, alpha=0.15, color="steelblue")
    ax.axhline(y=EQUITY, color="gray", linestyle="--", alpha=0.4)
    ax.axhline(y=1000, color="green", linestyle=":", alpha=0.3, label="£1,000")
    ax.axhline(y=1500, color="orange", linestyle=":", alpha=0.3, label="£1,500 (switch to V1)")

    # Mark trade dots by pattern
    pat_colors = {"HVF": "purple", "VIPER": "crimson", "KZ_HUNT": "teal"}
    running_eq = EQUITY
    for t in all_trades:
        running_eq += t.pnl_currency
        color = pat_colors.get(t.pattern_type, "gray")
        marker = "^" if t.pnl_pips > 0 else "v"
        ttime = t.exit_time if t.exit_time else t.entry_time
        ax.scatter(ttime, running_eq, color=color, marker=marker, s=18, alpha=0.6, zorder=3)

    # Legend for pattern dots
    for pat, col in pat_colors.items():
        pt = pattern_totals[pat]
        if pt["trades"] > 0:
            pf = pt["gross_win"] / pt["gross_loss"] if pt["gross_loss"] > 0 else float("inf")
            pf_str = f"PF={pf:.2f}" if pf < 100 else "PF=inf"
            ax.scatter([], [], color=col, s=40, label=f"{pat}: {pt['trades']}T, {pt['pips']:+.0f}p, {pf_str}")

    ax.set_title(f"Current Config — £{EQUITY:.0f} → £{final_eq:.0f} ({ret_pct:+.0f}%), "
                 f"{grand['trades']}T, {grand['pips']:+.0f}p, MaxDD {max_dd:.1f}%",
                 fontsize=13, fontweight="bold")
    ax.set_ylabel("Equity (£)")
    ax.legend(loc="upper left", fontsize=9)
    ax.grid(True, alpha=0.3)

    # Bottom: drawdown
    ax2 = axes[1]
    ax2.fill_between(times, dd, 0, color="red", alpha=0.3)
    ax2.plot(times, dd, color="red", linewidth=0.8, alpha=0.6)
    ax2.set_ylabel("Drawdown (%)")
    ax2.set_xlabel("Time")
    ax2.grid(True, alpha=0.3)
    ax2.set_title(f"Drawdown (max {max_dd:.1f}%)", fontsize=11)

    plt.tight_layout()
    fig.savefig("C:/hvf_trader/bt_current_equity.png", dpi=150)
    plt.close()
    logger.info("Saved bt_current_equity.png")

    # ─── Per-pair equity subplots ────────────────────────────────────────────
    n = len(PAIRS)
    fig2, axes2 = plt.subplots((n + 1) // 2, 2, figsize=(16, 4 * ((n + 1) // 2)))
    if n == 1:
        axes2 = np.array([[axes2]])
    elif (n + 1) // 2 == 1:
        axes2 = axes2.reshape(1, -1)

    for idx, symbol in enumerate(PAIRS):
        if symbol not in results:
            continue
        ax = axes2[idx // 2][idx % 2]
        res = results[symbol]
        if not res.trades:
            ax.set_title(f"{symbol}: 0 trades")
            continue

        # Build equity curve for this pair
        peq = [EQUITY]
        ptimes = [res.trades[0].entry_time]
        for t in res.trades:
            peq.append(peq[-1] + t.pnl_currency)
            ptimes.append(t.exit_time if t.exit_time else t.entry_time)

        ax.plot(ptimes, peq, color="steelblue", linewidth=1.3)
        ax.fill_between(ptimes, EQUITY, peq, alpha=0.1, color="steelblue")
        ax.axhline(y=EQUITY, color="gray", linestyle="--", alpha=0.4)

        # Pattern dots
        req = EQUITY
        for t in res.trades:
            req += t.pnl_currency
            color = pat_colors.get(t.pattern_type, "gray")
            marker = "^" if t.pnl_pips > 0 else "v"
            ttime = t.exit_time if t.exit_time else t.entry_time
            ax.scatter(ttime, req, color=color, marker=marker, s=15, alpha=0.5)

        pf_str = f"PF={res.profit_factor:.2f}" if res.profit_factor < 100 else "PF=inf"
        ax.set_title(f"{symbol}: {res.total_trades}T, {res.total_pnl_pips:+.0f}p, {pf_str}, WR={res.win_rate:.0f}%",
                     fontsize=11, fontweight="bold")
        ax.set_ylabel("Equity (£)")
        ax.grid(True, alpha=0.3)

    # Hide unused subplot
    if n % 2 == 1:
        axes2[n // 2][1].set_visible(False)

    fig2.suptitle("Per-Pair Equity — Current Config (HVF RRR≥1.5, Viper SHORT, KZ Hunt)",
                  fontsize=13, fontweight="bold")
    plt.tight_layout()
    fig2.savefig("C:/hvf_trader/bt_current_pairs.png", dpi=150)
    plt.close()
    logger.info("Saved bt_current_pairs.png")

    with open("C:/hvf_trader/bt_current_status.txt", "w") as f:
        f.write("COMPLETE\n")

except Exception:
    with open("C:/hvf_trader/bt_current_error.txt", "w") as f:
        traceback.print_exc(file=f)
