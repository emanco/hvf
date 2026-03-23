# Bug History (pre 2026-03-11)

## 2026-03-10, commit 7ef2239 — Armed Pattern Expiry & Dedup
- Live bot used global PATTERN_EXPIRY_BARS (100h) for armed expiry, backtest used per-pattern PATTERN_FRESHNESS_BARS. KZ patterns sat armed for 100h instead of 24h.
- KZ tracker rebuild created duplicate armed patterns. DB load didn't dedup.
- Fix: per-pattern freshness in `_check_armed_patterns()`, dedup on startup load.

## 2026-03-10, commit 0364926 — Partial Close Telegram Alert
- `alert_partial_close` existed but was never called from trade_monitor.
- Wired it up: pass alerter to TradeMonitor, call on T1 hit.

## 2026-03-10, commit e569aa2 — Invalid Stops (retcode 10016)
- SL/TP sent unrounded to MT5. Fix: round to `symbol_info.digits`.

## 2026-03-10, commit e530cf8 — Cold-Start Duplicate Trades
- On restart, KZ tracker re-detected same patterns. No check for TRIGGERED status.
- Cost: ~$4.40 across 3 restarts.
- Fix: 3-way dedup check (open trades, armed, recently triggered 24h).

## 2026-03-10, commit d69b2e0 — KZ Hunt Index Mismatch
- `_scan_instrument()` passed `len(df_1h)-1` (~499) as bar_idx. KZ levels at ~499, detector searched from 500+ = zero patterns.
- Backtest worked because bars processed sequentially.
- Fix: rebuild KZ tracker from last 200 bars each cycle.

## 2026-03-09, commit 5ade2ea — Multiple Fixes
- `.get()` crash on TradeRecord in risk_manager (used hasattr pattern)
- Stale pattern confirmation: proximity guard (within 2x stop-distance)
- Freshness filter using PATTERN_FRESHNESS_BARS
- Pattern expiry: `bars_since_detection = len(df)` always 50, fixed to use detected_at
- MAX_SPREAD_PCT_OF_STOP: 5%->10%
- DB cleaned: 12 junk trades + 26 stale Viper patterns deleted
- MT5 AutoTrading must be enabled via GUI
- MT5 autostart: setup_mt5_autostart.ps1

## HVF Optimization Research (2026-03-08)
- AND convergence is CORRECT (OR is net negative)
- Variant E deployed: MIN_RRR=1.5 for HVF
- GBPJPY/USDJPY/XAUUSD produce zero H1 HVF patterns
- Viper SHORT-only profitable short-term but net negative over 10yr
