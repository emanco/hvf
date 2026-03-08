"""HVF Quality Params: Current vs Tighter (validator recommendations).
Tests HVF-only on 5 live pairs with progressively tighter quality filters."""
import os, sys, traceback
sys.path.insert(0, "C:/")
os.chdir("C:/hvf_trader")

try:
    from dotenv import load_dotenv
    load_dotenv("C:/hvf_trader/.env")

    import logging
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    logger = logging.getLogger("bt_hvf_qual")

    import MetaTrader5 as mt5
    import pandas as pd
    import numpy as np

    from hvf_trader import config
    from hvf_trader.data.data_fetcher import add_indicators
    from hvf_trader.backtesting.backtest_engine import BacktestEngine

    path = os.getenv("MT5_PATH")
    mt5.initialize(path=path)
    mt5.login(int(os.getenv("MT5_LOGIN")), password=os.getenv("MT5_PASSWORD"), server=os.getenv("MT5_SERVER"))

    PAIRS = ["EURUSD", "NZDUSD", "EURGBP", "USDCHF", "EURAUD"]
    EQUITY = 700.0

    for p in PAIRS:
        if p not in config.PIP_VALUES:
            config.PIP_VALUES[p] = 0.0001

    # Fetch data once
    data = {}
    for symbol in PAIRS:
        r1 = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_H1, 0, 10000)
        r4 = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_H4, 0, 2500)
        if r1 is None or r4 is None:
            continue
        d1 = pd.DataFrame(r1); d1["time"] = pd.to_datetime(d1["time"], unit="s", utc=True)
        d1 = add_indicators(d1); d1 = d1.dropna(subset=["atr","ema_200","adx"]).reset_index(drop=True)
        d4 = pd.DataFrame(r4); d4["time"] = pd.to_datetime(d4["time"], unit="s", utc=True)
        d4 = add_indicators(d4)
        data[symbol] = (d1, d4)
        logger.info(f"{symbol}: {len(d1)} H1 bars")
    mt5.shutdown()

    def run_variant(label, overrides):
        saved = {}
        for key, val in overrides.items():
            saved[key] = getattr(config, key)
            setattr(config, key, val)

        results = {}
        for symbol in PAIRS:
            if symbol not in data:
                continue
            d1, d4 = data[symbol]
            eng = BacktestEngine(starting_equity=EQUITY, enabled_patterns=["HVF"])
            res = eng.run(d1, symbol, d4)
            results[symbol] = res
            if res.total_trades > 0:
                logger.info(f"  {label} {symbol}: {res.total_trades}T, {res.total_pnl_pips:+.1f}p, "
                            f"PF={res.profit_factor:.2f}, WR={res.win_rate:.0f}%, "
                            f"AvgW={res.avg_win_pips:.1f}p, AvgL={res.avg_loss_pips:.1f}p")
            else:
                logger.info(f"  {label} {symbol}: 0T")

        for key, val in saved.items():
            setattr(config, key, val)

        total_t = sum(r.total_trades for r in results.values())
        total_p = sum(r.total_pnl_pips for r in results.values())
        wins = sum(r.win_count for r in results.values() if hasattr(r, 'win_count'))
        logger.info(f"  {label} TOTAL: {total_t}T, {total_p:+.1f}p")
        return results, total_t, total_p

    base = {"PATTERN_SYMBOL_EXCLUSIONS": {}}

    # ─── VARIANT A: Current config (baseline) ───────────────────────────
    logger.info("=" * 70)
    logger.info("VARIANT A: CURRENT CONFIG (baseline)")
    a_res, a_t, a_p = run_variant("A", {
        **base,
        "HVF_ATR_STOP_MULT": 0.5,
        "HVF_MIN_RRR": 1.0,
        "SCORE_THRESHOLD": 40,
        "SCORE_THRESHOLD_BY_PATTERN": {"HVF": 40, "VIPER": 60, "KZ_HUNT": 50, "LONDON_SWEEP": 50},
        "VOLUME_SPIKE_MULT": 1.2,
        "PATTERN_EXPIRY_BARS": 100,
    })

    # ─── VARIANT B: Moderate tightening ──────────────────────────────────
    logger.info("=" * 70)
    logger.info("VARIANT B: MODERATE (stop=0.75, RRR=1.5, score=50, vol=1.3, expiry=60)")
    b_res, b_t, b_p = run_variant("B", {
        **base,
        "HVF_ATR_STOP_MULT": 0.75,
        "HVF_MIN_RRR": 1.5,
        "SCORE_THRESHOLD": 50,
        "SCORE_THRESHOLD_BY_PATTERN": {"HVF": 50, "VIPER": 60, "KZ_HUNT": 50, "LONDON_SWEEP": 50},
        "VOLUME_SPIKE_MULT": 1.3,
        "PATTERN_EXPIRY_BARS": 60,
    })

    # ─── VARIANT C: Full validator recommendations ───────────────────────
    logger.info("=" * 70)
    logger.info("VARIANT C: FULL VALIDATOR (stop=1.0, RRR=2.0, score=60, vol=1.5, expiry=50)")
    c_res, c_t, c_p = run_variant("C", {
        **base,
        "HVF_ATR_STOP_MULT": 1.0,
        "HVF_MIN_RRR": 2.0,
        "SCORE_THRESHOLD": 60,
        "SCORE_THRESHOLD_BY_PATTERN": {"HVF": 60, "VIPER": 60, "KZ_HUNT": 50, "LONDON_SWEEP": 50},
        "VOLUME_SPIKE_MULT": 1.5,
        "PATTERN_EXPIRY_BARS": 50,
    })

    # ─── VARIANT D: Stop-only change (isolate stop impact) ──────────────
    logger.info("=" * 70)
    logger.info("VARIANT D: STOP-ONLY (stop=1.0, everything else current)")
    d_res, d_t, d_p = run_variant("D", {
        **base,
        "HVF_ATR_STOP_MULT": 1.0,
        "HVF_MIN_RRR": 1.0,
        "SCORE_THRESHOLD": 40,
        "SCORE_THRESHOLD_BY_PATTERN": {"HVF": 40, "VIPER": 60, "KZ_HUNT": 50, "LONDON_SWEEP": 50},
        "VOLUME_SPIKE_MULT": 1.2,
        "PATTERN_EXPIRY_BARS": 100,
    })

    # ─── VARIANT E: RRR-only change (isolate RRR impact) ────────────────
    logger.info("=" * 70)
    logger.info("VARIANT E: RRR-ONLY (RRR=1.5, everything else current)")
    e_res, e_t, e_p = run_variant("E", {
        **base,
        "HVF_ATR_STOP_MULT": 0.5,
        "HVF_MIN_RRR": 1.5,
        "SCORE_THRESHOLD": 40,
        "SCORE_THRESHOLD_BY_PATTERN": {"HVF": 40, "VIPER": 60, "KZ_HUNT": 50, "LONDON_SWEEP": 50},
        "VOLUME_SPIKE_MULT": 1.2,
        "PATTERN_EXPIRY_BARS": 100,
    })

    # ─── Summary ────────────────────────────────────────────────────────
    logger.info("=" * 70)
    logger.info("COMPARISON TABLE")
    logger.info(f"{'Variant':<55} {'Trades':>7} {'Pips':>10} {'Pips/T':>8}")
    logger.info("-" * 85)
    for label, t, p in [
        ("A: Current (stop=0.5, RRR=1.0, score=40)", a_t, a_p),
        ("B: Moderate (stop=0.75, RRR=1.5, score=50)", b_t, b_p),
        ("C: Full Validator (stop=1.0, RRR=2.0, score=60)", c_t, c_p),
        ("D: Stop-only (stop=1.0)", d_t, d_p),
        ("E: RRR-only (RRR=1.5)", e_t, e_p),
    ]:
        ppt = p / t if t > 0 else 0
        logger.info(f"  {label:<53} {t:>7} {p:>+10.1f} {ppt:>+8.1f}")

    # Per-pair breakdown for each variant
    logger.info("=" * 70)
    logger.info("PER-PAIR BREAKDOWN")
    for symbol in PAIRS:
        parts = []
        for label, res in [("A", a_res), ("B", b_res), ("C", c_res), ("D", d_res), ("E", e_res)]:
            r = res.get(symbol)
            if r and r.total_trades > 0:
                parts.append(f"{label}:{r.total_trades}T/{r.total_pnl_pips:+.0f}p/PF={r.profit_factor:.2f}")
            else:
                parts.append(f"{label}:0T")
        logger.info(f"  {symbol}: {' | '.join(parts)}")

    with open("C:/hvf_trader/bt_hvf_qual_status.txt", "w") as f:
        f.write("COMPLETE\n")

except Exception:
    with open("C:/hvf_trader/bt_hvf_qual_error.txt", "w") as f:
        traceback.print_exc(file=f)
