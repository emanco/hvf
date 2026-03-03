# HVF Auto-Trader — Claude Code Handover
**Date:** March 2026  
**Purpose:** Full context handover so Claude Code can resume building this project on a work laptop connected to an AccuWebHosting VPS.

---

## What We Are Building

A fully automated trading bot based on **Francis Hunt's Hunt Volatility Funnel (HVF)** methodology. The bot:

- Scans multiple financial instruments 24/5 for valid HVF patterns
- Scores each pattern using an AI layer that self-improves nightly
- Executes trades via MetaTrader 5 with professional risk management
- Compounds a £1,000 starting account toward a £5,000/month income
- Eventually monetises as an MQL5 signal subscription service

The realistic timeline to £5,000/month is **18–24 months** via compounding + subscriber growth.

---

## What is HVF

The Hunt Volatility Funnel is a **continuation breakout pattern**:
```
1H ──────────────────────────────────────────┐
     \                                        │ = TARGET (1H-1L from midpoint)
      2H ────────────────────────────────┐    │
           \                             │    │
            3H ─────────────────────────│────┘ ← ENTRY (pending stop above 3H)
             \                          │
         ─────────────────────── 3L ───┘  ← STOP LOSS (just below 3L)
       2L ───────────────────────────────────
  1L ──────────────────────────────────────────
```

### The 6 Rules (All Must Pass)
1. Three descending highs: `1H > 2H > 3H`
2. Three ascending lows: `1L < 2L < 3L`
3. Strict alternation: H → L → H → L → H → L chronologically
4. Funnel must converge (narrow), not broaden
5. A clear prior trend must precede the pattern
6. Volume contracts during funnel, spikes on breakout

### Key Formulas
```python
# LONG SETUP
entry_price  = swing_3H + buffer_pips
stop_loss    = swing_3L - (1.0 * ATR_14)
midpoint     = (swing_3H + swing_3L) / 2
full_range   = swing_1H - swing_1L
target_1     = midpoint + (full_range * 0.5)   # 50% close here
target_2     = midpoint + full_range            # full target
rrr          = (target_2 - entry_price) / (entry_price - stop_loss)
# Only trade if rrr >= 3.0 (typically 5:1 to 13:1)

# SHORT — mirror all of the above
```

### No External Signals Needed
HVF is self-validating. The pending stop order IS the confirmation. Do not add RSI, MACD, or any signal service. The only external input needed is an economic calendar — use **MT5's built-in `mt5.calendar_events()`** (free, already authenticated).

---

## Infrastructure

### VPS
- **Provider:** AccuWebHosting
- **Plan:** Forex VPS 2 — 3GB RAM, 2 vCPU, 40GB SSD, £11.18/month (1-year term)
- **OS:** Windows Server 2019
- **Why 2019:** OpenSSH built-in, most community support, stable, supported until 2029
- **Location:** London (matches IC Markets / Pepperstone server locations)

### One-Time SSH Setup (Do This First After Getting VPS)
RDP in once, open PowerShell as Administrator:
```powershell
# Enable OpenSSH
Add-WindowsCapability -Online -Name OpenSSH.Server~~~~0.0.1.0
Start-Service sshd
Set-Service -Name sshd -StartupType 'Automatic'
New-NetFirewallRule -Name sshd -DisplayName 'OpenSSH Server' `
  -Enabled True -Direction Inbound -Protocol TCP -Action Allow -LocalPort 22

# Set PowerShell as default SSH shell
New-ItemProperty -Path "HKLM:\SOFTWARE\OpenSSH" `
  -Name DefaultShell `
  -Value "C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe" `
  -PropertyType String -Force
```

From your work laptop:
```bash
ssh-keygen -t ed25519 -C "hvf-trader"
ssh-copy-id Administrator@YOUR.VPS.IP
```

Connect Claude Code: **File → Open Remote → SSH → YOUR.VPS.IP**

### Broker
- IC Markets or Pepperstone (ECN/STP account, MT5, London servers)
- Check if broker offers free VPS for active accounts — could eliminate the £11.18 cost

### Total Monthly Costs
| Item | Cost |
|------|------|
| AccuWebHosting VPS | £11.18 |
| Everything else (MT5, Python, Telegram, calendar) | £0 |
| **Total** | **£11.18/mo** |

---

