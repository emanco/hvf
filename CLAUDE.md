# HVF Auto-Trader — Project Guide

## What This Is
Automated multi-strategy trading bot via MetaTrader 5, spanning forex, crypto, and equity indices. Started as a single KZ Hunt forex bot; now runs a portfolio of independent strategies, each on its own scanner thread. Deployed to a Windows VPS, managed as an NSSM service. Python, SQLAlchemy, Telegram alerts.

## Current State (as of 2026-07-02)
- **Active strategies** (each its own scanner thread; `ENABLED_PATTERNS` for the main loop is now `[]`):
  - **NIGHT_TIDE** — M15 BB+RSI mean reversion on 4 cross pairs (AUDNZD, NZDCAD, AUDCAD, EURCHF), 22:00–01:00 UTC (DST-aware). Best live performer, but judge it against the **IC-native baseline: PF ~1.3–1.5, ~60% WR, ~6–11 fills/mo, max DD ~80p** (2026-07-02 diagnostic) — NOT the Dukascopy backtest PF 2–3 (IC's feed produces ~4x fewer signals; see `scripts/nt_ic_feed_diag.py`). EURCHF: near-zero setups on IC feed since 2025-10 (expected silence, not a bug). 1% risk.
  - **ASIAN_SESSION_BREAKOUT (ASB)** — Asian-range breakout on GBPJPY (EURJPY dropped 2026-06-26), pending stop orders, EOD force-close 20:00 UTC. Research mode at 0.5% risk (collecting 30–50 fills). ⚠️ 2026-07-02 audit: live arms its stops ~3h later (relative to the range) than the backtest that produced PF 1.79 — the live fill population is not the measured one; backtests have no commission. Live so far: 4W/7L, −$162.
  - **LONDON_BREAKOUT (LONDON_BO)** — GBPUSD breakout, Mon/Tue only, H1. 1% risk. The live geometry (a broker-time accident: 4-bar range ≈ UTC 00–04, traded UTC 08–13) was **re-validated 2026-07-02 as the best of 4 variants** on IC data with commission: N=260, PF 1.63, +929p, dd 108p over 8.3y (2023+: PF 1.62). Keep as deployed — the *documented* "00–07 UTC range" variant is breakeven-to-losing; see `scripts/lbo_geometry_validation.py`. Live: 6W/1L +$153.
  - **BTC_DONCHIAN** — daily Donchian (55/20, Turtle S2 variant) on BTCUSD + ETHUSD, trailing exits. 1% risk, LIVE. Implementation verified faithful to its sim; honest re-backtest 2026-07-02 (IC data, real spread, live entry timing): **BTC PF 1.76 / ETH PF 3.92, combined CAGR ~7%, maxDD ~11% (2023+)** — not the claimed PF ~5. The 00:01-UTC entry lag (2–3h after broker D1 close) costs a third to half the edge; moving the daily gate to the broker rollover would recover most of it. See `scripts/btc_donchian_honest_bt.py`.
- **Disabled / retired**:
  - **NR7_BREAKOUT** — PAUSED 2026-07-02. The deployed trailing exit (10-day lowest-low) is not the backtested one (10-day highest-low); the deployed variant re-backtests at PF ~1.04 (no edge) vs the claimed 5.46/5.74. Pending + positions flattened at pause. See config comment for re-enable conditions.
  - **KZ_HUNT** — disabled 2026-05-15. Geometric-validity ablation showed honest PF 0.44 (the apparent edge was fake quick wins from SL-on-profit-side mechanics). Detector/scorer code retained as reference (see KZ Hunt section below).
  - **QUANTUM_LONDON** — retired 2026-06-22 after −$631 lifetime live (PF 0.28). Low-R:R mean-reversion fade needing ~76–85% WR; never survived broker friction. EURCHF instance died 2026-06-04. Config kept for backtest history.
  - **HVF** — retired 2026-06-02 (detector finds ~zero patterns across gold/silver/crypto; algorithm is broken). **Viper**, **London Sweep** — net negative.
- **Account**: IC Markets Demo, ~$7.9k balance, risk per trade varies by strategy (0.5–1%)
- **Account history**: Started $700 (2026-03-06), $10k deposit added 2026-03-31
- **Go-live date**: 2026-03-25 (performance stats ignore trades before this)
- **DB caveat**: `trade_records.pnl` is unreliable when `pnl_estimated=1` (deal lookup failed). Exclude estimated trades when ranking strategy performance.

## DO NOT
- Re-enable retired strategies — HVF, Viper, QUANTUM_LONDON, KZ_HUNT are all proven unprofitable live (see Current State for each)
- Change params on research-mode strategies (ASB, NR7_BREAKOUT) until 30–50 clean live fills collected — they're at half-size (0.5%) for exactly this reason
- Retire a limit-order strategy by only flipping `enabled: False` — that orphans any filled limit order (not in DB; reconciliation won't adopt it) and leaves resting pending orders. Manually flatten positions + cancel pendings via MT5 after disabling (see QL retirement, 2026-06-22)
- Skip `./deploy.sh` and manually copy files — it handles cache clearing and service restart
- Use `&&` in PowerShell commands on the VPS — use `;` instead
- Call `session.close()` anywhere — thread-local scoped sessions manage their own lifecycle
- Store SQLAlchemy ORM objects in long-lived state — use `_detach_record()` to snapshot into SimpleNamespace
- Trust `mt5.history_deals_get(position=ticket)` on IC Markets — it returns empty. Always fall back to broad search
- "Fix" NIGHT_TIDE to evaluate completed bar closes — evaluating the forming bar at open is load-bearing (IC-native sim: stub-eval PF 1.42 vs completed-close PF 0.80). See comments in `data_fetcher.py:fetch_ohlcv` and `main.py:_scan_night_tide_instrument`

---

## Architecture

### Threads
The main scanner loop hosts **NIGHT_TIDE, ASB, and LONDON_BO inline** (`_scan_night_tide`, `_scan_asb`, plus the disabled KZ_HUNT pipeline). **BTC_DONCHIAN and NR7_BREAKOUT each run their own scanner thread.** QUANTUM_LONDON (`quantum_london_scanner.py`) and ASIAN_GRAVITY (`asian_gravity_scanner.py`) also have dedicated-thread machinery but are both currently disabled.

| Thread | File | Interval | Purpose |
|--------|------|----------|---------|
| Scanner (main) | `main.py:_scanner_loop` | 60s | KZ_HUNT pipeline (disabled) + NIGHT_TIDE / ASB / LONDON_BO scan/arm/execute, all inline |
| BTC_DONCHIAN | `btc_donchian_scanner.py` | 60s | Daily Donchian on BTCUSD/ETHUSD |
| NR7_BREAKOUT | `nr7_scanner.py` | 60s | Daily NR7 breakout on US500/DE40 |
| Trade Monitor | `trade_monitor.py` | 30s | Partials at T1, trailing stops, invalidation, server-close detection |
| Health Check | `health_check.py` | 60s | MT5 heartbeat, reconnection with exponential backoff |
| Telegram Commands | `telegram_commands.py` | polling | /status, /health, /trades, /equity, /balance, /closeall |

### Pipeline: Detection to Execution
*(KZ_HUNT-specific — disabled since 2026-05-15. Active strategies have their own simpler detect→arm→execute flows in their respective scanners.)*
```
fetch_and_prepare (H1 OHLCV + ATR/EMA/ADX)
  → KillZoneTracker.update (track session highs/lows)
  → detect_kz_hunt_patterns (rejection candle at KZ extreme)
  → score_kz_hunt (0-100: rejection quality, KZ range, EMA200, volume, timing)
  → score >= 50 → prioritize_signals (best signal per symbol)
  → dedup check (no open trade, no armed pattern, no recent trigger for same symbol+direction)
  → ARM pattern (log to DB + Telegram alert)
  → next cycle: check_entry_confirmation (close past entry price)
  → pre_trade_check (8 risk gates: circuit breaker, margin, spread, RRR, news, lot size)
  → place_market_order (MT5) → recalculate SL from fill → log trade
```

### Trade Management (after entry)
```
Every 30s (trade_monitor):
  1. Check invalidation (KZ extreme revisit, 2hr grace period)
  2. Check T2 hit → full close
  3. Check T1 hit → close 60%, move SL to breakeven
  4. After partial: trail remaining 40% at 1.0x ATR (KZ_HUNT)
```

### Key Files
| File | Role |
|------|------|
| `config.py` | Single source of truth for all parameters |
| `main.py` | Orchestrator — scanner loop, arming, entry execution |
| `trade_monitor.py` | Post-entry management — partials, trailing, closes |
| `order_manager.py` | MT5 order execution — market orders, modify SL, close |
| `reconciliation.py` | DB vs MT5 position sync (3-miss counter before closing) |
| `trade_logger.py` | All DB writes — thread-local sessions via property accessor |
| `models.py` | SQLAlchemy models + engine init with WAL mode + busy_timeout |
| `telegram_bot.py` | Alerts + daily summary with equity chart |
| `circuit_breaker.py` | Daily 5% / weekly 8% / monthly 15% loss limits |
| `risk_manager.py` | 8 pre-trade gates (sequential, all must pass) |
| `kz_hunt_detector.py` | Pattern detection — rejection candles at KZ extremes |
| `kz_hunt_scorer.py` | 5-component scorer (rejection, range, EMA, volume, timing) |
| `killzone_tracker.py` | Tracks session highs/lows per kill zone period |

---

## KZ Hunt Strategy

> **⚠️ DISABLED since 2026-05-15** (honest PF 0.44 — see Current State). The detector/scorer/tracker code and this section are retained as reference and for backtesting, but KZ_HUNT does not trade live. The backtest figures below predate the geometric-validity fix that exposed the real edge as ~zero.

### What It Is
Session-reversal strategy. Price reaches a Kill Zone extreme (session high/low), prints a rejection candle (wick > 2x body), and reverses. Not a Francis Hunt original — it's a composite of his KZ timing concepts, ICT/Smart Money session theory, and TradingView community work. Trade management (partial close + trail) borrowed from Hunt's HVF approach.

### Entry Rules
1. Kill Zone session completes (London 8-11, NY morning 13-15, NY evening 16-20, Asian 0-4 UTC)
2. Price approaches the completed KZ high or low within 0.3x ATR
3. Rejection candle forms: wick > 2x body (bullish rejection at low, bearish at high)
4. Score >= 50/100 (rejection quality + KZ range + EMA200 alignment + volume + session timing)
5. Confirmation: next bar closes past entry price
6. All 8 risk checks pass

### Levels
- **Entry**: Rejection candle close price
- **Stop Loss**: Beyond KZ extreme + 0.5x ATR (widened by spread at execution)
- **Target 1**: Opposite KZ extreme (partial close 60%)
- **Target 2**: 1.5x KZ range from entry (full close)
- **Minimum RRR**: 1.0 (calculated against T2)
- **Minimum stop**: 8 pips (filters noise)

### Invalidation
- If price revisits the KZ extreme we're fading (LONG: KZ low revisit, SHORT: KZ high revisit)
- 2-hour grace period before checking
- Backtested: improves PF from 1.56 to 1.69 (79% of invalidated trades would have been losers)

### Walk-Forward Validation (12m train / 3m test / 3m step, 11.3 years)
| Metric | Value |
|--------|-------|
| OOS trades | 4,656 |
| OOS Win Rate | 61% |
| OOS Profit Factor | 1.53 |
| OOS Total Pips | +13,483 |
| Positive windows | 162/205 (79%) |

Per-pair: EURUSD PF=1.68, NZDUSD PF=1.69, EURGBP PF=1.47, USDCHF PF=1.52, EURAUD PF=1.33.

### Expert Panel Expectations (live vs backtest)
- Expected live PF: 1.15-1.30 (40-60% degradation from backtest 1.53)
- Realistic MaxDD: 28-35%
- 1 pip slippage/trade consumes 31% of edge
- Effective independent bets: 2.5-3.0 (not 6) due to EUR/USD correlation
- Breakeven stop hit rate: 30-40% on trades that reached T1

---

## Deployment

### From Mac (repo root)
```bash
./deploy.sh    # stops bot, uploads, clears __pycache__, restarts
```

### VPS Details
- **Host**: 198.244.245.3 (SSH alias: `hvf-vps`)
- **OS**: Windows Server, PowerShell
- **Path**: `C:\hvf_trader\` (entry point: `main.py`)
- **Python**: `C:\hvf_trader\venv\Scripts\python.exe`
- **Service**: NSSM (`C:\nssm\nssm.exe`) — auto-start on boot, auto-restart on failure (5s delay)

### Bot Control
```powershell
C:\nssm\nssm.exe start HVF_Bot
C:\nssm\nssm.exe stop HVF_Bot
C:\nssm\nssm.exe restart HVF_Bot
C:\nssm\nssm.exe status HVF_Bot
```

### Logs
```powershell
Get-Content C:\hvf_trader\logs\main.log -Tail 20        # all activity
Get-Content C:\hvf_trader\logs\trades.log -Tail 20       # trade events
Get-Content C:\hvf_trader\logs\errors.log -Tail 20       # warnings/errors
Get-Content C:\hvf_trader\logs\service_stdout.log -Tail 20  # NSSM stdout
```

### Quick Health Check (from Mac)
```bash
ssh hvf-vps "C:\nssm\nssm.exe status HVF_Bot; exit 0"
ssh hvf-vps "Get-Content 'C:/hvf_trader/logs/main.log' -Tail 10 -ErrorAction SilentlyContinue; exit 0"
```

### DB Queries (from VPS)
```powershell
C:\hvf_trader\venv\Scripts\python.exe -c "import sqlite3; conn = sqlite3.connect(r'C:\hvf_trader\hvf_trader.db'); cur = conn.cursor(); cur.execute('SELECT id, symbol, direction, pattern_type, status, pnl, pnl_pips FROM trade_records ORDER BY id DESC LIMIT 10'); [print(r) for r in cur.fetchall()]; conn.close()"
```

---

## Known Gotchas

### IC Markets MT5
- `mt5.history_deals_get(position=ticket)` returns empty — always fall back to broad search (`history_deals_get(from_date, now)`) filtered by symbol
- Spread widens significantly outside London/NY sessions — SL spread compensation only applied at entry

### SQLAlchemy / Threading
- **Thread-local sessions**: `TradeLogger._session` is a property calling `get_session()` per access. Never cache the session object.
- **DetachedInstanceError**: ORM objects expire after `session.commit()`. Use `_detach_record()` (main.py:54) to snapshot into SimpleNamespace before storing in long-lived state.
- **Double-close guard**: `log_trade_close` skips if trade already CLOSED — prevents reconciliation overwriting real PnL.
- **WAL mode + busy_timeout=5s**: Set via engine event listener in models.py. Required for concurrent writes from 4 threads.
- **Armed patterns lock**: `threading.Lock` protects `_armed_patterns` list — always acquire before mutation or iteration.

### Reconciliation vs Trade Monitor
- Both detect missing MT5 positions. Trade monitor runs every 30s (2 misses = close). Reconciliation runs every 60s (3 misses = close).
- Trade monitor gets priority by design — it has better deal history lookup.
- Reconciliation is the safety net for anything trade monitor misses.

### Position Sizing
- Risk manager calculates lots from equity, risk%, and stop distance
- FX conversion for non-USD quoted pairs handled by `_get_quote_to_account_rate()`
- Minimum lot rounding can distort small accounts — $10k+ recommended

---

## Configuration Quick Reference (config.py)

Each strategy is its own dict in `config.py` with an `enabled` flag and its own params. The main-loop pattern list and per-pattern dicts are now keyed by many strategies; the snapshot below reflects the current state:

```
ENABLED_PATTERNS = []                # main-loop patterns (KZ_HUNT) all disabled 2026-05-15
INSTRUMENTS = ["NZDUSD", "EURGBP", "EURJPY", "EURAUD"]   # KZ_HUNT universe (only used if KZ re-enabled)

# Per-strategy dicts (each with "enabled"):
QUANTUM_LONDON       = {"enabled": False, ...}            # retired 2026-06-22
ASIAN_GRAVITY        = {"enabled": False, ...}            # superseded by QL (also retired)
NIGHT_TIDE           = {"enabled": True,  "instruments": ["AUDNZD","NZDCAD","AUDCAD","EURCHF"], "timeframe": "M15", "stop_pips": 12, "risk_pct": 1.0}
ASIAN_SESSION_BREAKOUT = {"enabled": True, "instruments": ["GBPJPY","EURJPY"], "risk_pct": 0.5, "eod_force_close_hour": 20}
LONDON_BREAKOUT      = {"enabled": True,  "instrument": "GBPUSD", "days": [0,1], "risk_pct": 1.0}
BTC_DONCHIAN         = {"enabled": True,  "instances": ["BTCUSD","ETHUSD"], "entry_lookback_days": 55, "exit_lookback_days": 20, "risk_pct": 1.0}
NR7_BREAKOUT         = {"enabled": False, "instances": ["US500","DE40"], "nr_lookback": 7, "risk_pct": 0.5}   # PAUSED 2026-07-02

# Loss-limit circuit breakers (the ONLY portfolio-level control actually live):
DAILY_LOSS_LIMIT_PCT = 10.0    # NOT 5 — widened for demo data collection
WEEKLY_LOSS_LIMIT_PCT = 20.0   # NOT 8
MONTHLY_LOSS_LIMIT_PCT = 30.0  # NOT 15
PERF_GO_LIVE_DATE = "2026-03-25"

# ⚠️ 2026-07-02 audit: MAX_CONCURRENT_TRADES, MAX_SPREAD_PCT_OF_STOP, the news
# filter, margin cap, correlation check and min-RRR live ONLY in
# risk_manager.pre_trade_check, which is called from the dead KZ_HUNT paths.
# Every active strategy executes directly and bypasses all of them. Live
# protection = loss-limit breaker (realized PnL only, DB-sourced) +
# per-pattern 3-loss pause + each scanner's own ad-hoc checks. A shared
# portfolio gate (count incl. pending orders + margin + currency exposure)
# is the top structural fix on the backlog.
```

## Deferred Work (see TODO.md)
- **M8**: RRR 1.0 threshold may be too tight with spread — revisit after 50+ trades
- **L1-L5**: Logging/monitoring polish — low priority
- **Feature backlog**: Correlation guard, alternative SL backtest, regime filter, Monte Carlo, per-pair daily limit

## Backtesting
```bash
# Single pair backtest
python -m hvf_trader.backtesting.run_backtest

# Walk-forward validation
python -m hvf_trader.backtesting.walk_forward

# Invalidation A/B comparison
python backtests/run_bt_invalidation_compare.py
python backtests/analyze_invalidation_fates.py
```

Charts output to `backtests/charts/`.
