# HVF Auto-Trader — Project Guide

## What This Is
Automated multi-strategy trading bot via MetaTrader 5, spanning forex, crypto, and equity indices. Started as a single KZ Hunt forex bot; now runs a portfolio of independent strategies, each on its own scanner thread. Deployed to a Windows VPS, managed as an NSSM service. Python, SQLAlchemy, Telegram alerts.

## Current State (as of 2026-07-02)
- **Active strategies** (each its own scanner thread; `ENABLED_PATTERNS` for the main loop is now `[]`):
  - **NIGHT_TIDE** — M15 BB+RSI mean reversion on 4 cross pairs (AUDNZD, NZDCAD, AUDCAD, EURCHF), 22:00–01:00 UTC (DST-aware), **1 trade/pair/night** (cap added + validated 2026-07-14), 1% risk. Judge it against the **IC-native baseline: PF ~1.4–1.55, ~60% WR, ~6–11 fills/mo, max DD ~80p** (`scripts/nt_ic_feed_diag.py`) — NOT the Dukascopy backtest PF 2–3 (IC's feed produces ~4x fewer signals). ⚠️ The corrected live record since go-live is **−$69.79 / 19 trades / 32% WR** (as of 2026-07-14) — but this was an **operational failure, not a broken edge**. Two bugs (both fixed 2026-07-14): (1) when IC's deal-lookup lagged, `_detect_night_tide_closes` *assumed* TAKE_PROFIT and booked SL losses as fabricated TP "wins" (3 of 4 estimated-TP trades were really losses) — it now defers to the real deal / reconciliation instead of guessing; (2) no per-night cap let it re-enter a falling market repeatedly (3× AUDNZD, −$225, on 2026-07-14) — capping to 1/pair/night *improved* the IC backtest (PF 1.42→1.55, DD 90→77p, +64p from dropping the ~6% falling-knife re-entries). The strategy's validated edge stands; re-evaluate live on clean data going forward. EURCHF: near-zero setups on IC feed since 2025-10 (expected silence, not a bug).
  - **ASIAN_SESSION_BREAKOUT (ASB)** — Asian-range breakout on **GBPJPY only** (range ≈ true UTC 21:00–04:00, armed 07:00), pending stop orders, EOD force-close 20:00 UTC, research mode at 0.5% risk. ⚠️ **Audited 2026-07-28 (`scripts/asb_fill_audit.py`) — every previously recorded PF for this strategy was inflated by two sim fictions.** Read the audit before trusting any older number here.
    - **Fiction 1, blind-gap fills** (the LBO killer, see negative results): the sim filled pending-stop legs that were un-placeable at 07:00 (IC retcode 10015). ASB *survives* this where LBO didn't — it arms an OCO **bracket**, so an un-placeable leg still leaves the opposite leg valid. Correcting it drops ~36% of trades.
    - **Fiction 2, breakeven-through-market** (bigger): `scripts/asb_eod_traintest.py` models BE12 as `eff_sl = entry_px` unconditionally, but MT5 rejects an SL through the market (retcode 10016), so on exactly the underwater trades BE12 was meant to save the modify **fails**. ~60% of the sim's BE exits were impossible (47/75 GBPJPY). The live code is correct (`_asb_apply_breakeven` retries rather than pretending) — the bug was only ever in the backtest.
    - **Honest 2023+ PF** (arm-check + gap-fill + BE as it really behaves): **GBPJPY 1.36**, USDJPY 1.06, EURUSD 0.77. Versus the naive-model claims of 5.40 / 4.62 / 2.98. The old headline figures — geometry validation PF 1.57/1.64, BE12 train 6.58 / test 3.73, "~1.5× expectancy" — are all **void**. ⚠️ Quote GBPJPY's cost sensitivity **period-explicitly**: recorded-spread → floored-spread is 1.36 → **1.28** on 2023+, and 1.20 → **1.13** on FULL. An earlier version of this line paired the 2023+ 1.36 against the FULL 1.13, which reads as a much larger cost penalty than there is.
    - **USDJPY + EURUSD dropped 2026-07-28**: added on `scripts/pair_extension_screen.py` numbers (5.81 / 3.69) that the audit reproduces *exactly* as its naive-BE row — the screen inherited both fictions. Neither pair ever took a live fill. **`pair_extension_screen.py` was rewritten 2026-07-29** — it now ports the audited `simulate()` verbatim and aborts unless GBPJPY reproduces `asb_fill_audit.py` row E on PF *and* N in both periods and both cost columns. On the fixed screen nothing extends ASB: EURUSD 0.73, USDJPY 0.97, AUDJPY not scorable (M15 history starts 2025); old-vs-honest inflation factors were 5.1× / 5.9× / 10.8×.
    - ⚠️ **GBPJPY's edge is UNPROVABLE, not proven and not dead** (CI analysis 2026-07-29, `scripts/asb_edge_ci.py`, audited `simulate()` reused verbatim with row-E pins 1.36/109 and 1.28/109 reproduced). On the decision column (floored spread, honest BE12, 2023+, N=109): avgR **+0.055**, sd 0.598, SE 0.057, **95% CI [−0.056, +0.166]**; PF 1.28 with **95% CI [0.78, 2.17]**. t=0.96, one-sided p=0.168, so **P(true edge ≤ 0) ≈ 17%** — the evidence leans positive (~83%) but clears no conventional bar. Every variant straddles zero (no-BE +0.071 [−0.054, +0.193]; recorded-spread +0.069 [−0.043, +0.180]).
    - ⚠️ **The 30–50-fill rule cannot settle ASB — retire the idea that it will.** Detecting this effect size at 80% power needs **480–923 trades**; we have 109, and GBPJPY fills at ~2.6/mo = **12–26 years**. 30 more live fills on top of N=109 shrink the SE by ~11%, i.e. nothing. ASB is therefore reclassified from "research mode, collecting evidence" to **permanent small allocation at 0.5%, accepted as unprovable**. Do not re-open this analysis expecting a different answer; the sample size is the binding constraint, not the method.
    - ✅ **Correction: the "flat since 2024" decay story does NOT hold.** An earlier version of this line read the per-year sequence as decay. Per-year (floored, row E): 2023 N=21 PF 1.99 avgR +0.176 [−0.095, +0.431] | 2024 N=25 PF 1.49 +0.096 [−0.142, +0.326] | 2025 N=41 PF 0.75 **−0.064** [−0.255, +0.124] | **2026 N=22 PF 2.04 +0.116** [−0.083, +0.314]. 2026 recovered. 2023–24 vs 2025+ differs by −0.133 with CI **[−0.355, +0.094]**, straddling zero — "decayed" and "one noisy year" are both consistent. Every per-year CI is too wide to read on its own; **do not draw conclusions from single-year ASB rows.**
    - Rough live expectation at 0.5% on ~$37.7k: **+0.055R × ~2.6 fills/mo × $188.50 ≈ +$27/month, monthly sd ≈ $180.** A small positive tilt buried in noise — sized as a lottery ticket, not a conviction position. ⚠️ Note the $30k deposit (2026-07-29) already multiplied ASB's per-trade dollar risk ~5× ($38.50 → $188.50) with no decision taken; the 13 historical trades' $25–44 outcomes understate current exposure.
    - **GBPJPY kept** as the only honest survivor: PF ~1.13–1.49 depending on cost assumption, avgR +0.03..+0.08, N=109 (2023+), ~2.6 fills/mo — thin but real, and *not* dependent on the BE overlay (no-BE scores 1.34). It's also the only pair live is positive on.
    - **BE12 left at 12** deliberately: live already behaves as the honest column, so it's a no-op to leave, not a live risk. Note it therefore silently degrades to "no BE" on affected trades, logging nothing. Unvalidated candidate replacement: **close at market at 12:00 when underwater** (always fillable, unlike an SL through market) — 2023+ GBPJPY 1.49 with DD halved, but found on the same data that killed BE12, so it needs a pre-committed train/test before deploy.
    - **Live so far: −$131.18 / 13 trades / 6W/7L / PF 0.44** — but all of it is dropped EURJPY (2W/7L, −$174.42); **GBPJPY is 4W/0L, +$43.24**. Only 1 trade postdates both era-2 and BE12, so live has not yet tested any of the above.
  - **BTC_DONCHIAN** — daily Donchian (55/20, Turtle S2 variant), trailing exits. **BTCUSD + ETHUSD at 1% risk; JP225 + US500 + USTEC + XAUUSD added 2026-07-29 at 0.5%** (universe extension, `scripts/donchian_universe_screen.py` — incumbent sanity gate passed all 8 pins; screened 24 instruments on the unchanged rule, 4 passed the pre-committed bar incl. the held-out 2022+ test leg). **XAUUSD (PF 2.54, the best candidate) and USTEC (1.59) were held back the same day on account size** — at $7.7k one minimum lot risked 1.23% / 0.85% of equity, so the sizer would have refused every signal and they'd have been *silent no-op* instruments. Unblocked by a deposit to **$37.7k** (2026-07-29) and re-verified against live IC specs at that equity: XAUUSD 0.02 lots (2× min, $165.53 of a $188.65 budget), USTEC 0.20 lots (2× min, $125.80). ⚠️ Sized against the ATR *distribution*, not spot ATR: flooring to `vol_step` can only under-risk, so the live failure mode is the outright **skip** when `raw_lots < vol_min`. At $37.7k XAUUSD still goes silent in **3.6%** of the last 2y of D1 ATR readings (USTEC 0.0%) — and that residual gold blind spot is *adversely selected*, being the high-vol tail where a trend system's big trades live. Full gold p99 coverage needs ~$47k; 3×-min-lot sizing ~$84k. US500/USTEC correlate 0.61 on monthly R — count them as ~1.5 independent bets, not 2. ⚠️ **Those four screen PFs are PRE-FINANCING and none of them survive it intact** (`scripts/donchian_financing_rescore.py`, 2026-07-29 — audited `simulate()` spliced verbatim, all 8 pins reproduced, N identical on/off by assertion). No hvf backtest charges overnight carry, and this strategy holds 20–42 nights. Real-cost PF **2017+ (2022+ test leg)**, financing off → on: **BTCUSD 5.18→4.48 (2.89→2.21), ETHUSD 3.56→3.18 (2.88→2.39), XAUUSD 2.55→2.27 (3.66→3.25) — all still PASS; JP225 1.51→1.19 (1.75→1.47), USTEC 1.59→1.01 (1.62→1.14), US500 1.45→0.76 (1.17→0.67) — all three FAIL the screen's own pre-committed bar.** Pooled 4.13→3.36. **The discriminator is edge size, NOT the carry rate** — carry/night in R spans only ~2× across the six (US500 worst 0.018, JP225 best 0.009) while gross avgR spans ~18× (indices +0.37..+0.49R, gold +1.15, crypto +4.6..+6.6). Carry eats 53–147% of the index edge vs 7–22% of crypto/gold's. Two compounders: carry lands on the *longest holds, which are the winners* (longs run 32–42 nights vs shorts 11–19 under the 20-day trail, and indices are 62–70% long), and there is no offsetting credit (crypto shorts pay exactly 0, **gold shorts are PAID** −0.157R, index shorts still cost 0.38–3.31%/yr). Model validated against real charged deals: the only position held long enough to measure (US500 short, 15 nights) came in at **1.14× the modelled rate**; the ratio converges to ~1 as holds lengthen (2.6 nights → 1.35×, sub-night rows are rollover-rounding noise, not error). ✅ **Decision 2026-07-29: all six KEPT anyway**, deliberately and with the above on record — the reason is "collecting live data on known-marginal instruments", NOT "the screen passed them", because it no longer does. Expected cost of keeping US500 ≈ −$200..−$300/yr at 0.5% on $37.7k. ⚠️ **Do not expect live trades to adjudicate this** — at these fill rates and sd(R), 80% power needs: BTCUSD 21 years, ETHUSD 67, XAUUSD 53, JP225 372, US500 176, **USTEC 5,916**. The instruments most in need of validation are the ones that can never be validated, because a near-zero avgR sits in the denominator. If they are dropped it will be on a pre-committed rule, not on an eyeballed losing streak. 📌 **THE STOP RULE (pre-committed 2026-07-29, before any live fill existed on these instruments; `scripts/donchian_stop_rule.py` prints status).** Scope: **JP225, US500, USTEC only** — BTCUSD/ETHUSD/XAUUSD are NOT rule-bound, they passed post-financing and a false drop there is expensive. **Drop on the FIRST of: (a) cumulative R ≤ −3×sd(R) — US500 −6.3R, USTEC −6.8R, JP225 −10.8R; or (b) N ≥ 25 closed fills with cumulative R < 0.** This is a **spend cap, not an inference rule** — inference is impossible here (see the power numbers above), so the rule caps what we pay to keep the experiment running rather than pretending to detect a bad edge. It **will fire on noise ~50% of the time** (at n=20 the barrier is ~0.67 sd of the cumulative-R distribution) and that is deliberate: a false drop costs ~nothing precisely *because* these instruments have ~0 expected edge, so being trigger-happy is free. Thresholds are sd-scaled so all three carry the same false-fire probability — JP225 swings ~1.7× harder and a flat number would drop it on ordinary variance. Worst case if all three run to the limit: 23.9R ≈ **$4,500 (~12% of the account) over ~4–5 years**; expected outcome if the backtests hold is roughly flat (+$57/yr), so the budget is tail risk, not the base case. Measurement: closed trades only, `opened_at >= 2026-07-29`, **exclude `pnl_estimated=1`**, R = `pnl / (|entry−stop_loss| × lots × dpp)` (`stop_loss` is the initial stop; the trail writes `trailing_sl`) — and **do not read this off the scorecard**, whose era filter hides strategies holding longer than the era. **No re-add without a fresh pre-committed screen** ("it recovered" is not evidence). Not a drop trigger but scheduled: **re-run `donchian_financing_rescore.py` on 2027-07-29** — these fail on the *current* rate environment (index carry 8.35%/yr today), not on a broken pattern, so a fall in financing can legitimately reverse the verdict. Dial the 3× multiplier if that budget is too rich, but dial it **now**, not after a drawdown. **All 12 FX pairs failed badly** (best USDJPY 0.86) — see negative results; do not add FX here. Live so far: **2 trades, both winners, +$106.65** (BTCUSD +$77.17 / ETHUSD +$29.48, closed 07-14 and 07-11 after 41 and 38 days) — but both were the over-risked pre-fix trades (1.39×/1.53×), so ≈+$75 at intended sizing, i.e. +0.71R and +0.25R. Both opened 06-03 so they fall outside the `opened_at >= PERF_GO_LIVE_DATE` era filter and do **not** appear on the scorecard (see Deferred Work). Implementation verified faithful to its sim; honest re-backtest 2026-07-02 (IC data, real spread, live entry timing): **BTC PF 1.76 / ETH PF 3.92, combined CAGR ~7%, maxDD ~11% (2023+)** — not the claimed PF ~5. The 00:01-UTC entry lag (2–3h after broker D1 close) cost a third to half the edge — fixed 2026-07-02: the gate now fires at the broker rollover (~21:00/22:00 UTC), so expect the entry-at-close baseline (BTC PF ~2.6 / ETH ~4.9, 2023+). See `scripts/btc_donchian_honest_bt.py`. **Entry-fill audit 2026-07-28: the sim is CLEAN** — it's close-based (`if row["close"] > row["entry_high"]`), not level-based, so it is structurally immune to the blind-gap fill fiction that killed LONDON_BO, and live matches it (`prior_history` ≡ `.shift(1)`). Two real execution defects were found and fixed instead: (1) the 2026-07-02 rollover gate put detection at ~22:00 UTC, *inside* IC's crypto maintenance close — measured live, detection logs at 22:00:21/23 vs 10018 rejections at 22:00:06–22:00:52 — and a rejected entry was **consumed, never retried** (signal lost outright, strictly worse than the 2–3h lag it replaced); entry now retries up to `MAX_ENTRY_RETRIES=30` ticks and only marks the bar processed once the broker has had its say, with policy skips still consuming the signal. (2) SL and lot size were anchored to the signal D1 *close* and never re-derived from the fill — both live trades over-risked (BTCUSD 1.39×, ETHUSD 1.53×, same night ≈2.7% of equity instead of 2%); the stop now anchors to the pre-trade tick and is re-anchored to the real fill after `order_send`.
- **Disabled / retired**:
  - **LONDON_BREAKOUT (LONDON_BO)** — RETIRED 2026-07-28, do not rebuild. Asian-range breakout, Mon/Tue, GBPUSD + GBPJPY. Live record was **flat: 13 trades, 8W/5L, −$2.95, PF 0.99** (it peaked +$160 on 2026-07-07 and gave it all back — era-2 alone is −$163.26 over 4). The retirement is on evidence, not the drawdown. The PF 1.63 validation (`scripts/lbo_geometry_validation.py`) filled **62% of trades at the breakout level on days the window OPENED through it** — a price that was never available, because the deployed geometry ends its range at 04:00 UTC but doesn't open its window until 08:00, a 4h blind gap. Incumbent PF tracked blind-gap size monotonically (4h/1h/0h → PF 1.75/1.11/0.88, `scripts/lbo_geometry_x_fill.py`); on the zero-gap variant all three fill models converge at ~0.86, which is the family's honest edge. The pre-registered honest-fill re-fit over **960 cells** (geometry × window × TP × SL × band, train pre-2024 / test 2024+, `scripts/lbo_honest_refit.py`) found **8/960 positive on train** (best avgR +0.020), failed the robustness gate (neighbour median avgR −0.152) and the held-out gate (test PF 0.76, avgR −0.114); **2% of the grid positive on test and 0/8 train-positive cells carried over**. Not a parameter miss — ~1.7p round-trip on a ~15p stop is ~0.11R/trade of friction the gross edge never clears (same wall that killed scalping). Config kept for backtest history; flattened clean (no positions/pendings at disable).
  - **NR7_BREAKOUT** — RETIRED 2026-07-02, do not rebuild. The deployed trail wasn't the backtested one (PF ~1.0), and the honest re-backtest of the *backtested* tight variant on IC data killed it too: US500 PF 1.22 full / **0.83 in 2023+**, DE40 1.12 / 0.91 (`scripts/nr7_honest_bt.py`). The claimed PF 5.46/5.74 was stacked optimism — exact fills through gaps both ways, whipsaw days resolved by peeking at the close, flat costs. One live trade ever (-$10.56); flattened clean.
  - **KZ_HUNT** — disabled 2026-05-15. Geometric-validity ablation showed honest PF 0.44 (the apparent edge was fake quick wins from SL-on-profit-side mechanics). Detector/scorer code retained as reference (see KZ Hunt section below).
  - **QUANTUM_LONDON** — retired 2026-06-22 after −$631 lifetime live (PF 0.28). Low-R:R mean-reversion fade needing ~76–85% WR; never survived broker friction. EURCHF instance died 2026-06-04. Config kept for backtest history.
  - **HVF** — retired 2026-06-02 (detector finds ~zero patterns across gold/silver/crypto; algorithm is broken). **Viper**, **London Sweep** — net negative.
- **Account**: IC Markets Demo, ~$37.7k balance, risk per trade varies by strategy (0.5–1%)
- **Account history**: Started $700 (2026-03-06), $10k deposit added 2026-03-31, $30k deposit added 2026-07-29 (to unblock XAUUSD/USTEC — note this rescales every strategy's per-trade dollar risk, since all sizing and all loss limits are % of equity)
- **Go-live date**: 2026-07-16 "era 2" (performance stats + Telegram equity chart ignore trades/snapshots before this; reset from 2026-03-25 after the 2026-07-10..15 overhaul: NIGHT_TIDE fabricated-TP fix + 1/pair/night cap, BTC_DONCHIAN per-tick trail, ASB expiration fix, LONDON_BO 10–22p band. Pre-reset history remains in the DB.)
- **DB caveat**: `trade_records.pnl` is unreliable when `pnl_estimated=1` (deal lookup failed). Exclude estimated trades when ranking strategy performance.

## DO NOT
- Re-enable retired strategies — HVF, Viper, QUANTUM_LONDON, KZ_HUNT are all proven unprofitable live (see Current State for each)
- Change params on research-mode strategies (ASB, NR7_BREAKOUT) until 30–50 clean live fills collected — they're at half-size (0.5%) for exactly this reason. ⚠️ But do NOT read that rule as "wait and the data will decide": for **ASB it never will** (needs 480–923 trades = 12–26 years at 2.6 fills/mo; see ASB in Current State). The rule stops premature tinkering on a *known* edge; it is not a validation path for an edge whose CI straddles zero. Before invoking it, check the power calc — otherwise it silently commits you to an unbounded wait
- Assume more trades will resolve a thin edge without computing the power requirement. `N ≈ 7.85 × sd(R)² / avgR²` for 80% power at α=0.05. ASB: sd 0.598, avgR +0.055 → 923 trades. At avgR +0.05 with sd ~0.6 you need ~900 fills; at +0.15 you need ~100. This one line would have replaced weeks of "collect more data" reasoning
- Increase lot size to "get a bigger edge" — avgR, PF and WR are all measured per unit of risk and are **size-invariant**. Sizing up scales dollars (both directions), variance, drawdown and ruin risk; it does not change edge, and it does not speed up validation either (the t-stat on avgR is size-invariant too). With an estimated mean whose CI straddles zero, the size-optimal answer under parameter uncertainty is at or near **zero**, not larger
- Retire a limit-order strategy by only flipping `enabled: False` — that orphans any filled limit order (not in DB; reconciliation won't adopt it) and leaves resting pending orders. Manually flatten positions + cancel pendings via MT5 after disabling (see QL retirement, 2026-06-22)
- Skip `./deploy.sh` and manually copy files — it handles cache clearing and service restart
- Use `&&` in PowerShell commands on the VPS — use `;` instead
- Call `session.close()` anywhere — thread-local scoped sessions manage their own lifecycle
- Store SQLAlchemy ORM objects in long-lived state — use `_detach_record()` to snapshot into SimpleNamespace
- Trust `mt5.history_deals_get(position=ticket)` on IC Markets — it returns empty OR a wrong non-empty set. Always broad-search filtered by symbol when the by-ticket set lacks the target position. Also pad `date_to` to `now+1d`: `deal.time` is server-time-labelled-UTC ~3h ahead, so a `now(utc)` upper bound drops the freshest deals (see Known Gotchas → IC Markets MT5)
- Derive any *decision* from a PnL that may be estimated (`pnl_estimated=1`) without a path that revises it when the real deal lands. Three bugs in this family so far: NIGHT_TIDE fabricated TP "wins" (fixed 2026-07-14), reconciliation booking a TP win as an SL loss, and the per-pattern circuit breaker banking those phantom losses into a false 48h pause (LONDON_BO/GBPUSD, fixed 2026-07-20 — `revise_pattern_streak` now rebuilds the streak from corrected history and only ever *lifts* a pause)
- Recompute a close PnL from `pips × $10 × lots` anywhere — that flat rate is the pair's *quote* currency, unconverted to the USD account currency. Always read the broker's real `deal.profit`; only fall back to `estimate_fallback_pnl` (account-currency-correct via broker tick specs). `_enforce_night_tide_exits` did this and silently mis-stated every time-based NIGHT_TIDE close on non-USD-quote crosses (AUDCAD/NZDCAD ~+42%, EURCHF ~−19%) — and because these are `pnl_estimated=0` they slipped past every estimated-PnL filter (fixed 2026-07-27, `close_position` returns no `profit` field so the fallback always fired; 8 historical rows corrected)
- Book an SL modification in a backtest without asserting the new SL is on the *legal* side of current price — MT5 rejects an SL through the market (retcode 10016) and the live code just retries, so the sim's "free scratch at entry" never happens. This inflated ASB's BE12 by 4x (see negative results). Applies to every breakeven / trailing / time-stop overlay
- Derive a performance metric from balance/equity deltas without subtracting **non-trading capital flows**. Every equity-derived surface (rolling Sharpe, daily PnL, PnL-since-go-live, the equity chart) read day-over-day balance deltas, so the 2026-07-29 $30k demo deposit booked as a **+388% return day** — rolling Sharpe 4.57, avg daily return +29.8%, which would have held the Sharpe halt/warn alarm inert for a full 60-day window. **A deposit silently disabled a safety net**, and the true figure underneath was Sharpe −2.63. Fixed 2026-07-29: `balance_adjustments` table + `deal_utils.sync_balance_adjustments` (mirrors MT5 `DEAL_TYPE_BALANCE/CREDIT/BONUS`, idempotent on deal ticket, called before each equity snapshot); trading costs (commission, swap) are deliberately NOT excluded — they are real drag. Note the *inverse* risk too: a withdrawal fakes a loss and could trip the breaker.
- Interpolate a broker/gate/exception string into a Telegram HTML alert without `esc()` (`hvf_trader/alerts/telegram_bot.esc`). Telegram's `parse_mode=HTML` rejects the **entire** message on one unknown tag, so a single bare `<` drops the whole alert — it logs an ERROR and the notification you were relying on never arrives. `portfolio_gate`'s `"free margin 22% < floor 25%"` put a `<` at byte 53 of the ASB bracket-blocked alert, so **every margin-floor block since 2026-06-02 was invisible on Telegram** (06-02, 07-27, 07-28 — found and fixed 2026-07-29 at all 5 gate-reason alert sites). Same family as the stale-list bug below: the failure is a monitoring surface going quiet, which looks exactly like "nothing happened".
- Hand-maintain a strategy or instrument list in any user-facing surface — derive it from `config.active_strategy_map()` / `config.BOT_MAGICS` so a retirement propagates automatically. `strategy_scorecard._REFERENCE` had a manual `"active"` tag and still advertised NR7 (retired 07-02) and LONDON_BO (retired 07-28) on 2026-07-29, against backtest PFs the fill audits had voided; because its dot is `live/backtest`, inflated denominators paint healthy strategies red. Fixed 2026-07-29 (rows now come from the config map, references carry provenance, retired-but-with-history shows in a footer). `alert_startup` had the same bug in 2026-07-15
- Mark a signal consumed (`_last_processed_date`, armed-pattern removal, etc.) before the broker has accepted *or* rejected the order. A rejection is retryable and losing the signal costs 100% of that trade; a *policy* skip (circuit breaker, portfolio gate, sub-minimum lots) is not retryable and must consume it. Return an explicit bool from the entry path so the caller can tell the two apart — BTC_DONCHIAN dropped rollover-window entries this way (fixed 2026-07-28)
- Assume a value-per-point when sizing. `btc_donchian_scanner` computed `raw_lots = risk_usd / stop_dist`, i.e. **$1 per price unit per lot** — true for BTCUSD/ETHUSD (contract size 1) and nothing else. Pointing it at the screened universe would have risked ~100% of equity on one XAUUSD trade (dpp 100) and traded JP225 at 1/165th size (dpp 0.0061, below `vol_min` so in practice never). Always derive `trade_tick_value / trade_tick_size` from the instrument, and keep the post-sizing invariant (`lots × stop_dist × dpp <= risk_usd`) — flooring to the broker step can only reduce risk, so a violation *proves* the value-per-point is wrong. Same family as the "pips × $10" rule below. Fixed 2026-07-29
- Add an instrument whose **minimum lot exceeds the risk budget**. The sizer correctly refuses to round up to `vol_min` (2026-07-02 audit), so such an instrument logs a warning and skips every signal forever — a silent no-op that looks deployed. Check `vol_min × stop_dist × dpp <= equity × risk_pct` before adding; this is what kept XAUUSD/USTEC out on 2026-07-29
- Size a retry budget against the **instrument's actual trading hours**, not against the one instrument it was tuned on. BTC_DONCHIAN detects at the broker D1 rollover (00:00 broker), which sits *inside* the daily maintenance close for everything except crypto — measured from M1 bar gaps 2026-07-29: BTCUSD/ETHUSD 23:58→00:00 (**2 min**), XAUUSD/USTEC/US500 23:58→01:00 (**61 min**), JP225 no quotes 00:00–01:00. `MAX_ENTRY_RETRIES = 30` ticks (~30 min) was tuned when crypto was the whole universe, so for the four instruments added 2026-07-29 it expired **30 min before the market reopened** and every signal on them was guaranteed to be abandoned unfilled (`retcode=10018 Market closed`; USTEC SHORT abandoned 21:31 UTC against a 22:00 UTC reopen). Same silent-no-op family as the min-lot trap above — correct sizing, correct detection, zero fills, and it looks deployed. Fixed 2026-07-29: wall-clock `ENTRY_RETRY_WINDOW = 3h` (immune to a `poll_interval_sec` change). ⚠️ Residual, NOT yet scored: those four therefore fill **~1h after the D1 close**, structurally — the bar closes while the market is shut — but `donchian_universe_screen.py` scored them entry-at-close. The 2026-07-02 audit showed a 2–3h entry lag cost BTC a third to half its edge, so this is not obviously negligible on instruments already marginal post-financing
- Send a per-signal alert from inside a **retryable** entry path. The BTC_DONCHIAN detection alert sat before `order_send`, so one signal retried 30x fired 30 identical "SHORT signal (LIVE)" Telegram messages. Alert fatigue on the same channel that carries real fills is a monitoring failure, not cosmetic — gate on a per-signal flag, not on reaching the entry path (fixed 2026-07-29)
- Score a multi-day strategy without charging **overnight financing**. NO hvf backtest models it — `simulate()` charges one round-trip at entry and nothing per night — yet BTC_DONCHIAN holds 20–42 nights and IC's carry is large and direction-asymmetric (crypto longs 20%/yr and shorts exactly 0; **gold shorts are PAID**). It cost the four 2026-07-29 index/metal additions 20–48% of their PF and pushed three below their own bar. Two traps inside the trap: (1) **read `swap_mode` per instrument, never assume** — modes differ on the same account (1=POINTS, 2/3/4=currency per lot, 5/6=annual %), and reading a 20%/yr INTEREST rate as a currency amount produced a 15R fake cost on ETHUSD; (2) **normalise every mode to an annual RATE ON NOTIONAL before carrying it backwards**, then charge `px × rate/360` per bar. Modes 1/2/3/4 quote a *fixed* amount per lot per night; holding that fixed amount constant through history charges today's dollars against a 5× smaller index and inflated USTEC's carry ~5× (1.96R vs the true 0.68R) — the broker republishes the fixed amount as price moves, so the rate is the invariant, not the amount. Sanity-check the result as %/yr of notional (expect ~5–20% on CFDs) and validate against real `deal.swap` on any position held more than ~10 nights
- Promise that "more live trades will tell us" without checking whether the instrument *can* be validated. Compute `N ≈ 7.85 × sd(R)² / avgR²` and divide by the fill rate first. BTC_DONCHIAN at ~5–6 fills/yr needs 21 years (BTCUSD) to 5,916 years (USTEC) — **no instrument in it is live-validatable**, and the near-breakeven ones are the *worst*, since avgR sits in the denominator. Live data does settle execution mechanics (fills, sizing, actual swap charged) in a handful of trades; it does not settle edge here. Same rule as ASB — see the power entry above
- Size a position or set an initial stop off the *signal* price without re-deriving both from the actual fill. BTC_DONCHIAN anchored to the D1 close and over-risked 1.39×/1.53× on its only two live trades (fixed 2026-07-28); KZ_HUNT has always recalculated from fill
- "Fix" NIGHT_TIDE to evaluate completed bar closes — evaluating the forming bar at open is load-bearing (IC-native sim: stub-eval PF 1.42 vs completed-close PF 0.80). See comments in `data_fetcher.py:fetch_ohlcv` and `main.py:_scan_night_tide_instrument`

---

## Architecture

### Threads
The main scanner loop hosts **NIGHT_TIDE and ASB inline** (`_scan_night_tide`, `_scan_asb`, plus the disabled KZ_HUNT and LONDON_BO pipelines — `_scan_london_breakout` is retained but gated off since 2026-07-28). **BTC_DONCHIAN and NR7_BREAKOUT each run their own scanner thread.** QUANTUM_LONDON (`quantum_london_scanner.py`) and ASIAN_GRAVITY (`asian_gravity_scanner.py`) also have dedicated-thread machinery but are both currently disabled.

| Thread | File | Interval | Purpose |
|--------|------|----------|---------|
| Scanner (main) | `main.py:_scanner_loop` | 60s | KZ_HUNT + LONDON_BO pipelines (both disabled) + NIGHT_TIDE / ASB scan/arm/execute, all inline |
| BTC_DONCHIAN | `btc_donchian_scanner.py` | 60s | Daily Donchian on BTCUSD/ETHUSD |
| NR7_BREAKOUT | `nr7_scanner.py` | 60s | Daily NR7 breakout on US500/DE40 |
| Trade Monitor | `trade_monitor.py` | 1s | Partials at T1, trailing stops, invalidation, server-close detection (`TRADE_MONITOR_INTERVAL_SEC=1`; was 30s historically) |
| Health Check | `health_check.py` | 60s | MT5 heartbeat, reconnection with exponential backoff |
| Telegram Commands | `telegram_commands.py` | polling | /status, /health, /trades, /equity, /balance, /closeall |

### Pipeline: Detection to Execution
*(KZ_HUNT-specific — disabled since 2026-05-15. Active strategies have their own simpler detect→arm→execute flows in their respective scanners.)*
```
fetch_and_prepare (H1 OHLCV + ATR/EMA/ADX)
  → KillZoneTracker.update (track session highs/lows)
  → detect_kz_hunt_patterns (rejection candle at KZ extreme)
  → score_kz_hunt (0-100: rejection quality, KZ range, EMA200, volume, timing)
  → score >= 50 → prioritize_signals (best signal per symbol)
  → dedup check (no open trade, no armed pattern, no recent trigger for same symbol+direction)
  → ARM pattern (log to DB + Telegram alert)
  → next cycle: check_entry_confirmation (close past entry price)
  → pre_trade_check (8 risk gates: circuit breaker, margin, spread, RRR, news, lot size)
  → place_market_order (MT5) → recalculate SL from fill → log trade
```

### Trade Management (after entry)
```
Every 30s (trade_monitor):
  1. Check invalidation (KZ extreme revisit, 2hr grace period)
  2. Check T2 hit → full close
  3. Check T1 hit → close 60%, move SL to breakeven
  4. After partial: trail remaining 40% at 1.0x ATR (KZ_HUNT)
```

### Key Files
| File | Role |
|------|------|
| `config.py` | Single source of truth for all parameters |
| `main.py` | Orchestrator — scanner loop, arming, entry execution |
| `trade_monitor.py` | Post-entry management — partials, trailing, closes |
| `order_manager.py` | MT5 order execution — market orders, modify SL, close |
| `reconciliation.py` | DB vs MT5 position sync (3-miss counter before closing) |
| `trade_logger.py` | All DB writes — thread-local sessions via property accessor |
| `models.py` | SQLAlchemy models + engine init with WAL mode + busy_timeout |
| `telegram_bot.py` | Alerts + daily summary with equity chart |
| `circuit_breaker.py` | Daily 5% / weekly 8% / monthly 15% loss limits |
| `risk_manager.py` | 8 pre-trade gates (sequential, all must pass) |
| `kz_hunt_detector.py` | Pattern detection — rejection candles at KZ extremes |
| `kz_hunt_scorer.py` | 5-component scorer (rejection, range, EMA, volume, timing) |
| `killzone_tracker.py` | Tracks session highs/lows per kill zone period |

---

## KZ Hunt Strategy

> **⚠️ DISABLED since 2026-05-15** (honest PF 0.44 — see Current State). The detector/scorer/tracker code and this section are retained as reference and for backtesting, but KZ_HUNT does not trade live. The backtest figures below predate the geometric-validity fix that exposed the real edge as ~zero.

### What It Is
Session-reversal strategy. Price reaches a Kill Zone extreme (session high/low), prints a rejection candle (wick > 2x body), and reverses. Not a Francis Hunt original — it's a composite of his KZ timing concepts, ICT/Smart Money session theory, and TradingView community work. Trade management (partial close + trail) borrowed from Hunt's HVF approach.

### Entry Rules
1. Kill Zone session completes (London 8-11, NY morning 13-15, NY evening 16-20, Asian 0-4 UTC)
2. Price approaches the completed KZ high or low within 0.3x ATR
3. Rejection candle forms: wick > 2x body (bullish rejection at low, bearish at high)
4. Score >= 50/100 (rejection quality + KZ range + EMA200 alignment + volume + session timing)
5. Confirmation: next bar closes past entry price
6. All 8 risk checks pass

### Levels
- **Entry**: Rejection candle close price
- **Stop Loss**: Beyond KZ extreme + 0.5x ATR (widened by spread at execution)
- **Target 1**: Opposite KZ extreme (partial close 60%)
- **Target 2**: 1.5x KZ range from entry (full close)
- **Minimum RRR**: 1.0 (calculated against T2)
- **Minimum stop**: 8 pips (filters noise)

### Invalidation
- If price revisits the KZ extreme we're fading (LONG: KZ low revisit, SHORT: KZ high revisit)
- 2-hour grace period before checking
- Backtested: improves PF from 1.56 to 1.69 (79% of invalidated trades would have been losers)

### Walk-Forward Validation (12m train / 3m test / 3m step, 11.3 years)
| Metric | Value |
|--------|-------|
| OOS trades | 4,656 |
| OOS Win Rate | 61% |
| OOS Profit Factor | 1.53 |
| OOS Total Pips | +13,483 |
| Positive windows | 162/205 (79%) |

Per-pair: EURUSD PF=1.68, NZDUSD PF=1.69, EURGBP PF=1.47, USDCHF PF=1.52, EURAUD PF=1.33.

### Expert Panel Expectations (live vs backtest)
- Expected live PF: 1.15-1.30 (40-60% degradation from backtest 1.53)
- Realistic MaxDD: 28-35%
- 1 pip slippage/trade consumes 31% of edge
- Effective independent bets: 2.5-3.0 (not 6) due to EUR/USD correlation
- Breakeven stop hit rate: 30-40% on trades that reached T1

---

## Deployment

### From Mac (repo root)
```bash
./deploy.sh    # stops bot, uploads, clears __pycache__, restarts
```

### VPS Details
- **Host**: 198.244.245.3 (SSH alias: `hvf-vps`)
- **OS**: Windows Server, PowerShell
- **Path**: `C:\hvf_trader\` (entry point: `main.py`)
- **Python**: `C:\hvf_trader\venv\Scripts\python.exe`
- **Service**: NSSM (`C:\nssm\nssm.exe`) — auto-start on boot, auto-restart on failure (5s delay)

### Bot Control
```powershell
C:\nssm\nssm.exe start HVF_Bot
C:\nssm\nssm.exe stop HVF_Bot
C:\nssm\nssm.exe restart HVF_Bot
C:\nssm\nssm.exe status HVF_Bot
```

### Logs
```powershell
Get-Content C:\hvf_trader\logs\main.log -Tail 20        # all activity
Get-Content C:\hvf_trader\logs\trades.log -Tail 20       # trade events
Get-Content C:\hvf_trader\logs\errors.log -Tail 20       # warnings/errors
Get-Content C:\hvf_trader\logs\service_stdout.log -Tail 20  # NSSM stdout
```

### Quick Health Check (from Mac)
```bash
ssh hvf-vps "C:\nssm\nssm.exe status HVF_Bot; exit 0"
ssh hvf-vps "Get-Content 'C:/hvf_trader/logs/main.log' -Tail 10 -ErrorAction SilentlyContinue; exit 0"
```

### DB Queries (from VPS)
```powershell
C:\hvf_trader\venv\Scripts\python.exe -c "import sqlite3; conn = sqlite3.connect(r'C:\hvf_trader\hvf_trader.db'); cur = conn.cursor(); cur.execute('SELECT id, symbol, direction, pattern_type, status, pnl, pnl_pips FROM trade_records ORDER BY id DESC LIMIT 10'); [print(r) for r in cur.fetchall()]; conn.close()"
```

---

## Known Gotchas

### IC Markets MT5
- `mt5.history_deals_get(position=ticket)` is unreliable — it returns empty *or* a non-empty set that omits the target position's own deals (unrelated recent deals). A `if not deals` guard only falls back on *empty*, so a wrong-but-non-empty result silently defeats it. Always broad-search (`history_deals_get(from, to)`) filtered by symbol whenever the by-ticket set lacks `position_id == ticket`. (`deal_utils._query_deal_history`, hardened 2026-07-27)
- **Deal-history clock skew** — `deal.time` is the broker's server time *labelled* as UTC, ~3h ahead of true UTC (verified 2026-07-27: server 16:50 vs UTC 13:50). A `date_to` of `datetime.now(timezone.utc)` sits *below* the timestamp of any deal closed in the last ~3h, silently excluding the freshest deals — precisely the ones a close/late-update lookup needs. This was the engine behind the estimated-PnL epidemic (deal lookup at close fails → estimated fallback → phantom SL losses feeding the circuit breaker). Fix: pad `date_to` to `now + 1 day` (no real deals live in the future). `deal_utils._query_deal_history`.
- Spread widens significantly outside London/NY sessions — SL spread compensation only applied at entry

### SQLAlchemy / Threading
- **Thread-local sessions**: `TradeLogger._session` is a property calling `get_session()` per access. Never cache the session object.
- **DetachedInstanceError**: ORM objects expire after `session.commit()`. Use `_detach_record()` (main.py:54) to snapshot into SimpleNamespace before storing in long-lived state.
- **Double-close guard**: `log_trade_close` skips if trade already CLOSED — prevents reconciliation overwriting real PnL.
- **WAL mode + busy_timeout=5s**: Set via engine event listener in models.py. Required for concurrent writes from 4 threads.
- **Armed patterns lock**: `threading.Lock` protects `_armed_patterns` list — always acquire before mutation or iteration.

### Reconciliation vs Trade Monitor
- Both detect missing MT5 positions. Trade monitor runs every 1s (2 consecutive misses = close). Reconciliation runs every 60s (3 misses = close).
- Trade monitor gets priority by design — it has better deal history lookup.
- Reconciliation is the safety net for anything trade monitor misses.

### Position Sizing
- Risk manager calculates lots from equity, risk%, and stop distance
- FX conversion for non-USD quoted pairs handled by `_get_quote_to_account_rate()`
- Minimum lot rounding can distort small accounts — $10k+ recommended

---

## Configuration Quick Reference (config.py)

Each strategy is its own dict in `config.py` with an `enabled` flag and its own params. The main-loop pattern list and per-pattern dicts are now keyed by many strategies; the snapshot below reflects the current state:

```
ENABLED_PATTERNS = []                # main-loop patterns (KZ_HUNT) all disabled 2026-05-15
INSTRUMENTS = ["NZDUSD", "EURGBP", "EURJPY", "EURAUD"]   # KZ_HUNT universe (only used if KZ re-enabled)

# Per-strategy dicts (each with "enabled"):
QUANTUM_LONDON       = {"enabled": False, ...}            # retired 2026-06-22
ASIAN_GRAVITY        = {"enabled": False, ...}            # superseded by QL (also retired)
NIGHT_TIDE           = {"enabled": True,  "instruments": ["AUDNZD","NZDCAD","AUDCAD","EURCHF"], "timeframe": "M15", "stop_pips": 12, "risk_pct": 1.0}
ASIAN_SESSION_BREAKOUT = {"enabled": True, "instruments": ["GBPJPY"], "risk_pct": 0.5, "eod_force_close_hour": 20, "breakeven_hour_utc": 12}   # USDJPY+EURUSD dropped 2026-07-28 (fill audit); *_by_symbol overrides removed with them
LONDON_BREAKOUT      = {"enabled": False, "instruments": ["GBPUSD","GBPJPY"], ...}   # RETIRED 2026-07-28
BTC_DONCHIAN         = {"enabled": True,  "instances": ["BTCUSD","ETHUSD"] @1.0%  +  ["JP225","US500","USTEC","XAUUSD"] @0.5%, "entry_lookback_days": 55, "exit_lookback_days": 20}
NR7_BREAKOUT         = {"enabled": False, "instances": ["US500","DE40"], "nr_lookback": 7, "risk_pct": 0.5}   # PAUSED 2026-07-02

# Loss-limit circuit breakers:
DAILY_LOSS_LIMIT_PCT = 10.0    # NOT 5 — widened for demo data collection
WEEKLY_LOSS_LIMIT_PCT = 20.0   # NOT 8
MONTHLY_LOSS_LIMIT_PCT = 30.0  # NOT 15
PERF_GO_LIVE_DATE = "2026-07-16"   # "era 2" reset; kill switch uses PERF_KILL_SWITCH_SINCE (decoupled)

# Portfolio gate (added 2026-07-02, hvf_trader/risk/portfolio_gate.py) —
# called by ALL live strategy entry paths; counts broker positions + resting
# pendings (bot magics), free-margin floor, per-currency cap. Deliberately
# PERMISSIVE while on demo (max_positions 9, exposures 13, margin floor 25%,
# 4 legs/currency) — tighten before real money:
PORTFOLIO_GATE = {"enabled": True, "max_positions": 12, "max_total_exposures": 16,
                  "min_free_margin_pct": 25.0, "max_per_currency": 4}

# ⚠️ Note: MAX_CONCURRENT_TRADES, MAX_SPREAD_PCT_OF_STOP, the news filter and
# min-RRR still live ONLY in risk_manager.pre_trade_check (dead KZ_HUNT-only
# path). Live protection = loss-limit breaker (realized PnL only, DB-sourced)
# + per-pattern 3-loss pause + PORTFOLIO_GATE + each scanner's ad-hoc checks.
```

## Deferred Work (see TODO.md)
- **Era filter hides slow strategies (needs a decision)**: every performance surface filters `opened_at >= PERF_GO_LIVE_DATE`. BTC_DONCHIAN holds ~40 days, so its two winners (opened 06-03, closed 07-11/07-14, +$106.65) appear **nowhere** — the scorecard reads "no closed trades". Any strategy slower than the era length is invisible for a full holding period after each reset. Switching to `closed_at` would fix the display but changes what the kill switch and daily summary count as in-era; **not changed unilaterally** — pick the semantics.
- ~~**XAUUSD / USTEC parked on account size**~~ — RESOLVED 2026-07-29 by a $30k deposit ($7.7k → $37.7k); both deployed at 0.5%. Residual: XAUUSD is still min-lot-chunky and skips signals in the top ~3.6% of its ATR distribution (see BTC_DONCHIAN above). Re-run the sizing block in `scripts/donchian_universe_screen.py` before adding anything further — ATRs move.
- **M8**: RRR 1.0 threshold may be too tight with spread — revisit after 50+ trades
- **L1-L5**: Logging/monitoring polish — low priority
- **Feature backlog**: Correlation guard, alternative SL backtest, regime filter, Monte Carlo, per-pair daily limit
- **Parked (screened, passed, not deployed)**: ~~LBO/EURUSD + LBO/EURGBP marginal passes~~ — void, LBO retired 2026-07-28 and the old `scripts/pair_extension_screen.py` used the same level-fill assumption that inflated it. (ASB/EURUSD was here — deployed 2026-07-24, dropped 2026-07-28.) The rewritten ASB screen (2026-07-29) passes no candidate. **BTC_DONCHIAN extension candidates — `XAUUSD` 2.54, `USTEC` 1.59, `JP225` 1.51, `US500` 1.44** (real-cost PF 2017+, `scripts/donchian_universe_screen.py`, 2026-07-29): passed the pre-committed bar incl. the 2022+ test leg, monthly-R correlation to the incumbents mean 0.07. **Not deployed** — blocked on the portfolio-gate question (peak USD legs 4 vs `max_per_currency: 4`, so the screened portfolio is not the one the bot would run) and on the multiple-comparisons caveat (24 instruments screened; US500/USTEC correlate 0.61 and are near-duplicates — take one, not both).

## Negative results (do not re-explore without a NEW hypothesis)
- **Blind-gap fill fiction (methodology, not a strategy)** — any range-breakout backtest with a time gap between range-end and window-open will award fills AT the level on days the window already opened through it. Live gets neither: a market order chases (worse than the level), a pending stop is rejected outright (IC retcode 10015). This is invisible in the usual checks because **win rate is unaffected — only the payoff degrades**, so PF collapses while every surface metric looks healthy; costs, slippage padding and walk-forward splits do not catch it. It manufactured LONDON_BO's entire PF 1.63 (see retired list). **Before trusting any breakout PF, print the fraction of trades whose first window bar OPENS beyond the level**; if non-trivial, re-run under chase and skip fill models and treat the spread as the real uncertainty band. Prefer zero-blind-gap geometries. Audited 2026-07-28 on **ASB** (`scripts/asb_fill_audit.py`): it survives, because an OCO *bracket* loses only the un-placeable leg where LBO lost the whole trade — the structural lesson is that single-order breakouts are far more exposed than bracketed ones. **`scripts/pair_extension_screen.py` was confirmed contaminated** (it reproduced ASB's inflated numbers exactly) and was **rewritten 2026-07-29**: it now ports `asb_fill_audit.py::simulate` verbatim rather than re-deriving the fill model, judges every verdict on the floored-spread column, and hard-aborts unless the live incumbent reproduces the audit on PF *and* N. **Pattern worth copying to any future screen: pin a known-good incumbent row and exit non-zero on drift** — that gate immediately caught a period-mismatch in the expected values (see ASB in Current State).
- **Stop-modify-through-market fiction (methodology)** — a backtest that moves an SL to a price the market has already passed is modelling an order the broker rejects (MT5: a BUY's SL must sit below Bid, retcode 10016). So a "move SL to entry at hour H" overlay is a **no-op on exactly the trades it was meant to save** — the underwater ones: the sim books a free ~−0.1R scratch, live keeps the original stop and takes the full −1R or recovers. Found 2026-07-28 in ASB's BE12 (`scripts/asb_eod_traintest.py:147`, `eff_sl = entry_px` unconditional): 2023+ PF 5.40 → **1.36** on GBPJPY once corrected, ~60% of BE exits impossible. Worse than the blind gap because it *looks* like prudent risk reduction and **WR drops when you add it** (scratches book as small losses), which reads as an honest tradeoff and disarms suspicion. **The tell we missed: the whole BE-hour family (12/14/16) dominated.** A real edge is hour-specific; a free scratch is available at every hour — if an entire parameter family wins, suspect a mechanical artifact, not robustness. The honest deployable version of "breakeven" for an underwater trade is a **market close** at the current price (always fills), never a scratch at entry.
- **NY-open breakout (London-morning range 08–13 UTC → NY 13–17 breakout)** — screened 2026-07-18 (`scripts/ny_breakout_screen.py`), pre-registered LBO-family geometry, honest costs: EURUSD PF 1.02 (coin flip), GBPUSD PF 0.83, both FAIL all bar legs. The family edge requires a *quiet* accumulation range (Asian); the London morning is an active move NY as often reverses as extends. The 13:00–20:00 UTC session gap stays uncovered deliberately.
- **Scalping (sub-5p targets)** — ruled out 2026-07-18 on cost math: ~1p round-trip on EURUSD needs 60–73% WR to break even (QL needed 76–85% with a 1s scanner and died at PF 0.28); sub-5p targets also can't be honestly validated on bar data. Edge must live above the cost wall (10p+ targets).
- **Donchian 55/20 on FX (all 12 majors/crosses)** — screened 2026-07-29 (`scripts/donchian_universe_screen.py`, incumbent sanity gate passed on all 8 pins). Every pair fails on 2017+ real costs, most catastrophically: EURGBP 0.16, AUDUSD 0.33, GBPUSD 0.39, NZDUSD 0.46 … best is USDJPY 0.86. **Explicitly not a cost artifact** — recorded→2×-stress cost moves these ~2–5% (EURUSD 0.81/0.79/0.77), because a 1×ATR daily stop sits far above the friction wall. Daily-bar trend following on FX is dead over this period, consistent with the post-2010 carry/suppression regime. Don't re-screen FX for this family without a new hypothesis. Same screen also killed **XTIUSD/XBRUSD** on the pre-committed test leg (train 2017–21 PF 2.76/2.60 → test 2022+ 0.77/0.85) and **XAGUSD 1.07, US30 0.89, HK50 0.85, F40 0.79, UK100 0.69, DE40 0.64**.
- **ASB/AUDJPY, LBO/USDJPY** — failed the 2026-07-16 pair screen.

## Backtesting
```bash
# Single pair backtest
python -m hvf_trader.backtesting.run_backtest

# Walk-forward validation
python -m hvf_trader.backtesting.walk_forward

# Invalidation A/B comparison
python backtests/run_bt_invalidation_compare.py
python backtests/analyze_invalidation_fates.py
```

Charts output to `backtests/charts/`.
