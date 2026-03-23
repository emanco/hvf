# Expert Panel Findings — 2026-03-13

Three-expert review (Quant Risk, Systematic Algo, Professional Forex Trader).

## DONE — Implemented 2026-03-13
- [x] Revert to 60/40 partial close (PARTIAL_CLOSE_PCT 0.50 -> 0.60)
- [x] Reduce KZ Hunt risk to 1% (RISK_PCT_BY_PATTERN KZ_HUNT 2.0 -> 1.0)
- [x] Exclude EURGBP from HVF (added to PATTERN_SYMBOL_EXCLUSIONS)
- [x] Add min 15-pip stop for KZ Hunt
- [x] Add startup reconciliation (commit 1e44c2a) — DB vs MT5 cross-check, Telegram alerts on mismatch
- [x] V7 backtest run: PF 1.74, MaxDD 9.7%, 5936T, +24163p (confirms improvements)

## TODO — This Month
- [x] Fix deployment to single path with deploy.sh (nested hvf_trader/hvf_trader/ removed, single canonical path)
- [x] Replace Windows Scheduled Task with NSSM service wrapper (commit edd3d3a)
- [x] Enable SQLite WAL mode (event listener on engine connect, commit 692c33e)
- [x] Recalculate SL from actual fill price, not observed price at signal time (commit a09c02b)
- [x] Start live vs backtest tracking (slippage, intended prices, invalidation ratio in weekly summary, commit 120f72e)

## TODO — Over Time
- [ ] Portfolio-level correlation guard: block new entry when 3+ open positions share USD/EUR directional exposure
- [x] Rolling Sharpe (60-day) + WR decay monitoring with Telegram auto-alerts (commit 441134c)
- [ ] Backtest alternative: SL = entry - 0.3x ATR instead of breakeven after partial (algo trader suggests 15-25% improvement)
- [ ] Regime filter: 20-day realized vol percentile. Low-vol = reduce size or pause
- [ ] Monte Carlo simulation: randomise trade order 10K times, report 5th-percentile MaxDD (expect 30-40%)
- [ ] Per-pair daily trade limit: max 2 KZ Hunt triggers per pair per day
- [x] Kill switch: if live PF < 1.2 after 200+ trades, auto-halt and alert (commit 7c82fcf)

## Key Numbers From Panel
- Live PF expected: 1.15-1.30 (vs 1.53 backtest) — 40-60% degradation
- Realistic MaxDD: 28-35% (vs 19% backtest)
- Effective independent bets: 2.5-3.0 (not 6) due to EUR/USD correlation
- 1 pip slippage/trade = 31% of edge consumed (523 trades/year, +1704 pips/year)
- Breakeven stop gets hit 30-40% of time on trades that reached T1 (algo trader estimate)

## Scaling Milestones (Forex Trader)
- Phase 1 (months 1-6): Validation, 200+ live trades, target live PF > 1.3
- Phase 2 (months 6-12): Stabilisation, 500+ trades, reduce to 1% all patterns
- Phase 3 (month 12+): Prop firm evaluation with verified track record
- Phase 4 (year 2+): Multiple funded accounts, $50-100K under management
