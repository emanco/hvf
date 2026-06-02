---
name: Spread sampler retired — use on-demand snapshot
description: The continuous 24/7 sampler kept dying on bot deploys despite reconnect fixes. Replaced 2026-06-01 with on-demand snapshot script.
type: feedback
originSessionId: d108d06f-19a6-4a24-b018-ab64afebd75e
---

**Decommissioned 2026-06-01 (commit 9acc3dc).** The continuous `spread_sampler_vps.py` died silently on every bot deploy (MT5 terminal teardown raised exceptions the reconnect-on-stale logic didn't catch; auth rate limits also caused trouble). Used the data exactly once in 3 weeks despite ongoing maintenance.

Replaced with `scripts/spread_snapshot.py` — fire-and-report on demand:
```
python C:/hvf_trader/scripts/spread_snapshot.py --minutes 60                                    # all pairs
python C:/hvf_trader/scripts/spread_snapshot.py --minutes 180 --pairs AUDNZD AUDCAD NZDCAD     # NT window check
python C:/hvf_trader/scripts/spread_snapshot.py --minutes 60 --csv C:/hvf_trader/logs/snap.csv # raw samples
```
Output: per-pair mean / p50 / p95 / max spread in pips.

**When to use it:** Evaluating whether a strategy is spread-eaten (e.g. NIGHT_TIDE during its 22-01 UTC window); refreshing backtest harness estimates; ad-hoc broker-spread regime checks.

---

Historical lesson (kept — applies to any future independent MT5 worker):

The MT5 Python lib has no explicit connection-health signal on stale handles. When the bot redeploys, sibling MT5 connections silently break: `mt5.symbol_info_tick(sym)` either returns None for every pair OR raises an exception on the next call. Heartbeats that count loop iterations rather than rows written will mask both cases.

**Pattern to use for any future MT5 sidecar:**
- Wrap the inner `symbol_info_tick` call in try/except.
- Track "every-symbol-returned-None for N batches" and trigger `mt5.shutdown(); mt5.initialize(); mt5.login()`.
- Heartbeats must report **rows actually written**, not loop iterations.
- If running unsupervised: supervise it. NSSM service, watchdog, or systemd-style auto-restart. The snapshot script avoids this by being short-lived.
