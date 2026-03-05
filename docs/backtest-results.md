# Backtest Results (2026-03-05)

## Full Backtest (20,000 bars H1, ~2+ years)

### EURUSD
- Trades: 4
- Win Rate: 100%
- Profit Factor: inf
- Total PnL: +86.7 pips
- Max Drawdown: 0.0%
- All trades LONG

### GBPUSD
- Trades: 1
- Win Rate: 100%
- Profit Factor: inf
- Total PnL: +6.9 pips
- Max Drawdown: 0.0%

## Walk-Forward (6-month train / 2-month test windows)

### EURUSD
- OOS Trades: 2
- Win Rate: 50%
- Profit Factor: 0.03
- Positive windows: 1/16 (6%)

### GBPUSD
- OOS Trades: 1
- Win Rate: 100%
- Profit Factor: inf
- Positive windows: 1/16 (6%)

## Notes
- Very low trade count means these metrics are not statistically significant
- The 100% WR on full backtest is likely due to small sample + survivorship
- Walk-forward shows mixed results (1 win, 1 loss on EURUSD OOS)
- Need 50+ trades minimum for meaningful statistical evaluation
- GBPUSD patterns often blocked by position sizing (lots = 0.00)

## Bugs Fixed Before These Results
1. RRR scoring formula: rrr/10 → rrr/4 (full marks at 4:1 not 10:1)
2. Score threshold: 70 → 40
3. Volume spike multiplier: 1.5 → 1.2
4. Trade clustering: added triggered_pattern_keys set
5. Entry sanity check: skip if price already past target_1
6. Stop distance uses actual bar close, not theoretical entry