## Project Structure
```
hvf_trader/
├── HANDOVER.md
├── CLAUDE.md                  ← detailed build instructions
├── main.py                    ← orchestrator entry point
├── config.py                  ← all settings (nothing hardcoded elsewhere)
├── requirements.txt
├── .env                       ← credentials (never commit to git)
│
├── detector/
│   ├── hvf_detector.py        ← scipy peak detection + HVF validation
│   ├── klos_detector.py       ← Key Levels of Significance
│   └── pattern_scorer.py      ← 6-component scorer (0-100)
│
├── execution/
│   ├── mt5_connector.py       ← MT5 connection, reconnect, health check
│   ├── order_manager.py       ← place/modify/cancel/close orders
│   └── trade_monitor.py       ← trailing stop + partial close (30s loop)
│
├── risk/
│   ├── position_sizer.py      ← lot size formula
│   ├── risk_manager.py        ← daily cap, max trades, spread/news filters
│   └── portfolio_state.py     ← track open positions and equity
│
├── ai/
│   ├── scorer_v1.py           ← rule-based scorer (use from day 1)
│   ├── scorer_v2.py           ← XGBoost (train after 50 trades)
│   ├── rl_agent.py            ← PPO reinforcement learning
│   ├── gym_env.py             ← custom OpenAI Gym environment
│   └── optimizer.py           ← Optuna nightly hyperparameter search
│
├── data/
│   ├── data_fetcher.py        ← OHLCV from MT5
│   └── news_filter.py         ← mt5.calendar_events() wrapper
│
├── database/
│   ├── models.py              ← SQLAlchemy: trades + snapshots tables
│   ├── trade_logger.py        ← log every order event
│   └── performance.py        ← win rate, Sharpe, drawdown
│
├── alerts/
│   └── telegram_bot.py        ← real-time alerts + daily report
│
├── dashboard/
│   └── app.py                 ← Streamlit monitoring dashboard
│
├── backtesting/
│   ├── backtest_engine.py
│   └── validator.py
│
└── scheduler/
    ├── scan_scheduler.py      ← APScheduler jobs
    └── nightly_loop.py        ← self-improvement at 00:00 UTC
```

---

## config.py — Key Settings
```python
INSTRUMENTS           = ["XAUUSD", "EURUSD", "BTCUSD", "GBPJPY", "US30"]

# HVF Detection
HVF_SWING_ORDER       = 5
HVF_ENTRY_BUFFER_PIPS = 3
HVF_ATR_PERIOD        = 14
HVF_ATR_STOP_MULT     = 1.0
HVF_MIN_RRR           = 3.0

# Risk
RISK_PCT_BASE         = 2.0
RISK_PCT_MAX          = 5.0
RISK_PCT_MIN          = 1.0
DAILY_LOSS_LIMIT_PCT  = 6.0
MAX_CONCURRENT_TRADES = 3

# Trade management
PARTIAL_CLOSE_PCT     = 0.50
TRAILING_STOP_ATR     = 1.5
TRAILING_ACTIVATE_PCT = 0.50

# AI
SCORE_THRESHOLD       = 70
MIN_TRADES_FOR_ML     = 50

# News filter
NEWS_BLOCK_MINUTES    = 30
```

---

## Pattern Scorer — 6 Components

| Component | Points | What It Measures |
|-----------|--------|-----------------|
| Funnel tightness | 25 | `(3H-3L)/(1H-1L)` — tighter = better |
| Volume contraction | 20 | Recent vol vs early funnel vol |
| ATR contraction | 20 | ATR at 3H/3L vs ATR at 1H/1L |
| RRR quality | 20 | Higher RRR = higher score |
| Multi-TF confirmation | 10 | Higher TF trend agrees with direction |
| Session quality | 5 | London/NY overlap scores highest |

Only pass patterns scoring **≥ 70** to execution.

---

## AI Evolution (Do Not Skip Ahead)

| Stage | Activate When | What |
|-------|--------------|------|
| v1 Rule-based | Day 1 | 6-component scorer above |
| v2 XGBoost | After 50 live trades | Trained on actual win/loss data |
| v3 PPO RL agent | After 100+ trades | Maximises risk-adjusted return |

RL agent specs:
- Library: `stable-baselines3` PPO
- State: 15 normalised pattern features
- Actions: Skip / Trade / Trade reduced size
- Reward: Sharpe contribution minus drawdown penalty
- Shadow for 7 days before activating live

---

## Nightly Self-Improvement Loop (00:00 UTC)

1. Pull completed trades from DB
2. Calculate metrics (win rate, Sharpe, max DD, profit factor)
3. Save performance snapshot
4. Send Telegram daily report
5. Run Optuna (100 Bayesian trials) on: risk_pct, score_threshold, ATR mult, trailing trigger, swing_order
6. Backtest new params on rolling 90-day window
7. Promote if new Sharpe beats current by ≥5%
8. Retrain RL agent on all trade data
9. Reject if Sharpe < 1.0 or MaxDD > 25%

---

## Build Order

**Build and test each step before moving to the next:**
```
Step 1:  config.py + .env
Step 2:  database/models.py
Step 3:  data/data_fetcher.py — verify MT5 connection
Step 4:  detector/hvf_detector.py — test on 1 instrument
Step 5:  detector/pattern_scorer.py
Step 6:  risk/position_sizer.py — unit test
Step 7:  execution/mt5_connector.py — DEMO ACCOUNT ONLY
Step 8:  risk/risk_manager.py
Step 9:  execution/order_manager.py
Step 10: execution/trade_monitor.py
Step 11: database/trade_logger.py
Step 12: alerts/telegram_bot.py
Step 13: main.py — full loop on demo
Step 14: backtesting/backtest_engine.py
Step 15: dashboard/app.py
Step 16: ai/scorer_v2.py (after 50 paper trades)
Step 17: ai/gym_env.py + ai/rl_agent.py
Step 18: scheduler/nightly_loop.py
Step 19: Go live with £1,000 real account
```

