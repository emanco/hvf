---
name: Quiet-Hours BB+RSI scalper — backtest validated 2026-04-28
description: 4-pair M15 mean reversion 22:00-01:00 UTC. Live spread spike at 21:00 UTC found and avoided. PF 3.03 with realistic spreads.
type: project
originSessionId: b47e514d-24ea-44bd-82fc-3d220690e0f2
---
**Strategy**: BB(20,2) + RSI(14) mean reversion at quiet-hours liquidity lows. Trade when M15 close pierces a Bollinger band AND RSI extreme — TP at BB middle, fixed 12p SL, 16-bar (4hr) max hold.

**Pairs**: AUDNZD, NZDCAD, AUDCAD, EURCHF (M15)
**Window**: 22:00-01:00 UTC (originally 21:00-01:00 — see "21:00 spread spike" below)

**Live spread sampling 2026-04-27 → 2026-04-28 (8640 samples, 6 hrs):**

| Hour UTC | AUDCAD | AUDNZD | EURCHF | NZDCAD |
|----------|--------|--------|--------|--------|
| 20 | 1.3p | 1.7p | 1.4p | 1.4p |
| **21** | **12.6p** | **21.7p** | **16.3p** | **15.3p** |
| 22 | 1.3p | 1.4p | 1.4p | 1.3p |
| 23 | 1.3p | 1.7p | 1.4p | 1.5p |
| 0  | 1.3p | 1.5p | 1.5p | 1.4p |
| 1  | 1.3p | 1.5p | 1.4p | 1.3p |

**21:00 UTC spread spike**: median 12-22 pips on all 4 pairs — 10-20× normal — at the daily rollover hour. Backtest used 1.5-2p assumed spread. Trading 21:00 UTC live would obliterate any backtest edge. Mandatory to start window at 22:00 UTC, not 21:00.

**Backtest results (2022-04 → 2026-04, ~4 years, 22:00-01:00 UTC, live-measured spreads):**
- Combined: **n=1318  WR=75%  PF=3.03  Tot=+7825p  DD=79p  MaxCL=5**
- AUDNZD: PF 2.51, +1847p, DD 51p
- NZDCAD: PF 2.36, +2001p, DD 79p
- AUDCAD: PF 3.00, +978p, DD 45p
- EURCHF: PF 4.06, +2999p, DD 54p
- Yearly: positive every year (2022 +663p → 2026 +1648p)

**Comparison vs 21:00-01:00 (same clean-spread assumption):**
- 21-01: 1440 trades, WR 72%, PF 2.59, +7548p, DD 121p
- 22-01: 1318 trades, WR 75%, PF 3.03, +7825p, DD 79p
- Dropping the 21:00 hour: -122 trades, +277p, DD halved. Pure win.

**Strategy details:**
- Long: M15 close < BB lower AND RSI < 30 → buy at close, TP=BB mid, SL=12p
- Short: M15 close > BB upper AND RSI > 70 → sell at close, TP=BB mid, SL=12p
- Skip if (TP-distance / pip) < spread+1 (would lock-in loss)
- Single open trade per symbol at a time
- Force-close after 16 M15 bars (4 hrs)

**Implementation status (2026-04-28)**: Live on VPS as `NIGHT_TIDE` pattern. End-to-end pipework validated with test_mode (single AUDNZD trade opened, manually closed, reconciliation detected close — same SL-fallback caveat as QL when find_close_deal misses, fine in production paths). Production config: 4 pairs, real BB+RSI thresholds, 22-01 UTC window with DST awareness, broker-side TP/SL, scanner-driven force-close at 4hr/window-end.

**Code paths**:
- Detector: `hvf_trader/detector/night_tide.py` (compute_indicators, detect_signal, in_trading_window with DST-aware)
- Scanner: `hvf_trader/main.py:_scan_night_tide` runs in main loop (60s cadence)
- Force-close: `_enforce_night_tide_exits` covers MAX_HOLD (4hr) and WINDOW_END
- Trade monitor skips NIGHT_TIDE (own scanner manages it like QL/LB)

**Tonight (2026-04-28 22:00 UTC = local 23:00, EDT)** is the first real trading session.

**Refs**:
- ForexFactory threads #604951 (Extremely Accurate EA), #641507 (Night Owl)
- Backtest script: `scripts/quiet_hours_bbrsi_backtest.py`
- Spread sampler: `scripts/spread_sampler_vps.py`
- Live spread CSV: `backtests/data/spread_samples_2026-04-27.csv`
