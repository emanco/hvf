# KZ Hunt — Automated Session Reversal Strategy

## The Edge

Institutional forex trading concentrates in predictable time windows — London open, New York morning, New York afternoon, and Asian session. During these "Kill Zones," large players push price to session extremes to trigger retail stop losses and fill their own orders. Once they've filled, price reverses.

KZ Hunt systematically identifies these reversals and trades them.

## How It Works

1. Track the high and low of each Kill Zone session as it forms
2. After the session closes, watch for a rejection candle at the extreme — a bar where price pushed to the session high/low but got slammed back (wick > 2x the body). This is the institutional footprint.
3. Enter on confirmation: the next bar closes past our entry level, proving momentum has shifted
4. Stop loss beyond the Kill Zone extreme (the level institutions defended)
5. First target: the opposite end of the Kill Zone range — close 60%, move stop to breakeven
6. Second target: 1.5x the KZ range — trail the remaining 40% with an ATR-based stop

## Why It Works

It's not predicting direction — it's reading what large players already did. The rejection candle is evidence of institutional activity. We're following their money, not guessing.

## Validated Edge

- **11.3-year walk-forward test** (out-of-sample): 4,656 trades, 61% win rate, 1.53 profit factor, 79% of test windows profitable
- **1-year realistic backtest** with live execution constraints (spread, dedup, cooldowns): 743 trades, 53% win rate, 1.73 profit factor, 6.2% max drawdown
- All 5 traded pairs independently profitable (EURUSD, NZDUSD, EURGBP, USDCHF, EURAUD)

## Risk Management

- 1% equity per trade
- 8-pip minimum stop
- 6 max concurrent positions
- Daily/weekly/monthly circuit breakers
- The partial close at T1 with breakeven stop means roughly half of all triggered trades become risk-free runners

## What to Expect Live

Profit factor around 1.15-1.30 after real-world slippage and spread. Not every month will be green — the backtest shows months with 15-25% win rates even within a profitable year. The edge plays out over hundreds of trades, not dozens.
