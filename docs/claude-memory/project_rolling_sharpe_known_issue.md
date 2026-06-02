---
name: Rolling Sharpe fixed
description: Rolling Sharpe was rewritten 2026-04-15 to use daily equity returns — now reads 3.52 instead of -10.15
type: project
originSessionId: f501baf1-25a0-4127-bd25-05baff95b8a7
---
Rolling Sharpe was broken (using raw pips instead of % returns + bad annualization, producing -10.15). Fixed 2026-04-15 to use daily equity returns from EquitySnapshot table. Now reads 3.52.

**Why:** The old calculation was dimensionally wrong — Sharpe expects percentage returns, not raw pips.
**How to apply:** Rolling Sharpe is now reliable. It's computed in `performance_monitor.py:_check_rolling_sharpe` using `trade_logger.get_daily_equity_returns()`.
