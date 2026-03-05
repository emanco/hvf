# Backtest Results

## Run 3: 4-Pair Diversification Test (2026-03-05)

Added AUDUSD and USDJPY to test whether diversification improves returns at £500.

### Full Backtest (20,000 bars H1, ~2+ years)

| Symbol | Trades | Win Rate | PF | PnL (pips) | Max DD | Notes |
|--------|--------|----------|----|------------|--------|-------|
| EURUSD | 11 | 91% | 3.16 | +109.0 | 1.0% | Unchanged from Run 2 |
| GBPUSD | 6 | 83% | 0.76 | -10.2 | 0.8% | Unchanged from Run 2 |
| AUDUSD | 1 | 100% | inf | +25.4 | 0.0% | Only ~1yr data available |
| USDJPY | 0 | - | - | 0.0 | 0.0% | All lots floor to 0.00 |

#### AUDUSD Trade Detail
- #1: LONG entry=0.62982 exit=0.63169 pips=+25.4 (TRAILING_STOP, score=53)

#### USDJPY Sizing Problem
- pip_value_per_lot=1000 for JPY pairs (vs 10 for USD pairs)
- At £500 / 1% risk / ~60-190 pip stops → raw_lots = 0.0000-0.0001, all floor to 0.00
- Needs ~£3,000+ to trade minimum 0.01 lots

### Walk-Forward (6-month train / 2-month test)

| Symbol | OOS Trades | OOS WR | OOS PF | Positive Windows |
|--------|-----------|--------|--------|-----------------|
| EURUSD | 7 | 57% | 0.48 | 1/16 (6%) |
| GBPUSD | 3 | 33% | 0.13 | 1/16 (6%) |
| AUDUSD | 0 | - | - | 0/4 (0%) |
| USDJPY | 0 | - | - | 0/16 (0%) |

### Conclusion
Diversification does not help at £500. EURUSD is the only viable instrument.
Scaling roadmap: GBPUSD at ~£750, AUDUSD at £1,000+, USDJPY at £3,000+.

---

## Run 2: After Filter Relaxation (2026-03-05)

Changes: convergence 1.5×→1.2×, EMA200 hard gate→soft scorer, RRR 1.5→1.0

### Full Backtest (20,000 bars H1, ~2+ years)

#### EURUSD
- Trades: 11
- Win Rate: 90.9%
- Profit Factor: 3.16
- Total PnL: +109.0 pips
- Max Drawdown: 1.0%
- Avg Score: 50
- All trades LONG
- Trade details:
  - #1: LONG +10.6 pips (TRAILING_STOP, score=55)
  - #2: LONG +10.5 pips (TRAILING_STOP, score=41)
  - #3: LONG +37.8 pips (TRAILING_STOP, score=60)
  - #4: LONG +4.0 pips (TRAILING_STOP, score=44)
  - #5: LONG +12.7 pips (TRAILING_STOP, score=54)
  - #6: LONG +17.7 pips (TARGET_2, score=41)
  - #7: LONG +0.8 pips (TRAILING_STOP, score=53)
  - #8: LONG +25.8 pips (TARGET_2, score=56)
  - #9: LONG +37.4 pips (TRAILING_STOP, score=54)
  - #10: LONG -50.6 pips (STOP_LOSS, score=50)
  - #11: LONG +2.1 pips (TRAILING_STOP, score=43)

#### GBPUSD
- Trades: 6
- Win Rate: 83.3%
- Profit Factor: 0.76
- Total PnL: -10.2 pips
- Max Drawdown: 0.8%
- Trade details:
  - #1: LONG +1.7 pips (TRAILING_STOP, score=43)
  - #2: LONG +6.9 pips (TRAILING_STOP, score=57)
  - #3: LONG +3.8 pips (TRAILING_STOP, score=49)
  - #4: LONG +6.8 pips (TRAILING_STOP, score=45)
  - #5: LONG -42.2 pips (STOP_LOSS, score=44)
  - #6: LONG +12.8 pips (TRAILING_STOP, score=44)

### Walk-Forward (6-month train / 2-month test)

#### EURUSD
- OOS Trades: 7
- Win Rate: 57.1%
- Profit Factor: 0.48
- OOS PnL: -62.0 pips
- Positive windows: 1/16 (6%)
- Active windows: 4/16 (Window 1: -32.4, Window 6: -16.7, Window 7: +26.6, Window 14: -39.6)

#### GBPUSD
- OOS Trades: 3
- Win Rate: 33.3%
- Profit Factor: 0.12
- OOS PnL: -52.1 pips
- Positive windows: 1/16 (6%)
- Active windows: 2/16 (Window 5: +6.9, Window 14: -59.0)

---

## Run 1: Initial Working Backtest (2026-03-05, earlier)

Config at the time: convergence 1.5×, EMA200 hard gate, RRR 1.5

### Full Backtest
- EURUSD: 4 trades, 100% WR, PF=inf, +86.7 pips, 0% DD
- GBPUSD: 1 trade, 100% WR, PF=inf, +6.9 pips, 0% DD

### Walk-Forward
- EURUSD: 2 OOS trades, 50% WR, PF=0.03
- GBPUSD: 1 OOS trade, 100% WR, PF=inf

---

## Key Observations
- Filter relaxation tripled trade count (5→17) while maintaining EURUSD quality (PF 3.16)
- GBPUSD is net negative — many patterns blocked by position sizing, surviving trades less reliable
- Walk-forward PF < 1 for both instruments — concerning but sample sizes too small to be conclusive
- Only LONG patterns found across entire 2+ year dataset — no SHORT HVFs detected
- Most EURUSD exits via TRAILING_STOP (9/11) — system is capturing partial moves, not full targets
- Only 2/11 EURUSD trades hit TARGET_2 — trailing stop is doing most of the work
- The single EURUSD loss (-50.6 pips) was a full stop loss hit — acceptable given 10 wins
- **Diversification finding**: AUDUSD adds 1 trade in 2+ years, USDJPY untradeable at £500
- **Capital scaling**: EURUSD-only at £500, add pairs as account grows (see Run 3)

## Bugs Fixed Before Run 1
1. RRR scoring formula: rrr/10 → rrr/4 (full marks at 4:1 not 10:1)
2. Score threshold: 70 → 40
3. Volume spike multiplier: 1.5 → 1.2
4. Trade clustering: added triggered_pattern_keys set
5. Entry sanity check: skip if price already past target_1
6. Stop distance uses actual bar close, not theoretical entry
