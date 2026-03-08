"""3-variant aggressive backtest: Current vs V1 (selective bump) vs V2 (full aggressive).
Runs on VPS. Generates per-pair + combined equity chart."""
import os, sys, traceback
sys.path.insert(0, "C:/")
os.chdir("C:/hvf_trader")

try:
    from dotenv import load_dotenv
    load_dotenv("C:/hvf_trader/.env")

    import logging
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    logger = logging.getLogger("bt_aggressive")

    import MetaTrader5 as mt5
    import pandas as pd
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np

    from hvf_trader import config
    from hvf_trader.data.data_fetcher import add_indicators
    from hvf_trader.backtesting.backtest_engine import BacktestEngine

    path = os.getenv("MT5_PATH")
    login = int(os.getenv("MT5_LOGIN"))
    password = os.getenv("MT5_PASSWORD")
    server = os.getenv("MT5_SERVER")

    if not mt5.initialize(path=path):
        sys.exit(1)
    if not mt5.login(login, password=password, server=server):
        sys.exit(1)

    PAIRS = ["EURUSD", "NZDUSD", "EURGBP", "USDCHF", "EURAUD"]
    EQUITY = 700.0
    BARS = 10000
    PATTERNS = ["HVF", "VIPER", "KZ_HUNT"]
    EXCLUSIONS = {"VIPER": ["EURGBP", "NZDUSD", "EURAUD"], "KZ_HUNT": ["EURUSD"]}

    # Ensure EURAUD pip value
    if "EURAUD" not in config.PIP_VALUES:
        config.PIP_VALUES["EURAUD"] = 0.0001

    # ─── Fetch data ────────────────────────────────────────────────────
    data = {}
    for symbol in PAIRS:
        rates_1h = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_H1, 0, BARS)
        rates_4h = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_H4, 0, 2500)
        if rates_1h is None or rates_4h is None:
            logger.warning(f"No data for {symbol}")
            continue
        df_1h = pd.DataFrame(rates_1h)
        df_1h["time"] = pd.to_datetime(df_1h["time"], unit="s", utc=True)
        df_4h = pd.DataFrame(rates_4h)
        df_4h["time"] = pd.to_datetime(df_4h["time"], unit="s", utc=True)
        df_1h = add_indicators(df_1h)
        df_4h = add_indicators(df_4h)
        df_1h = df_1h.dropna(subset=["atr", "ema_200", "adx"]).reset_index(drop=True)
        data[symbol] = (df_1h, df_4h)
        logger.info(f"{symbol}: {len(df_1h)} bars")

    mt5.shutdown()

    # ─── Config override helper ─────────────────────────────────────────
    def run_variant(label, overrides):
        """Run backtest with config overrides, then restore originals."""
        # Save originals
        saved = {}
        for key, val in overrides.items():
            saved[key] = getattr(config, key)
            setattr(config, key, val)

        results = {}
        for symbol in PAIRS:
            if symbol not in data:
                continue
            df_1h, df_4h = data[symbol]
            eng = BacktestEngine(starting_equity=EQUITY, enabled_patterns=PATTERNS)
            result = eng.run(df_1h, symbol, df_4h)
            results[symbol] = result

            # Per-pattern breakdown
            by_pat = {}
            for t in result.trades:
                pt = t.pattern_type or "HVF"
                by_pat.setdefault(pt, []).append(t)
            pat_str = ", ".join(f"{p}:{len(ts)}T/{sum(t.pnl_pips or 0 for t in ts):+.0f}p" for p, ts in sorted(by_pat.items()))
            logger.info(f"  {label} {symbol}: {result.total_trades}T, {result.total_pnl_pips:+.1f}p, PF={result.profit_factor:.2f} [{pat_str}]")

        # Restore
        for key, val in saved.items():
            setattr(config, key, val)

        total_t = sum(r.total_trades for r in results.values())
        total_p = sum(r.total_pnl_pips for r in results.values())
        logger.info(f"  {label} TOTAL: {total_t}T, {total_p:+.1f}p")
        return results

    # ─── Define variants ──────────────────────────────────────────────
    # CURRENT: what's deployed now
    current_overrides = {
        "RISK_PCT_BY_PATTERN": {"HVF": 1.0, "VIPER": 1.0, "KZ_HUNT": 1.0, "LONDON_SWEEP": 0.5},
        "MAX_CONCURRENT_TRADES": 4,
        "PATTERN_SYMBOL_EXCLUSIONS": EXCLUSIONS,
        "TRAILING_STOP_ATR_MULT_BY_PATTERN": {"HVF": 1.5, "VIPER": 2.5, "KZ_HUNT": 1.5, "LONDON_SWEEP": 1.5},
        "PARTIAL_CLOSE_PCT": 0.50,
        "TARGET_1_MULT": 0.5,
        "TARGET_2_MULT": 1.0,
        "DAILY_LOSS_LIMIT_PCT": 3.0,
        "WEEKLY_LOSS_LIMIT_PCT": 5.0,
        "MONTHLY_LOSS_LIMIT_PCT": 10.0,
    }

    # VARIANT 1: Selective Risk Bump — target MaxDD <10%
    # Rationale: bump proven patterns (KZ PF>1.3, Viper PF>1.5) to 1.5%,
    # allow 5 concurrent, tighten KZ trailing to lock profits faster,
    # raise daily limit proportionally.
    v1_overrides = {
        "RISK_PCT_BY_PATTERN": {"HVF": 1.0, "VIPER": 1.5, "KZ_HUNT": 1.5, "LONDON_SWEEP": 0.5},
        "MAX_CONCURRENT_TRADES": 5,
        "PATTERN_SYMBOL_EXCLUSIONS": EXCLUSIONS,
        "TRAILING_STOP_ATR_MULT_BY_PATTERN": {"HVF": 1.5, "VIPER": 2.5, "KZ_HUNT": 1.2, "LONDON_SWEEP": 1.5},
        "PARTIAL_CLOSE_PCT": 0.50,
        "TARGET_1_MULT": 0.5,
        "TARGET_2_MULT": 1.0,
        "DAILY_LOSS_LIMIT_PCT": 4.0,
        "WEEKLY_LOSS_LIMIT_PCT": 6.0,
        "MONTHLY_LOSS_LIMIT_PCT": 12.0,
    }

    # VARIANT 2: Full Aggressive — target MaxDD <15%
    # Rationale: 2% on KZ+Viper (proven edges), max 6 concurrent,
    # 60% partial close to secure more profit early, tighter KZ trail,
    # raised loss limits to accommodate bigger positions.
    v2_overrides = {
        "RISK_PCT_BY_PATTERN": {"HVF": 1.0, "VIPER": 2.0, "KZ_HUNT": 2.0, "LONDON_SWEEP": 0.5},
        "MAX_CONCURRENT_TRADES": 6,
        "PATTERN_SYMBOL_EXCLUSIONS": EXCLUSIONS,
        "TRAILING_STOP_ATR_MULT_BY_PATTERN": {"HVF": 1.5, "VIPER": 2.0, "KZ_HUNT": 1.0, "LONDON_SWEEP": 1.5},
        "PARTIAL_CLOSE_PCT": 0.60,
        "TARGET_1_MULT": 0.5,
        "TARGET_2_MULT": 1.0,
        "DAILY_LOSS_LIMIT_PCT": 5.0,
        "WEEKLY_LOSS_LIMIT_PCT": 8.0,
        "MONTHLY_LOSS_LIMIT_PCT": 15.0,
    }

    # ─── Run all variants ─────────────────────────────────────────────
    logger.info("=" * 60)
    logger.info("Running CURRENT config...")
    current_results = run_variant("CURRENT", current_overrides)

    logger.info("=" * 60)
    logger.info("Running V1: Selective Risk Bump (1.5% KZ+Viper, max5, tighter KZ trail)...")
    v1_results = run_variant("V1", v1_overrides)

    logger.info("=" * 60)
    logger.info("Running V2: Full Aggressive (2% KZ+Viper, max6, 60% partial, tight trail)...")
    v2_results = run_variant("V2", v2_overrides)

    # ─── Equity curve helpers ─────────────────────────────────────────
    def pair_equity_curve(result, starting_eq):
        eq = [starting_eq]
        times = [result.trades[0].entry_time] if result.trades else [pd.Timestamp.now(tz="UTC")]
        for t in result.trades:
            eq.append(eq[-1] + t.pnl_currency)
            times.append(t.exit_time if t.exit_time else t.entry_time)
        return times, eq

    def combined_equity_curve(results_dict, starting_eq):
        all_trades = []
        for sym, res in results_dict.items():
            for t in res.trades:
                all_trades.append(t)
        all_trades.sort(key=lambda t: t.exit_time if t.exit_time else t.entry_time)
        eq = [starting_eq]
        times = [all_trades[0].entry_time if all_trades else pd.Timestamp.now(tz="UTC")]
        for t in all_trades:
            eq.append(eq[-1] + t.pnl_currency)
            times.append(t.exit_time if t.exit_time else t.entry_time)
        return times, eq

    def calc_max_drawdown(equity_list):
        peak = equity_list[0]
        max_dd = 0
        for eq in equity_list:
            if eq > peak:
                peak = eq
            dd = (peak - eq) / peak * 100
            if dd > max_dd:
                max_dd = dd
        return max_dd

    # ─── Summaries ────────────────────────────────────────────────────
    all_variants = [
        ("CURRENT", current_results, "tab:gray"),
        ("V1: 1.5% KZ+Viper, max5", v1_results, "tab:blue"),
        ("V2: 2% KZ+Viper, max6, 60% partial", v2_results, "tab:red"),
    ]

    logger.info("=" * 60)
    logger.info("SUMMARY")
    logger.info("-" * 60)
    for label, results, _ in all_variants:
        total_t = sum(r.total_trades for r in results.values())
        total_p = sum(r.total_pnl_pips for r in results.values())
        _, eq = combined_equity_curve(results, EQUITY)
        max_dd = calc_max_drawdown(eq)
        logger.info(f"  {label}: {total_t}T, {total_p:+.0f}p, £{eq[-1]:.0f} (MaxDD {max_dd:.1f}%)")

    # ─── Plot: per-pair + combined ────────────────────────────────────
    n_pairs = len(PAIRS)
    rows = (n_pairs + 1) // 2 + 1  # +1 for combined
    fig, axes = plt.subplots(rows, 2, figsize=(18, 5.5 * rows))

    for idx, pair in enumerate(PAIRS):
        ax = axes[idx // 2][idx % 2]
        for label, results, color in all_variants:
            if pair in results and results[pair].trades:
                t, eq = pair_equity_curve(results[pair], EQUITY)
                max_dd = calc_max_drawdown(eq)
                ax.plot(t, eq, color=color, linewidth=1.3, alpha=0.85,
                        label=f"{label}: {results[pair].total_trades}T, {results[pair].total_pnl_pips:+.0f}p, £{eq[-1]:.0f}, DD {max_dd:.1f}%")
        ax.axhline(y=EQUITY, color="gray", linestyle="--", alpha=0.3)
        ax.set_title(pair, fontsize=13, fontweight="bold")
        ax.set_ylabel("Equity (£)")
        ax.legend(loc="upper left", fontsize=8)
        ax.grid(True, alpha=0.3)

    # Hide unused cell
    if n_pairs % 2 == 1:
        axes[n_pairs // 2][1].set_visible(False)

    # Combined portfolio (last row)
    ax_combined = fig.add_subplot(rows, 1, rows)
    axes[rows - 1][0].set_visible(False)
    axes[rows - 1][1].set_visible(False)

    for label, results, color in all_variants:
        t, eq = combined_equity_curve(results, EQUITY)
        total_t = sum(r.total_trades for r in results.values())
        total_p = sum(r.total_pnl_pips for r in results.values())
        max_dd = calc_max_drawdown(eq)
        ax_combined.plot(t, eq, color=color, linewidth=1.8, alpha=0.85,
                         label=f"{label}: {total_t}T, {total_p:+.0f}p → £{eq[-1]:.0f} (MaxDD {max_dd:.1f}%)")

    ax_combined.axhline(y=EQUITY, color="gray", linestyle="--", alpha=0.3)
    ax_combined.axhline(y=1400, color="green", linestyle=":", alpha=0.4, label="£1400 (2x)")
    ax_combined.set_title("Combined Portfolio", fontsize=14, fontweight="bold")
    ax_combined.set_xlabel("Time")
    ax_combined.set_ylabel("Equity (£)")
    ax_combined.legend(loc="upper left", fontsize=9)
    ax_combined.grid(True, alpha=0.3)

    fig.suptitle("Aggressive Variants: Current vs V1 (1.5%) vs V2 (2.0%) — £700 Start, 5 pairs",
                 fontsize=14, fontweight="bold", y=0.995)
    plt.tight_layout(rect=[0, 0, 1, 0.98])

    os.makedirs("C:/hvf_trader/backtests/charts", exist_ok=True)
    fig.savefig("C:/hvf_trader/backtests/charts/bt_aggressive_variants.png", dpi=150)
    plt.close()

    logger.info("Saved backtests/charts/bt_aggressive_variants.png")

    with open("C:/hvf_trader/bt_aggressive_status.txt", "w") as f:
        f.write("COMPLETE\n")

except Exception:
    with open("C:/hvf_trader/bt_aggressive_error.txt", "w") as f:
        traceback.print_exc(file=f)
