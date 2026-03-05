# Backtest Results

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

## Bugs Fixed Before Run 1
1. RRR scoring formula: rrr/10 → rrr/4 (full marks at 4:1 not 10:1)
2. Score threshold: 70 → 40
3. Volume spike multiplier: 1.5 → 1.2
4. Trade clustering: added triggered_pattern_keys set
5. Entry sanity check: skip if price already past target_1
6. Stop distance uses actual bar close, not theoretical entry
