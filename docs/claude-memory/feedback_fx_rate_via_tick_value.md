---
name: FX rate sizing via MT5 tick_value
description: For non-account-currency pairs, derive exchange_rate_to_account from the symbol's own trade_tick_value. The FX-pair lookup approach (e.g. USDJPY for JPY pairs) fails on IC Markets demo even with symbol_select.
type: feedback
originSessionId: d108d06f-19a6-4a24-b018-ab64afebd75e
---
When sizing positions for pairs whose quote currency differs from the account currency (JPY pairs on USD account, AUD/NZD/CAD crosses, EURCHF, etc.), compute `exchange_rate_to_account` from the symbol's own `mt5.symbol_info(sym).trade_tick_value` — not by looking up an auxiliary FX pair like USDJPY.

**Why:** IC Markets demo returns no usable tick for non-traded conversion symbols even after `mt5.symbol_select("USDJPY", True)`. Burned a week of EURJPY/GBPJPY ASB skips (lot_size 0, "Cannot find FX pair for JPY->USD, defaulting to 1.0") before figuring this out. The symbol we're trading is already subscribed, so its tick_value is authoritative.

**How to apply:** In `_get_quote_to_account_rate` (main.py), the primary path now does:
```
pip_value_per_lot = tick_value * (pip_size / tick_size)
fx_rate = pip_value_per_lot / (contract_size * pip_size)
```
The old direct/inverse FX-pair lookup remains as fallback only. Fixed 2026-05-26 (commit 124c031). Verified across all 8 live pairs: GBPJPY/EURJPY = 0.00628, EURCHF = 1.275, AUDCAD/NZDCAD = 0.725, etc. Don't go back to the pair-lookup-first approach.
