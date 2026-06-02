---
name: Run backtests locally, not on VPS
description: CSV data exported from VPS to backtests/data/. Run all backtests on Mac for speed. VPS is for live trading only.
type: feedback
originSessionId: 0be8ebfc-c3f1-483c-92eb-9f4a3c668a41
---
Backtest data is cached locally at `backtests/data/` — 9 pairs x H1 (8yr) + M5 (8mo) = 45MB of CSV files. Exported from VPS MT5 as a one-off.

**Why:** VPS is slow over SSH, has module import issues (flat directory layout), and MT5 API calls add latency. Local backtests run in seconds.

**How to apply:** For any new backtest, read from `backtests/data/{SYMBOL}_{TF}.csv`. Only go to the VPS for live trading or to pull fresh data. Re-export periodically if newer data is needed.

**Caveat:** KZ Hunt proper backtest needs full indicator pipeline (ATR, EMA, ADX, volume computed identically to `fetch_and_prepare`). The CSV has raw OHLCV — indicators must be computed locally to match.