---

## Go-Live Checklist
```
□ Detector finds known HVFs — manually verify 10+ on TradingView
□ Backtest: Win Rate > 50%, Sharpe > 1.0 over 2 years
□ Lot sizer verified: £1,000 / 2% risk / 50-pip stop = correct lots
□ Pending order triggers correctly on demo
□ SL and TP set on every order simultaneously
□ Partial close at target_1 works (check MT5 positions tab)
□ Trailing stop only moves in trade's favour — never against
□ Daily loss limit triggers, bot pauses at -6%
□ Pending order cancels when 3L breached (long invalidated)
□ All events in database correctly
□ All Telegram alerts fire
□ Dashboard shows correct data
□ Nightly loop completes without errors
□ Minimum 20 demo trades, net positive result
```

---

## Growth & Income Context

**Starting capital:** £1,000 | **VPS cost:** £11.18/mo | **Everything else:** free

| Month | Moderate (22%/mo) |
|-------|------------------|
| 3 | £1,816 |
| 6 | £3,297 |
| 9 | £5,985 |
| 12 | £10,868 |
| 18 | £35,849 |

**Account size needed for £5k/month:** ~£25,000 (at 20% monthly return)  
**Realistic timeline:** 18–20 months at moderate settings

**Withdrawal strategy:**
- Months 1–6: Compound everything
- Months 7–12: Withdraw 25%, compound 75%
- Month 12+: £1,500–2,500/month income growing progressively

---

## Monetisation Roadmap

**Phase 1 — MQL5 Signals (Month 6+)**
- List as signal provider on mql5.com
- Traders auto-copy your live trades
- 100 subscribers × £24/mo = £2,400/month passive

**Phase 2 — Prop Firm (Month 9+)**
- Pass FTMO challenge (~£400 for £50k funded account)
- 80% profit split = £3,000–8,000/month additional

**Phase 3 — MQL5 EA (Month 12+)**
- Rewrite as native MQL5 Expert Advisor
- One-time licence sales £150–400 per copy

---

## instruments Priority

| Instrument | Priority |
|-----------|----------|
| XAUUSD (Gold) | ⭐ Start here |
| EURUSD | ⭐ Start here |
| BTCUSD | Add month 2 |
| GBPJPY | Add month 2 |
| US30 | Add month 3 |

**Start with just XAUUSD and EURUSD.** Prove the system stable before expanding.

---

## Non-Negotiable Rules for Claude Code

1. Never hardcode credentials — use `.env` + `python-dotenv`
2. Every MT5 call needs error handling — check `mt5.last_error()`
3. Every order must have SL set simultaneously — never trade without stop loss
4. Log everything — every pattern, order, score, param change
5. Trailing stop only improves — never move SL against the trade
6. Daily loss limit is sacred — stop at -6%, resume midnight UTC only
7. Demo always first — switch to live only after full checklist passed
8. Build incrementally — each module testable independently
9. Graceful shutdown — catch `KeyboardInterrupt`, close MT5 cleanly
10. Test the detector hardest — wrong detection breaks everything downstream

---

## First Session Steps
```bash
# 1. SSH into VPS
ssh Administrator@YOUR.VPS.IP

# 2. Check Python
python --version   # needs 3.11+
# If missing: download from python.org, install, tick "Add to PATH"

# 3. Create project
mkdir C:\hvf_trader && cd C:\hvf_trader

# 4. Virtual environment
python -m venv venv
venv\Scripts\activate

# 5. Install dependencies
pip install -r requirements.txt

# 6. Create .env with MT5 credentials + Telegram tokens

# 7. Begin Step 1 of Build Order
```

---

## requirements.txt
```
MetaTrader5>=5.0.45
pandas>=2.0.0
numpy>=1.24.0
scipy>=1.10.0
pandas-ta>=0.3.14b
scikit-learn>=1.3.0
xgboost>=1.7.0
stable-baselines3>=2.0.0
gymnasium>=0.29.0
optuna>=3.3.0
backtrader>=1.9.78
sqlalchemy>=2.0.0
streamlit>=1.28.0
python-telegram-bot>=20.0
APScheduler>=3.10.0
requests>=2.31.0
python-dotenv>=1.0.0
plotly>=5.17.0
```

---

## Key Decisions Summary

| Decision | Choice |
|----------|--------|
| Platform | MT5 |
| Broker | IC Markets or Pepperstone |
| VPS | AccuWebHosting Forex VPS 2, London |
| OS | Windows Server 2019 |
| Language | Python 3.11 |
| Database | SQLite → Postgres when scaling |
| RL library | stable-baselines3 PPO |
| Optimiser | Optuna |
| Alerts | Telegram |
| Dashboard | Streamlit |
| Starting capital | £1,000 |
| External signals | None — HVF is self-validating |
| Economic calendar | MT5 built-in `calendar_events()` |

---
