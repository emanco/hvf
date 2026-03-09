"""10-year backtest — current V3 config. Per-pair + combined equity with drawdown. Runs on VPS."""
import os, sys, traceback
sys.path.insert(0, "C:/")
os.chdir("C:/hvf_trader")

try:
    from dotenv import load_dotenv
    load_dotenv("C:/hvf_trader/.env")

    import logging
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    logger = logging.getLogger("bt_10yr_full")

    import MetaTrader5 as mt5
    import pandas as pd
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import matplotlib.dates as mdates
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
    PATTERNS = config.ENABLED_PATTERNS  # ["HVF", "KZ_HUNT"]
    EQUITY = 700.0
    H1_BARS = 70000   # ~10 years of H1 data
    H4_BARS = 18000   # ~10 years of H4 data
    CHART_DIR = "C:/hvf_trader/backtests/charts"
    os.makedirs(CHART_DIR, exist_ok=True)

    for p in PAIRS:
        if p not in config.PIP_VALUES:
            config.PIP_VALUES[p] = 0.0001

    # ─── Fetch data ────────────────────────────────────────────────────────────
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
        logger.info(f"{symbol}: {len(d1)} H1 bars, {len(d4)} H4 bars, "
                    f"{d1['time'].iloc[0].date()} to {d1['time'].iloc[-1].date()} ({years:.1f} years)")
        data[symbol] = (d1, d4)
    mt5.shutdown()

    # ─── Run backtest per pair ─────────────────────────────────────────────────
    results = {}
    for symbol in PAIRS:
        if symbol not in data:
            continue
        d1, d4 = data[symbol]
        logger.info(f"Running {symbol}...")
        eng = BacktestEngine(starting_equity=EQUITY, enabled_patterns=PATTERNS)
        res = eng.run(d1, symbol, d4)
        results[symbol] = res
        logger.info(f"  {symbol}: {res.total_trades}T, {res.total_pnl_pips:+.1f}p, PF={res.profit_factor:.2f}")

    # ─── Per-pattern per-pair breakdown ────────────────────────────────────────
    logger.info("=" * 90)
    logger.info("PER-PATTERN PER-PAIR BREAKDOWN (10-YEAR)")
    logger.info(f"{'Pair':<10} {'Pattern':<12} {'Trades':>7} {'WR':>6} {'PF':>7} {'Pips':>10} {'AvgW':>8} {'AvgL':>8}")
    logger.info("-" * 90)

    pattern_totals = defaultdict(lambda: {"trades": 0, "pips": 0.0, "wins": 0, "gross_win": 0.0, "gross_loss": 0.0})
    grand = {"trades": 0, "pips": 0.0, "wins": 0, "gross_win": 0.0, "gross_loss": 0.0}

    for symbol in PAIRS:
        if symbol not in results:
            continue
        res = results[symbol]
        by_pattern = defaultdict(list)
        for t in res.trades:
            by_pattern[t.pattern_type].append(t)

        for pat in PATTERNS:
            trades = by_pattern.get(pat, [])
            n = len(trades)
            if n == 0:
                logger.info(f"  {symbol:<10} {pat:<12} {'0':>7}")
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

            pattern_totals[pat]["trades"] += n
            pattern_totals[pat]["pips"] += total_pips
            pattern_totals[pat]["wins"] += len(wins)
            pattern_totals[pat]["gross_win"] += gross_win
            pattern_totals[pat]["gross_loss"] += gross_loss
            grand["trades"] += n; grand["pips"] += total_pips
            grand["wins"] += len(wins)
            grand["gross_win"] += gross_win; grand["gross_loss"] += gross_loss

        pf_str = f"{res.profit_factor:.2f}" if res.profit_factor < 100 else "inf"
        logger.info(f"  {symbol:<10} {'TOTAL':<12} {res.total_trades:>7} {res.win_rate:>5.0f}% {pf_str:>7} {res.total_pnl_pips:>+10.1f}")
        logger.info("")

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

    # ─── Helper: build equity + drawdown arrays ───────────────────────────────
    def build_equity_curve(trades, starting_eq):
        if not trades:
            return [], [], [], 0.0
        eq = [starting_eq]
        times = [trades[0].entry_time]
        for t in trades:
            eq.append(eq[-1] + t.pnl_currency)
            times.append(t.exit_time if t.exit_time else t.entry_time)
        eq = np.array(eq)
        peak = np.maximum.accumulate(eq)
        dd_pct = (eq - peak) / peak * 100
        return times, eq, dd_pct, abs(dd_pct.min())

    # ─── Combined portfolio ────────────────────────────────────────────────────
    all_trades = []
    for sym, res in results.items():
        for t in res.trades:
            all_trades.append(t)
    all_trades.sort(key=lambda t: t.exit_time if t.exit_time else t.entry_time)

    c_times, c_eq, c_dd, c_max_dd = build_equity_curve(all_trades, EQUITY)
    final_eq = c_eq[-1] if len(c_eq) > 0 else EQUITY
    ret_pct = (final_eq - EQUITY) / EQUITY * 100

    # Annual stats
    if len(c_times) > 1:
        total_days = (c_times[-1] - c_times[0]).days
        total_years = total_days / 365.25
        annual_ret = ((final_eq / EQUITY) ** (1 / total_years) - 1) * 100 if total_years > 0 else 0
        trades_per_year = grand["trades"] / total_years if total_years > 0 else 0
    else:
        total_years = annual_ret = trades_per_year = 0

    logger.info("=" * 90)
    logger.info(f"PORTFOLIO: £{EQUITY:.0f} -> £{final_eq:.0f} ({ret_pct:+.0f}%), "
                f"MaxDD {c_max_dd:.1f}%, {grand['trades']}T, {grand['pips']:+.0f}p")
    logger.info(f"PERIOD: {total_years:.1f} years, CAGR {annual_ret:.1f}%, "
                f"{trades_per_year:.0f} trades/year")

    # ─── Style config ─────────────────────────────────────────────────────────
    pat_colors = {"HVF": "#7B2D8E", "KZ_HUNT": "#0097A7", "VIPER": "#D32F2F"}
    EQUITY_COLOR = "#1565C0"
    DD_COLOR = "#C62828"
    BG_COLOR = "#FAFAFA"
    GRID_COLOR = "#E0E0E0"

    # ─── Chart 1: Per-pair equity + drawdown ──────────────────────────────────
    n_pairs = len([p for p in PAIRS if p in results])
    fig, axes = plt.subplots(n_pairs, 2, figsize=(20, 5 * n_pairs),
                             gridspec_kw={"width_ratios": [3, 1]})
    if n_pairs == 1:
        axes = axes.reshape(1, -1)

    for idx, symbol in enumerate(PAIRS):
        if symbol not in results:
            continue
        res = results[symbol]
        if not res.trades:
            axes[idx][0].set_title(f"{symbol}: 0 trades")
            axes[idx][1].set_visible(False)
            continue

        p_times, p_eq, p_dd, p_max_dd = build_equity_curve(res.trades, EQUITY)

        # Left: equity curve with drawdown below
        ax_eq = axes[idx][0]
        ax_eq.set_facecolor(BG_COLOR)
        ax_eq.plot(p_times, p_eq, color=EQUITY_COLOR, linewidth=1.3, alpha=0.9, zorder=2)
        ax_eq.fill_between(p_times, EQUITY, p_eq,
                           where=np.array(p_eq) >= EQUITY, color=EQUITY_COLOR, alpha=0.08)
        ax_eq.fill_between(p_times, EQUITY, p_eq,
                           where=np.array(p_eq) < EQUITY, color=DD_COLOR, alpha=0.08)
        ax_eq.axhline(y=EQUITY, color="gray", linestyle="--", alpha=0.4)

        # Pattern trade markers
        running = EQUITY
        for t in res.trades:
            running += t.pnl_currency
            color = pat_colors.get(t.pattern_type, "gray")
            marker = "^" if t.pnl_pips > 0 else "v"
            ttime = t.exit_time if t.exit_time else t.entry_time
            ax_eq.scatter(ttime, running, color=color, marker=marker, s=14, alpha=0.5, zorder=3)

        # Legend entries for patterns
        by_pat = defaultdict(list)
        for t in res.trades:
            by_pat[t.pattern_type].append(t)
        for pat in PATTERNS:
            ts = by_pat.get(pat, [])
            if ts:
                pips = sum(t.pnl_pips for t in ts)
                ax_eq.scatter([], [], color=pat_colors.get(pat, "gray"), s=30,
                              label=f"{pat}: {len(ts)}T, {pips:+.0f}p")

        pf_str = f"PF={res.profit_factor:.2f}" if res.profit_factor < 100 else "PF=inf"
        final_p = p_eq[-1]
        p_ret = (final_p - EQUITY) / EQUITY * 100
        ax_eq.set_title(f"{symbol} — {res.total_trades}T, {res.total_pnl_pips:+,.0f}p, {pf_str}, "
                        f"WR={res.win_rate:.0f}%, MaxDD={p_max_dd:.1f}%",
                        fontsize=12, fontweight="bold")
        ax_eq.set_ylabel("Equity (£)")
        ax_eq.legend(loc="upper left", fontsize=8)
        ax_eq.grid(True, alpha=0.3, color=GRID_COLOR)
        ax_eq.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))

        # Create drawdown subplot below equity (shared x axis)
        # Use a twin-axis trick: draw DD on secondary y-axis at the bottom
        ax_dd = ax_eq.twinx()
        ax_dd.fill_between(p_times, p_dd, 0, color=DD_COLOR, alpha=0.15, zorder=1)
        ax_dd.plot(p_times, p_dd, color=DD_COLOR, linewidth=0.5, alpha=0.4, zorder=1)
        ax_dd.set_ylabel("DD (%)", color=DD_COLOR, fontsize=9)
        ax_dd.tick_params(axis="y", labelcolor=DD_COLOR, labelsize=8)
        ax_dd.set_ylim(min(p_dd.min() * 1.5, -1), 2)

        # Right: stats box
        ax_stats = axes[idx][1]
        ax_stats.axis("off")
        ax_stats.set_facecolor(BG_COLOR)

        wins = [t for t in res.trades if t.pnl_pips > 0]
        losses = [t for t in res.trades if t.pnl_pips <= 0]
        gross_w = sum(t.pnl_pips for t in wins)
        gross_l = abs(sum(t.pnl_pips for t in losses))
        avg_win = gross_w / len(wins) if wins else 0
        avg_loss = gross_l / len(losses) if losses else 0
        expectancy = res.total_pnl_pips / res.total_trades if res.total_trades > 0 else 0

        stats_text = (
            f"Trades: {res.total_trades}\n"
            f"Win Rate: {res.win_rate:.0f}%\n"
            f"Profit Factor: {pf_str}\n"
            f"Total Pips: {res.total_pnl_pips:+,.0f}\n"
            f"Expectancy: {expectancy:+.1f} p/trade\n"
            f"───────────────\n"
            f"Avg Win: +{avg_win:.1f}p\n"
            f"Avg Loss: -{avg_loss:.1f}p\n"
            f"Gross Win: +{gross_w:,.0f}p\n"
            f"Gross Loss: -{gross_l:,.0f}p\n"
            f"───────────────\n"
            f"Start: £{EQUITY:.0f}\n"
            f"Final: £{final_p:,.0f}\n"
            f"Return: {p_ret:+.0f}%\n"
            f"Max DD: {p_max_dd:.1f}%"
        )
        ax_stats.text(0.1, 0.95, stats_text, transform=ax_stats.transAxes,
                      fontsize=10, verticalalignment="top", fontfamily="monospace",
                      bbox=dict(boxstyle="round,pad=0.5", facecolor="white", edgecolor="#CCCCCC", alpha=0.9))

    fig.suptitle(f"10-Year Per-Pair Backtest — V3 Config (HVF+KZ Hunt, £{EQUITY:.0f} start)",
                 fontsize=15, fontweight="bold", y=1.01)
    plt.tight_layout()
    chart_pairs = os.path.join(CHART_DIR, "bt_10yr_pairs_dd.png")
    fig.savefig(chart_pairs, dpi=150, bbox_inches="tight")
    plt.close()
    logger.info(f"Saved {chart_pairs}")

    # ─── Chart 2: Combined portfolio equity + drawdown ─────────────────────────
    fig2, (ax_top, ax_bot) = plt.subplots(2, 1, figsize=(20, 10),
                                           gridspec_kw={"height_ratios": [3, 1]})

    # Equity curve
    ax_top.set_facecolor(BG_COLOR)
    ax_top.plot(c_times, c_eq, color=EQUITY_COLOR, linewidth=1.5, alpha=0.9, zorder=2)
    ax_top.fill_between(c_times, EQUITY, c_eq,
                        where=c_eq >= EQUITY, color=EQUITY_COLOR, alpha=0.08)
    ax_top.fill_between(c_times, EQUITY, c_eq,
                        where=c_eq < EQUITY, color=DD_COLOR, alpha=0.08)
    ax_top.axhline(y=EQUITY, color="gray", linestyle="--", alpha=0.4)

    # Trade markers
    running_eq = EQUITY
    for t in all_trades:
        running_eq += t.pnl_currency
        color = pat_colors.get(t.pattern_type, "gray")
        marker = "^" if t.pnl_pips > 0 else "v"
        ttime = t.exit_time if t.exit_time else t.entry_time
        ax_top.scatter(ttime, running_eq, color=color, marker=marker, s=12, alpha=0.35, zorder=3)

    # Pattern legend
    for pat, col in pat_colors.items():
        pt = pattern_totals[pat]
        if pt["trades"] > 0:
            pf = pt["gross_win"] / pt["gross_loss"] if pt["gross_loss"] > 0 else float("inf")
            pf_s = f"PF={pf:.2f}" if pf < 100 else "PF=inf"
            ax_top.scatter([], [], color=col, s=40,
                           label=f"{pat}: {pt['trades']}T, {pt['pips']:+,.0f}p, {pf_s}")

    ax_top.set_title(
        f"Combined Portfolio — £{EQUITY:.0f} → £{final_eq:,.0f} ({ret_pct:+,.0f}%), "
        f"{grand['trades']}T, {grand['pips']:+,.0f}p, MaxDD {c_max_dd:.1f}%, "
        f"CAGR {annual_ret:.1f}%, {trades_per_year:.0f} T/yr",
        fontsize=13, fontweight="bold")
    ax_top.set_ylabel("Equity (£)")
    ax_top.legend(loc="upper left", fontsize=10)
    ax_top.grid(True, alpha=0.3, color=GRID_COLOR)
    ax_top.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))

    # Drawdown chart
    ax_bot.set_facecolor(BG_COLOR)
    ax_bot.fill_between(c_times, c_dd, 0, color=DD_COLOR, alpha=0.3)
    ax_bot.plot(c_times, c_dd, color=DD_COLOR, linewidth=0.7, alpha=0.6)
    ax_bot.axhline(y=0, color="gray", linestyle="-", alpha=0.3)

    # Mark worst drawdown point
    worst_idx = np.argmin(c_dd)
    ax_bot.annotate(f"  Max DD: {c_dd[worst_idx]:.1f}%",
                    xy=(c_times[worst_idx], c_dd[worst_idx]),
                    fontsize=9, color=DD_COLOR, fontweight="bold")
    ax_bot.scatter([c_times[worst_idx]], [c_dd[worst_idx]], color=DD_COLOR, s=40, zorder=5)

    ax_bot.set_ylabel("Drawdown (%)")
    ax_bot.set_xlabel("Time")
    ax_bot.grid(True, alpha=0.3, color=GRID_COLOR)
    ax_bot.set_title(f"Portfolio Drawdown (max {c_max_dd:.1f}%)", fontsize=11)
    ax_bot.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))

    plt.tight_layout()
    chart_combined = os.path.join(CHART_DIR, "bt_10yr_combined_dd.png")
    fig2.savefig(chart_combined, dpi=150, bbox_inches="tight")
    plt.close()
    logger.info(f"Saved {chart_combined}")

    # ─── Chart 3: Individual pair charts (one per pair, full page) ────────────
    for symbol in PAIRS:
        if symbol not in results:
            continue
        res = results[symbol]
        if not res.trades:
            continue

        p_times, p_eq, p_dd, p_max_dd = build_equity_curve(res.trades, EQUITY)

        fig3, (ax3_top, ax3_bot) = plt.subplots(2, 1, figsize=(18, 9),
                                                  gridspec_kw={"height_ratios": [3, 1]})

        # Equity
        ax3_top.set_facecolor(BG_COLOR)
        ax3_top.plot(p_times, p_eq, color=EQUITY_COLOR, linewidth=1.5, alpha=0.9, zorder=2)
        ax3_top.fill_between(p_times, EQUITY, p_eq,
                             where=np.array(p_eq) >= EQUITY, color=EQUITY_COLOR, alpha=0.08)
        ax3_top.fill_between(p_times, EQUITY, p_eq,
                             where=np.array(p_eq) < EQUITY, color=DD_COLOR, alpha=0.08)
        ax3_top.axhline(y=EQUITY, color="gray", linestyle="--", alpha=0.4)

        # Trade markers
        running = EQUITY
        by_pat = defaultdict(list)
        for t in res.trades:
            by_pat[t.pattern_type].append(t)
            running += t.pnl_currency
            color = pat_colors.get(t.pattern_type, "gray")
            marker = "^" if t.pnl_pips > 0 else "v"
            ttime = t.exit_time if t.exit_time else t.entry_time
            ax3_top.scatter(ttime, running, color=color, marker=marker, s=18, alpha=0.5, zorder=3)

        for pat in PATTERNS:
            ts = by_pat.get(pat, [])
            if ts:
                pips = sum(t.pnl_pips for t in ts)
                wins_p = len([t for t in ts if t.pnl_pips > 0])
                wr_p = wins_p / len(ts) * 100
                ax3_top.scatter([], [], color=pat_colors.get(pat, "gray"), s=40,
                                label=f"{pat}: {len(ts)}T, {pips:+,.0f}p, WR={wr_p:.0f}%")

        pf_str = f"PF={res.profit_factor:.2f}" if res.profit_factor < 100 else "PF=inf"
        final_p = p_eq[-1]
        p_ret = (final_p - EQUITY) / EQUITY * 100
        expectancy = res.total_pnl_pips / res.total_trades

        ax3_top.set_title(
            f"{symbol} — 10yr Backtest — {res.total_trades}T, {res.total_pnl_pips:+,.0f}p, "
            f"{pf_str}, WR={res.win_rate:.0f}%, £{EQUITY:.0f}→£{final_p:,.0f} ({p_ret:+,.0f}%)",
            fontsize=13, fontweight="bold")
        ax3_top.set_ylabel("Equity (£)")
        ax3_top.legend(loc="upper left", fontsize=10)
        ax3_top.grid(True, alpha=0.3, color=GRID_COLOR)
        ax3_top.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))

        # Drawdown
        ax3_bot.set_facecolor(BG_COLOR)
        ax3_bot.fill_between(p_times, p_dd, 0, color=DD_COLOR, alpha=0.3)
        ax3_bot.plot(p_times, p_dd, color=DD_COLOR, linewidth=0.7, alpha=0.6)
        ax3_bot.axhline(y=0, color="gray", linestyle="-", alpha=0.3)

        worst_idx = np.argmin(p_dd)
        ax3_bot.annotate(f"  Max DD: {p_dd[worst_idx]:.1f}%",
                         xy=(p_times[worst_idx], p_dd[worst_idx]),
                         fontsize=9, color=DD_COLOR, fontweight="bold")
        ax3_bot.scatter([p_times[worst_idx]], [p_dd[worst_idx]], color=DD_COLOR, s=40, zorder=5)

        ax3_bot.set_ylabel("Drawdown (%)")
        ax3_bot.set_xlabel("Time")
        ax3_bot.grid(True, alpha=0.3, color=GRID_COLOR)
        ax3_bot.set_title(f"Drawdown (max {p_max_dd:.1f}%)", fontsize=11)
        ax3_bot.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))

        plt.tight_layout()
        chart_file = os.path.join(CHART_DIR, f"bt_10yr_{symbol.lower()}.png")
        fig3.savefig(chart_file, dpi=150, bbox_inches="tight")
        plt.close()
        logger.info(f"Saved {chart_file}")

    logger.info("=" * 90)
    logger.info("ALL CHARTS COMPLETE")

    with open("C:/hvf_trader/bt_10yr_full_status.txt", "w") as f:
        f.write("COMPLETE\n")

except Exception:
    with open("C:/hvf_trader/bt_10yr_full_error.txt", "w") as f:
        traceback.print_exc(file=f)
