# HVF Auto-Trader Project Memory

## Project Overview
- HVF (Hunt Volatility Funnel) + Viper automated forex trading bot
- Deployed to VPS: 198.244.245.3 (SSH alias: `hvf-vps`, Windows Server, PowerShell)
- MT5 demo: IC Markets, login 52774919, balance £691 (lost £9 to stale pattern bug, fixed)
- Instruments: EURUSD, NZDUSD, EURGBP, USDCHF, EURAUD
- **Live patterns**: HVF (excl EURUSD) + KZ Hunt (all 5 pairs). Viper DISABLED (net -160p/10yr)
- Tech: Python, MetaTrader5 lib, SQLAlchemy, Telegram alerts
- Repo: https://github.com/emanco/hvf.git (branch: main)

## Key Files
- See [architecture.md](architecture.md) for full file structure
- Core pipeline: zigzag → detect_hvf → score → arm → confirm entry → execute
- Viper pipeline: impulse → retrace → MACD/RSI/EMA200/ADX confirm → arm → entry
- Backtest engine reuses same detector/risk code

## VPS Details
- SSH: `ssh hvf-vps` (alias configured locally)
- Project path: `C:\hvf_trader\` (flat structure, NOT nested hvf_trader/)
- Sync: `scp <local_file> hvf-vps:"C:/hvf_trader/<path>"`
- Python venv at `C:\hvf_trader\venv\`
- **Service**: Windows Scheduled Task "HVF_Bot" (auto-start, restart on failure)
- Setup: `setup_task.ps1` creates task running `main.py`
- **PowerShell**: `&&` invalid, use `;` for chaining commands

---

## Build Phases & Progress

### Phase 1-5: Foundation → Integration — ALL COMPLETE

### Phase 6: Validation — IN PROGRESS
- Backtest engine — DONE, multi-pattern, pattern-specific trailing
- Walk-forward — DONE
- **Demo bot running** — Started 2026-03-06, critical bugs fixed 2026-03-09, clean restart
- Monitoring week: 2026-03-09 to 2026-03-14 (leave running, review next session)
- Backtest results: see [backtest-results.md](backtest-results.md)

### Phase 7: Multi-Pattern Enhancement
- Phase 0 (SHORT bug fix): DONE
- Phase 1 (KLOS): DONE
- Phase 2 (Multi-pattern infra): DONE
- **Phase 3 (Viper): TUNED & LIVE** — SHORT-only, PF 1.50 on EURUSD
- **Phase 4 (KZ Hunt): LIVE** — 100+ trades/pair in backtest, strong contributor
- Phase 5 (London Sweep): CODED — net negative
- Phase 6 (Integration): DONE

### Phase 8: Go Live — NOT STARTED
- Accumulate demo trades, then switch to live credentials

---

## Current LIVE Config — V3 (deployed 2026-03-09, commit 5ade2ea)
```
ENABLED_PATTERNS = ["HVF", "KZ_HUNT"]  # Viper DISABLED
INSTRUMENTS = ["EURUSD", "NZDUSD", "EURGBP", "USDCHF", "EURAUD"]
PATTERN_SYMBOL_EXCLUSIONS = {"HVF": ["EURUSD"]}
MIN_RRR_BY_PATTERN = {"HVF": 1.5, "KZ_HUNT": 1.0}
RISK_PCT_BY_PATTERN = {"HVF": 1.0, "KZ_HUNT": 2.0}
MAX_CONCURRENT_TRADES = 6, PARTIAL_CLOSE_PCT = 0.60
TRAILING: KZ 1.0x ATR, HVF 1.5x ATR
DAILY/WEEKLY/MONTHLY LIMITS: 5%/8%/15%
# KZ Hunt: all 5 pairs (engine — 97% of profit over 10yr)
# HVF: 4 pairs excl EURUSD (quality diversifier)
# Viper disabled: -160p/683T/PF=0.98 over 10yr
```

## V1 Config — Dial back to this at £1,500+
```
RISK_PCT_BY_PATTERN = {"HVF": 1.0, "VIPER": 1.5, "KZ_HUNT": 1.5, "LONDON_SWEEP": 0.5}
MAX_CONCURRENT_TRADES = 5
PARTIAL_CLOSE_PCT = 0.50
TRAILING_STOP_ATR_MULT_BY_PATTERN = {"HVF": 1.5, "VIPER": 2.5, "KZ_HUNT": 1.2, "LONDON_SWEEP": 1.5}
DAILY_LOSS_LIMIT_PCT = 4.0
WEEKLY_LOSS_LIMIT_PCT = 6.0
MONTHLY_LOSS_LIMIT_PCT = 12.0
# Everything else same as V2 (instruments, exclusions, patterns)
# Backtest: 603T, +2766p, £700→£2675 (+282%), MaxDD 6.3%
```

## Key Features
- **Performance Monitor**: hourly health checks (rolling PF, WR, loss streak) with Telegram alerts + 24h cooldown
- **Weekly Summary**: Telegram digest on Sundays 21:00 UTC with per-pattern breakdown
- **PATTERN_SYMBOL_EXCLUSIONS**: per-pattern per-symbol gating

## File Structure Changes
- `backtests/` — runner scripts (`run_bt*.py`)
- `backtests/charts/` — all backtest chart PNGs
- `docs/` — brief.md, architecture.md, backtest-results.md

## Bugs Fixed (2026-03-09, commit 5ade2ea)
- `.get()` crash on TradeRecord in `risk_manager.py` lines 159+238 — used `hasattr` pattern
- Stale pattern confirmation: DB-loaded patterns with no pattern_obj fired on naive price check. Added proximity guard (within 2x stop-distance)
- Stale patterns loaded on startup: added freshness filter using `PATTERN_FRESHNESS_BARS`
- Pattern expiry: `bars_since_detection = len(df)` was always 50. Fixed to use `detected_at` timestamp
- `MAX_SPREAD_PCT_OF_STOP`: 5%→10% (5% blocked normal market spreads)
- DB cleaned: deleted 12 junk INVALIDATION trades + 26 stale Viper patterns. Clean slate.
- **MT5 AutoTrading**: must be enabled via GUI (persists across restarts). `/algotrading` flag in scheduled task.
- **MT5 autostart**: `setup_mt5_autostart.ps1` — scheduled task on boot with 10s delay

## Known Issues
1. **London Sweep net negative**: not enabled
2. **AUDNZD/GBPCHF**: dropped from config
3. **events table missing**: EventLog model exists but table not created on VPS DB

## HVF Optimization Research (2026-03-08) — COMPLETE
- See [backtest-results.md](backtest-results.md) for full details
- AND convergence is CORRECT (OR is net negative). HVF is low-frequency, high-quality.
- Variant E deployed: MIN_RRR=1.5 for HVF (+200p/18T vs +154p/35T)
- GBPJPY/USDJPY/XAUUSD produce zero H1 HVF patterns — may need higher TF
- Viper SHORT-only was profitable short-term but net negative over 10yr

## 10-Year Backtest V3 (2026-03-09) — Dec 2014 to Mar 2026, 11.3 years
**Portfolio: £700 → £282,911 (+40,316%), 6,151T, +20,701p, MaxDD 19.5%, CAGR 70.7%**
- Compounding: position sizes scale with equity (2% KZ risk at current balance)
- 548 trades/year, 63% WR, PF 1.53

| Pair | Trades | Pips | PF | WR | MaxDD | £700 → |
|------|--------|------|----|----|-------|--------|
| EURAUD | 1,286 | +6,620 | 1.43 | 62% | 17.6% | £88,091 |
| USDCHF | 1,200 | +4,086 | 1.60 | 63% | 25.7% | £45,801 |
| NZDUSD | 1,263 | +3,441 | 1.44 | 62% | 30.7% | £52,652 |
| EURUSD | 1,093 | +3,380 | 1.43 | 63% | 25.7% | £35,950 |
| EURGBP | 1,309 | +3,173 | 1.63 | 63% | 24.2% | £63,216 |

| Pattern | Trades | PF | Pips | WR |
|---------|--------|----|------|----|
| KZ Hunt | 5,971 | 1.53 | +19,584 | 62% |
| HVF | 180 | 1.47 | +1,116 | 73% |

**Per-pair HVF breakdown**: EURAUD best (31T/84%WR/PF=2.32/+623p), NZDUSD good (34T/71%/PF=1.78/+309p), EURGBP negative (46T/65%/PF=0.85/-105p)
- Charts: `backtests/charts/bt_10yr_*.png` (combined, per-pair overview, 5 individual)

## Next Steps
1. **Review after monitoring week** (2026-03-14): check logs, trades, any new patterns armed/triggered
2. Expected: ~1-3 KZ Hunt trades/day, HVF every 2-3 weeks
3. **At £1,500**: dial back to V1 config (lower risk, tighter limits)
4. EURGBP HVF is -105p over 10yr — consider excluding
