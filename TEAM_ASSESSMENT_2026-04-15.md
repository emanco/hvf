# KZ Hunt Bot — Multi-Expert Assessment Report

**Date**: 2026-04-15
**Status**: ~66 trades since go-live (2026-03-25), data collection phase
**Account**: IC Markets Demo, ~$10.5k, 1% risk/trade, 8 pairs

---

## Panel

| Role | Focus Area |
|------|-----------|
| Expert Trader | Strategy logic, entry/exit rules, risk controls, pair selection |
| Data Analyst | Data model, metrics, reporting, observability |
| Senior SWE | Architecture, thread safety, reliability, code quality |
| Quant Analyst | Statistical validity, edge fragility, correlation risk, position sizing |

---

## CRITICAL FINDINGS (Fix Before Real Money)

### 1. Correlation Guard Is Dangerously Incomplete
**Flagged by**: Expert Trader, Quant Analyst, Senior SWE

The correlation map in `risk_manager.py:26-29` only covers EURUSD/GBPUSD (which isn't even in the portfolio). Meanwhile:
- **4 pairs share EUR exposure**: EURUSD, EURGBP, EURAUD, EURJPY
- **3 pairs share JPY exposure**: GBPJPY, EURJPY, CHFJPY
- **USDCHF inversely correlates** with EURUSD

With 1% risk each and MAX_CONCURRENT_TRADES=6, a single macro event (ECB, BOJ, NFP) could trigger 4+ correlated stops simultaneously for 4-6% drawdown in minutes — hitting the daily circuit breaker *after* the damage is done.

**Quant's estimate**: Effective independent bets = ~2.1 (down from the already-low 2.5-3.0 estimate for 5 pairs). The correlation guard covers 1 of 15 pair combinations.

### 2. Missing News Filter for EURJPY and CHFJPY
**Flagged by**: Expert Trader

`news_filter.py:17-28` — the `SYMBOL_CURRENCIES` dict does not include EURJPY or CHFJPY. The news filter returns `False` for these pairs regardless of scheduled events. A BOJ rate decision would not block EURJPY or CHFJPY trades.

GBPJPY is present but the two other JPY pairs are exposed.

### 3. Entry Confirmation Uses Forming Bar (Live-Backtest Divergence)
**Flagged by**: Expert Trader

Pattern detection uses completed bars (`main.py:390` — `df_completed = df_1h.iloc[:-1]`), but entry confirmation checks the current forming bar (`main.py:632` — `latest_bar = df.iloc[-1]`). This means the bot can enter mid-bar on a wick that later retraces. If the backtest uses completed bar closes for confirmation, this is a systematic live-backtest divergence that turns backtest winners into live losers.

### 4. Three JPY Pairs Are Trading Without Adequate Backtest Validation
**Flagged by**: Quant Analyst, Expert Trader

GBPJPY, EURJPY, CHFJPY were added to live trading with only ~1 OOS walk-forward window per pair (vs 30-40+ windows per original pair). This is statistically meaningless for validation. JPY pairs also have structurally different characteristics (wider spreads, higher vol, carry sensitivity, Asian session home turf).

---

## HIGH PRIORITY FINDINGS (Address During Data Collection Phase)

### 5. Rolling Sharpe Calculation Is Fundamentally Broken
**Flagged by**: Data Analyst (root-caused)

`performance_monitor.py:136-193` — Two compounding bugs:
1. **Uses raw pips instead of percentage returns**. Sharpe expects R_i = PnL_i / equity. Raw pips have no denominator, making the ratio dimensionally meaningless.
2. **Annualization amplifies the error**. With 66 trades over 21 days, `trades_per_year = 792`, so `sqrt(792) = 28.1x` amplification of a slightly negative mean produces the -10.15 reading.

**Fix**: Compute from daily equity returns using EquitySnapshot table, or use `pnl / equity_at_open` per trade.

### 6. `pattern_metadata` Fields Declared But Never Populated
**Flagged by**: Data Analyst

Both `PatternRecord.pattern_metadata` and `TradeRecord.pattern_metadata` (`models.py:61,92`) are JSON columns designed for pattern-specific data (KZ session, range size, rejection sub-scores) but are **never written to anywhere in the codebase**. You are running a "data collection phase" without collecting the data that matters most for analysis.

### 7. No Estimated-PnL Flag on Trade Records
**Flagged by**: Data Analyst

When deal history is unavailable and PnL is estimated from SL/trailing SL (`trade_monitor.py:541-575`, `reconciliation.py:309-368`), the trade is logged with estimated values but no `pnl_estimated` boolean flag. Telegram shows "estimated" but the DB record is indistinguishable from real PnL. The fallback also uses a hardcoded `dollar_per_pip = 10.0`, which is wrong for JPY pairs (~$8.50/lot).

### 8. Performance Monitor Alerts Are Silenced
**Flagged by**: Data Analyst

`main.py:148-153` — `alerter=None`. The performance monitor computes PF, WR, Sharpe, streaks, and decay, but sends zero alerts. During data collection, this is precisely when you want degradation alerts active.

### 9. Edge Is Extremely Fragile
**Flagged by**: Quant Analyst

- Average expectancy: **2.89 pips/trade** (OOS backtest)
- Average win ~12.3 pips, average loss ~12.6 pips — the edge comes almost entirely from win rate (61%), not win size
- 1 pip additional slippage = **35% edge erosion**
- 0.5 pip average spread widening (common during Asian KZ) = **17% erosion**
- This makes the strategy hypersensitive to execution quality

### 10. No Regime Filter
**Flagged by**: Quant Analyst

No VIX/volatility regime detection exists. Low-vol regimes produce tiny KZ ranges where rejection candles are noise and targets can't cover spread. Trending sessions without reversals invalidate the entire thesis. Listed in TODO.md but unimplemented.

### 11. No Thread Watchdog
**Flagged by**: Senior SWE

If the trade monitor thread dies (uncaught `SystemError`, etc.), nothing detects it. Open trades stop being managed — no trailing stops, no partial closes, no invalidation. A simple `is_alive()` check in the scanner loop would catch this.

### 12. No Database Backup
**Flagged by**: Senior SWE

SQLite on Windows with WAL mode + hard power loss = potential corruption. All trade history, patterns, and circuit breaker state would be lost. No backup mechanism exists. For a system managing real money, even a daily copy would be prudent.

### 13. `time.sleep(10)` Blocks the Entire Trade Monitor
**Flagged by**: Senior SWE

`trade_monitor.py:623` — When deal history isn't found during server-close handling, the code sleeps 10 seconds. This blocks monitoring of ALL open trades for 10 seconds. On a 30-second cycle, that's a third of the interval.

### 14. Scoring Model Has Weak Discriminatory Power
**Flagged by**: Quant Analyst, Expert Trader

- 4 of 5 components use discrete buckets (3-5 possible values each), producing a narrow score distribution
- Minimum passing score (50) is achievable with a weak rejection + one strong component
- Volume component uses tick_volume (poor proxy on IC Markets) and defaults to 7.5/15 (50% of max) when data is missing — **rewards data absence**
- Weights (25/20/20/15/20) are unjustified by data
- No body-size minimum on rejection candles — dojis at KZ extremes generate noise signals

---

## MODERATE FINDINGS (Review After 50+ Trades)

### Architecture & Reliability
| # | Finding | Source | Location |
|---|---------|--------|----------|
| 15 | KZ tracker `<=` boundary extends each session by 1 hour | Expert Trader | `killzone_tracker.py:60` |
| 16 | No DST adjustment for KZ windows (misaligned 7 months/year) | Expert Trader | `config.py:123-128` |
| 17 | T2-based RRR check doesn't reflect 60/40 weighted economics | Expert Trader | `kz_hunt_detector.py:57-76` |
| 18 | 24h recently_triggered cooldown blocks valid re-entries | Expert Trader | `main.py:495-496` |
| 19 | Split-order SL race window (30s gap after T1 hit) | Expert Trader, SWE | `trade_monitor.py:237` |
| 20 | Partial close PnL not recorded separately | Data Analyst | `trade_logger.py:306-333` |
| 21 | DRY: deal-matching and PnL estimation duplicated | Senior SWE | `trade_monitor.py` + `reconciliation.py` |
| 22 | Orphaned 60% position if split-order 40% fails + close fails | Senior SWE | `main.py:886-895` |
| 23 | Equity snapshot table grows unbounded (~43k records/month) | Senior SWE | `main.py:289-298` |
| 24 | Post-restart pattern confirmation is weaker (no pattern_obj) | Senior SWE | `main.py:667-686` |
| 25 | No test coverage beyond trivial cases | Senior SWE | `tests/` |

### Quantitative
| # | Finding | Source | Detail |
|---|---------|--------|--------|
| 26 | Walk-forward is not true OOS (params tuned on full dataset) | Quant | Config comments show tuning against backtest results |
| 27 | No portfolio-level backtest with all risk gates active | Quant | Per-pair backtests don't capture concurrent trade limits |
| 28 | Circuit breaker uses realized PnL, not mark-to-market | Quant | 6 trades can be 3% adverse with zero trips |
| 29 | No Monte Carlo ruin probability estimate | Quant | Listed in TODO, unimplemented |
| 30 | 66 trades: can't estimate PF to better than +/-0.5 | Quant | Need ~200 for WR precision, ~500 for PF |

---

## WHAT'S WORKING WELL

The panel unanimously recognized several strengths:

- **4-thread architecture** is well-designed with proper thread-local sessions, armed patterns lock, and detached records
- **Split-order T1 execution** — broker-side TP on the 60% position gives tick-level precision, far better than polling
- **Circuit breaker** — three-tier (daily/weekly/monthly) + per-pattern consecutive loss pause, with DB persistence for crash recovery
- **Fail-closed news filter** — stale cache blocks trading, not allows it
- **Reconciliation** — three layers (trade monitor, reconciliation loop, startup) with multi-miss counters prevent false closes
- **IC Markets deal history workaround** — two-pass matching handles the known broker bug
- **Double-close guard** — prevents reconciliation from overwriting real PnL
- **Logging** — three-tier file logging + DB event trail + Telegram alerts. Excellent for production debugging
- **Invalidation logic** — KZ extreme revisit check with 2hr grace period is a genuine edge improvement (PF 1.56→1.69 in A/B test)
- **Conservative position sizing** — 1% is ~1/4 to 1/7 Kelly, appropriate given edge uncertainty

---

## RECOMMENDED ACTION PLAN

### Before Real Money (Critical)
1. Expand correlation guard to cover EUR cluster (4 pairs) and JPY cluster (3 pairs)
2. Add EURJPY and CHFJPY to `news_filter.py` SYMBOL_CURRENCIES
3. Align entry confirmation to use completed bars (match backtest behavior)
4. Either backtest JPY pairs with full history or reduce their risk to 0.5% until validated

### During Data Collection Phase (High)
5. Fix Rolling Sharpe to use equity returns
6. Populate `pattern_metadata` — you're in data collection but not collecting key data
7. Add `pnl_estimated` flag to TradeRecord
8. Enable performance monitor alerts (`alerter=None` → real alerter)
9. Add thread watchdog for trade monitor
10. Set up daily SQLite backup
11. Remove `time.sleep(10)` from trade monitor server-close handler
12. Set volume fallback score to 0 (not 7.5)

### After 200+ Trades
13. Implement basic regime filter (20-day ATR percentile)
14. Build portfolio-level backtest with concurrent trade limits + correlation blocking
15. Run Monte Carlo simulation for ruin probability
16. Re-evaluate scoring weights with logistic regression on trade outcomes
17. Add correlation-aware position sizing

---

## STATISTICAL MILESTONES

| Trades | What You Can Assess |
|--------|-------------------|
| 66 (now) | Almost nothing with confidence. Check WR is within [49%, 73%] to not reject backtest hypothesis |
| 200 | Win rate with +/-7% precision. Kill switch threshold is correctly set here |
| 500 | Profit factor with reasonable precision. First meaningful live-vs-backtest comparison |
| 800 (100/pair) | Per-pair viability assessment |

---

*Report generated from parallel analysis by 4 specialized agents examining 20+ source files across strategy, data, engineering, and quantitative domains.*
