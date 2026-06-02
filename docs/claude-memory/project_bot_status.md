---
name: Bot status as of 2026-05-05 (post exit-overhaul + QL rebuild)
description: Demo mode. KZ_HUNT 4 pairs / score>=60 / flat 12p TP. Quantum London is the FF mean-reversion rebuild (40/12.5/40 EURGBP). NIGHT_TIDE + LB unchanged. Reconciliation orphan-bug class structurally eliminated.
type: project
originSessionId: b47e514d-24ea-44bd-82fc-3d220690e0f2
---
**Account:** IC Markets Demo, balance ~$8k.

## Active strategies

### KZ_HUNT — major exit-policy overhaul shipped 2026-05-05
- **4 pairs**: NZDUSD, EURGBP, EURJPY, EURAUD (down from 6 earlier today and from 8 originally). EURUSD and USDCHF dropped — even with score filter they're net-losing on the 117-trade live sample. EURAUD added back after what-if showed score>=60 rescues it (PF 0.96→1.12).
- **Score threshold 60** (up from 50). Cuts marginal 50–59 setups that were the bulk of the giveback.
- **Flat TP +12p, original spread-comp SL, NO partial, NO trail**. Single broker-side order. All trail/BE/pre-trail/invalidation/split-order machinery disabled for KZ_HUNT.
- **Backtest expectation** on this 6-week sample: PF 1.45, +107p, MaxDD 56p, MAR 1.93. Realistic forward expectation after typical out-of-sample decay: PF 1.10–1.25.
- **Memory:** see `project_kz_hunt_filter_set_2026_05_05.md` and `project_kz_hunt_exit_optimum.md`.

### Quantum London — rebuilt 2026-05-05 as FF mean-reversion (#743125)
- Replaces the prior 7p/5p/18p grid-EA-derivative version that couldn't reproduce its Dukascopy backtest on IC Markets data.
- **EURGBP only**, M5 capture timeframe, 1Hz tick polling. Capture daily open at 22:00 UTC, fade ±40p extension. TP 12.5p, SL 40p (asymmetric R:R per FF design). Force-exit at 21:00 UTC next day (~22hr hold). Limit-order entry at trigger price (not market at ask) to avoid the entry-spread double-tax.
- Validated on IC Markets EURGBP M5 over 8 months: N=26 trades, WR 69%, PF 2.52, +107p, MaxDD 22p, 0 SLs hit. Sample size is the open risk.
- M1 vs M5 fidelity check on overlap window confirmed M5 backtest is structurally accurate (identical results).
- 1% risk, no filters, single trade per session.
- **Memory:** see `project_quantum_london.md`.

### NIGHT_TIDE
- Unchanged from 2026-04-28 deployment. 4 cross pairs (AUDNZD, NZDCAD, AUDCAD, EURCHF), M15, BB(20,2)+RSI(14) mean reversion, 22:00–01:00 UTC summer / 23:00–01:00 winter. Backtest PF 3.03 / WR 75%.

### London Breakout
- Unchanged. GBPUSD H1 with 12–20p Asian range filter.

### Disabled
- HVF (PF 0.06 live), VIPER (10yr neg), LONDON_SWEEP (live neg), TREND_RIDE (PF 0.86 backtest), WEDGE (never went live), ASIAN_GRAVITY (superseded).

## Reconciliation / tracking

**The orphan-partial bug class is structurally eliminated** for the current live setup — no enabled strategy uses split orders anymore. KZ_HUNT was the last one and was switched to single-order on 2026-05-05.

Two patches shipped today as defense-in-depth (still active for any future re-enablement of HVF/Viper):
- `reconciliation.py` skip-set now includes `mt5_ticket_partial` from CLOSED trades too — stops the per-minute "MISSING_IN_DB" warning when a parent's partial outlives it.
- Telegram `/status` and `/trades` cross-check `mt5.positions_get()` against the DB and flag untracked positions as "UNTRACKED — orphan" with their PnL and ticket.

## Bot infrastructure (unchanged from 2026-04-30)

- NSSM service runs as **Administrator** (not LocalSystem) — MT5 inherits user profile + AutoTrading=on. See `feedback_nssm_user_account.md`.
- Per-thread heartbeats every 60s. TRADE_MONITOR_INTERVAL_SEC = 1.
- Memory monitor + 500MB Telegram alert.
- Monthly auto-reboot Saturday 12:00 local via Windows Task Scheduler. Telegram heads-up 5 min before. Bot self-recovers.

## Open questions / next checkpoint

- After **30–50 more KZ_HUNT trades** (~1 month at current 4-pair rate): does PF hold ≥1.10? MaxDD stay under 100p? If yes, the new policy is validated.
- After **20–30 QL trades** (~1 month): does live PF stay above 1.5? Sample-size risk is the main concern.
- If KZ_HUNT entry quality stays high, consider re-adding **CHFJPY** (PF 1.27 in this sample, currently off for "low M30 signal" reason which may have been the score-filter issue all along).
- Forward-test the **+12p vs +20p TP** call. The TP sweep showed +12p has higher PF (1.03) but lower R:R (0.7), making it WR-dependent. If live WR drops below 58% sustainably, switch to +20p (R:R 1.18, breakeven WR ~46%).
- Re-attempt the **MT5 Strategy Tester for QL** later — the EURUSD M1 history timeout was the blocker, requires loading both EURGBP and EURUSD M1 manually in the chart first.
