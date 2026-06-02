---
name: London Breakout — current state 2026-04-27
description: GBPUSD Mon/Tue Asian breakout, 12-20p range filter validated as optimal. Strategy is structurally low-frequency (~17 trades/year). 2-week dry spell is regime, not bug.
type: project
originSessionId: b47e514d-24ea-44bd-82fc-3d220690e0f2
---
**Config (live):**
- Instrument: GBPUSD (only pair that worked in original cross-pair test)
- Days: Mon + Tue only
- Asian formation: 00:00–07:00 UTC, range = bid_high − bid_low
- Range filter: **12–20 pips** (validated optimal — see below)
- Range lock at 07:00 UTC
- News filter: windowed 00:00–13:00 UTC (windowed fix shipped 2026-04-22)
- Trading window: 08:00–13:00 UTC
- TP: 1× Asian range from entry
- SL: opposite Asian extreme ± spread
- Risk: 1%
- Pattern type: LONDON_BO

**Architecture:** Integrated into main H1 scanner loop (no separate thread).

**Backtest validation (2026-04-27, 8 years GBPUSD H1, 834 Mon/Tu sessions):**
| Window | Q% | n | WR | PF | Total | DD |
|---|---|---|---|---|---|---|
| 12-15p | 4% | 30 | 70% | 2.44 | +153p | 18p |
| **12-20p (current)** | **17%** | **139** | **65%** | **1.61** | **+471p** | 87p |
| 12-30p | 46% | 381 | 57% | 1.09 | +291p | 277p |
| 20-40p | 54% | 439 | 52% | 0.92 | -353p | 826p |
| 30-50p | 37% | 301 | 50% | 0.93 | -245p | 600p |
| 12+ (no max) | 99% | 793 | 53% | 0.96 | -351p | 935p |

**Strategy edge is monotonically decreasing as Asian range widens.** Above 20p, PF drops below 1.0 (losing). The thesis "compressed Asian range → fresh breakout energy" only holds when the Asian session is genuinely contained. Widening the filter destroys the edge. Comparison scripts: `scripts/lb_range_filter_compare.py`, `scripts/lb_range_window_compare.py`.

**GBPUSD Asian range distribution (current regime):**
- p10=17.4 / p25=22.2 / median=30.8 / p75=41.8 / p90=55.7 pips
- The 12-20p filter rejects ~83% of sessions (correctly)

**Live history:**
- Mon 2026-04-20: bot crashed during formation (`bar_time` Timestamp bug, fixed same day)
- Tue 2026-04-21: range locked at 16p ✓ but news-filter skipped (4 high-impact USD/GBP events all in 00:00-13:00 UTC window)
- Mon 2026-04-27: range 36p — exceeds 20p max → skipped (correct)
- Zero live trades to date

**Key insight: zero trades is normal.** Historical base rate ~17 trades/year (139 trades / 8 years). Current GBPUSD volatility is high (median 30.8p vs <20p needed), so we're at the lower end of the trade-frequency distribution. Patience required, not parameter changes.

**Bug fixes shipped:**
- `bar_time` was `df.index[-1]` (int) → `df["time"].iloc[-1]` (Timestamp). Fixed 2026-04-22.
- News filter: whole-day → windowed 00:00-13:00 UTC. Fixed 2026-04-22.
- Telegram alerts on range-locked + session-skipped (parity with KZ_HUNT/QL).

**Don't change without evidence:**
- Range filter 12-20p validated optimal across 8 years
- Spread adjustment to filter doesn't help (tested 2026-04-27)
- Widening to capture more days actively destroys profitability
