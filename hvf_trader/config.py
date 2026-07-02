"""
HVF Auto-Trader Configuration
All settings and thresholds. Nothing hardcoded elsewhere.
"""

import os

# ─── Bot Identity ─────────────────────────────────────────────────────────────
BOT_NAME = "Sniper Bot"
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# ─── Paths ───────────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).parent
DB_PATH = BASE_DIR / "hvf_trader.db"
LOG_DIR = BASE_DIR / "logs"
LOG_DIR.mkdir(exist_ok=True)

# ─── MT5 Credentials ────────────────────────────────────────────────────────
MT5_LOGIN = int(os.getenv("MT5_LOGIN", "0"))
MT5_PASSWORD = os.getenv("MT5_PASSWORD", "")
MT5_SERVER = os.getenv("MT5_SERVER", "ICMarketsSC-Demo")
MT5_PATH = os.getenv("MT5_PATH", r"C:\Program Files\MetaTrader 5\terminal64.exe")

# ─── Telegram ────────────────────────────────────────────────────────────────
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

# ─── Database ────────────────────────────────────────────────────────────────
DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{DB_PATH}")

# ─── Environment ─────────────────────────────────────────────────────────────
ENVIRONMENT = os.getenv("ENVIRONMENT", "demo")

# ─── Display Timezone ────────────────────────────────────────────────────────
from zoneinfo import ZoneInfo
DISPLAY_TZ = ZoneInfo("Europe/London")  # GMT/BST — used for Telegram display + scheduling

# ─── Instruments ─────────────────────────────────────────────────────────────
INSTRUMENTS = ["NZDUSD", "EURGBP", "EURAUD"]   # 3-pair (EURJPY removed 2026-06-26, KZ disabled). 2026-05-05: was 4-pair subset. EURAUD added back after what-if showed score>=60 filter rescues it (PF 0.96→1.12, biggest total-pip contribution at +117p combined, vs 3-pair +97p). Trade-off: PF 1.51→1.33, DD 38p→65p, MAR 2.54→1.80. More volume for compounding. Dropped EURUSD (still PF 0.82 even with score filter), USDCHF, GBPJPY, CHFJPY.
# XAUUSD: add to INSTRUMENTS when WEDGE or gold-specific KZ_HUNT goes live.
# Currently available for backtesting only.
# Which pattern detectors to run live. Others remain available for backtesting.
ENABLED_PATTERNS = []  # 2026-05-15 PM: KZ_HUNT disabled (definitively this time). Variance + geometric-validity ablation on EURGBP M30 (5 seeds + 1 ablation pair, run_kz_variance_and_geometric.py) measured: with geometric-validity ON (real strategy) mean PF = 0.44 ± 0.02 across 5 seeds; with it OFF (May 12 buggy behaviour) PF = 1.23. The 18 invalid-geometry trades per window contributed +646p (+36p each avg) — they were all fake quick wins from SL-on-profit-side mechanics. Honest expected PF is 0.44 with tight CI, not the 1.19 we acted on. Decision is no longer a coin flip.
PRIMARY_TIMEFRAME = "M30"   # KZ_HUNT switched 2026-04-28 — backtest +57% pips vs H1 over 3yrs
CONFIRMATION_TIMEFRAME = "H4"

# ─── HVF Detection ──────────────────────────────────────────────────────────
ZIGZAG_ATR_MULTIPLIER = 2.0       # Zigzag threshold = ATR% * this multiplier (tuned for meaningful swings)
ATR_PERIOD = 14
EMA_PERIOD = 200
ADX_PERIOD = 14

HVF_ENTRY_BUFFER_PIPS = 3
HVF_ATR_STOP_MULT = 0.5          # SL = 3L - (this * ATR14) (tightened from 1.0 for better RRR)
HVF_MIN_RRR = 1.0                # Global fallback minimum reward:risk ratio
MIN_RRR_BY_PATTERN = {
    "HVF": 1.5,            # Tightened from 1.0→1.5 per backtest variant E (+200p/18T vs +154p/35T)
    "VIPER": 1.0,
    "KZ_HUNT": 0.6,        # 2026-05-06: 1.0→0.6 to match flat 12p TP / ~17p SL geometry (R:R ~0.71). Old 1.0 was rejecting valid setups (errors log showed RRR 0.68/0.72/0.78 rejections that would have been profitable under the new policy).
    "LONDON_SWEEP": 1.0,
    "WEDGE": 1.0,
}

# Detection Filters
WAVE1_MIN_ATR_MULT = 1.5         # Wave 1 range must be > 1.5x ATR14 (relaxed from 2.0)
WAVE3_MAX_DURATION_MULT = 5.0    # Wave 3 duration <= 5x Wave 1 duration (relaxed from 3.0)
ADX_MIN_TREND = 15               # ADX must be > 15 for trend confirmation (relaxed from 20)
PATTERN_EXPIRY_BARS = 100        # Pattern expires if no breakout within N bars (relaxed from 48)
VOLUME_SPIKE_MULT = 1.2          # Entry candle volume must be > 1.2x 20-bar avg (relaxed from 1.5)

# ─── KLOS (Key Levels of Significance) ────────────────────────────────────────
KLOS_CLUSTER_ATR_MULT = 0.3       # Cluster nearby levels within 0.3 * ATR
KLOS_PROXIMITY_ATR_MULT = 0.3     # Entry aligns with key level within 0.3 * ATR
KLOS_REJECTION_ATR_MULT = 0.5     # Opposing key level penalty zone = 0.5 * ATR
KLOS_4H_PIVOT_COUNT = 50          # Number of 4H pivots to consider
KLOS_D1_PIVOT_COUNT = 20          # Number of D1 pivots to consider

# ─── Scoring ─────────────────────────────────────────────────────────────────
SCORE_THRESHOLD = 40              # Minimum score to arm pattern (relaxed from 70→60→40)

# Per-pattern score thresholds
SCORE_THRESHOLD_BY_PATTERN = {
    "HVF": 40,
    "VIPER": 60,
    "KZ_HUNT": 60,    # 2026-05-05: 50→60. Pair+score sweep showed score>=60 + pair subset (NZDUSD/EURGBP/EURJPY) gives PF 1.45 vs 1.03 baseline on 117-trade sample.
    "LONDON_SWEEP": 50,
    "WEDGE": 40,
}

# KZ_HUNT detector mode. Sweep-mode required the bar to actually take out
# the prior KZ extreme. Walk-forward on 3yr M30 (2023-08 to 2026-02, 167
# OOS trades, hardened harness) showed sweep-mode delivers PF 0.52 vs
# legacy 1.20 -- it filters OUT the only edge instead of adding signal.
# Flipped back 2026-05-11.
KZ_HUNT_REQUIRE_SWEEP = False

# KZ_HUNT entry timing. The legacy confirmation requires the next bar to
# CLOSE past the rejection candle's close before firing — by then the move
# is 60-90 min old. With SKIP_CONFIRMATION=True, both the backtest and the
# live bot instead fire when price revisits the rejection bar's close:
# SHORT confirms when bar.high >= entry_price, LONG when bar.low <= entry_price.
# 2026-05-12: enabled live after walk-forward showed PF 1.19 across 334
# trades on EURGBP+NZDUSD (vs hardened-legacy PF 0.55 with confirmation wait).
KZ_HUNT_SKIP_CONFIRMATION = True

# When True (and SKIP_CONFIRMATION=True), KZ_HUNT places a real broker
# pending LIMIT at the rejection close instead of a market order on touch.
# This eliminates adverse slippage drift (live market-on-touch fills ~4-5p
# worse than the limit, which erodes the modeled edge). Mirrors the way
# Quantum London handles its mean-reversion entries.
KZ_HUNT_USE_BROKER_LIMITS = True

# SL buffer beyond the KZ extreme as a multiple of current ATR.
# Default 0.5 was set when KZ_HUNT ran on H1; on M30 (since 2026-04-28)
# ATR is roughly half H1's, so 0.5*ATR produces stops that often fall
# below MIN_STOP_PIPS_BY_PATTERN["KZ_HUNT"]=8 → patterns rejected at the
# gate. Backtest sweep needed before raising this — wider stops reduce
# RRR and change the SL-hit / TP-hit profile.
KZ_HUNT_SL_ATR_BUFFER = 0.5

# Geometric-validity guard. When True, KZHuntPattern.compute_levels short-
# circuits with rrr=0 when the computed SL ends up on the profit side of
# entry (rejection close past kz_extreme + atr_buffer — i.e. the rejection
# didn't return inside the KZ range). Default True. Disable only for
# investigative scripts that measure the historical contribution of the
# invalid-pattern population.
KZ_HUNT_ENFORCE_VALID_GEOMETRY = True

# Per-pattern allowed directions (None = both). SHORT-only Viper is a structural edge:
# forex downside momentum is sharper and more persistent than upside.
ALLOWED_DIRECTIONS_BY_PATTERN = {
    "HVF": None,          # Both LONG and SHORT
    "VIPER": "SHORT",     # SHORT-only — LONGs are net negative across all pairs
    "KZ_HUNT": None,
    "LONDON_SWEEP": None,
    "WEDGE": None,        # Both — rising wedge=SHORT, falling wedge=LONG
}

# Per-pattern per-symbol exclusions.
# EURUSD: HVF+Viper are net negative over 10yr (-180p). KZ Hunt is +3616p/PF=1.27.
# Viper net negative on EURGBP, NZDUSD, EURAUD. HVF net negative on EURGBP over 10yr.
PATTERN_SYMBOL_EXCLUSIONS = {
    "VIPER": ["EURGBP", "NZDUSD", "EURAUD", "EURUSD"],
    "HVF": ["EURUSD", "EURGBP"],  # EURGBP HVF net negative (-105p/10yr, PF=0.85)
}

# ─── Multi-Pattern Indicators ───────────────────────────────────────────────
RSI_PERIOD = 14
MACD_FAST = 12
MACD_SLOW = 26
MACD_SIGNAL = 9

# ─── Viper Regime Filter ──────────────────────────────────────────────────
VIPER_REGIME_EMA_LOOKBACK = 20     # Bars to measure EMA200 slope
VIPER_REGIME_EMA_SLOPE_THRESHOLD = 0.0002  # Minimum slope for penalty/bonus
VIPER_REGIME_ADX_THRESHOLD = 20    # ADX below this = weak trend

# ─── Kill Zones (UTC hours) ─────────────────────────────────────────────────
KILL_ZONES_UTC = {
    "london": (8, 11),          # London open session
    "ny_morning": (13, 15),     # NY morning / London-NY overlap
    "ny_evening": (16, 20),     # NY afternoon session
    "asian": (0, 4),            # Asian session (Tokyo/Sydney)
}

# ─── Risk Management ────────────────────────────────────────────────────────
RISK_PCT = 1.0                    # 1% per trade (conservative until validated)

# Per-pattern risk percentages
RISK_PCT_BY_PATTERN = {
    "HVF": 1.0,
    "VIPER": 2.0,          # V2 aggressive — PF 1.50+ SHORT-only, push while account is small
    "KZ_HUNT": 0.5,        # 2026-05-15: 1.0 -> 0.5 — halves bleed cost while collecting data under new broker-LIMIT + geometric-fix + skip-conf paths. Re-evaluate after 30-50 fills.
    "LONDON_SWEEP": 0.5,
    "WEDGE": 0.5,          # Conservative — unproven pattern type
}
DAILY_LOSS_LIMIT_PCT = 10.0       # Demo data collection — wider tolerance
WEEKLY_LOSS_LIMIT_PCT = 20.0      # Demo data collection — wider tolerance
MONTHLY_LOSS_LIMIT_PCT = 30.0     # Demo data collection — wider tolerance
MAX_CONCURRENT_TRADES = 6         # V2 aggressive — 6 × 2% = 12% max simultaneous risk
MAX_SPREAD_PCT_OF_STOP = 0.10     # 10% of stop distance max (5% blocked normal market spreads)
MAX_SPREAD_ABSOLUTE = 0.00020     # 2 pips — normal spreads always pass regardless of stop size
MAX_MARGIN_USAGE_PCT = 0.50       # Never use > 50% free margin

# ─── Trade Management ───────────────────────────────────────────────────────
PARTIAL_CLOSE_PCT = 0.60          # 60/40 split — bank more at T1, better risk-adjusted return (PF 1.79 vs 1.53, MaxDD 10.9% vs 19%)
TRAILING_STOP_ATR_MULT = 1.5     # Trail SL at 1.5x ATR below highest since partial
TARGET_1_MULT = 0.5              # target_1 = midpoint + full_range * 0.5
TARGET_2_MULT = 1.0              # target_2 = midpoint + full_range * 1.0

# Per-pattern trailing stop multipliers (Viper needs more room than HVF)
TRAILING_STOP_ATR_MULT_BY_PATTERN = {
    "HVF": 1.5,
    "VIPER": 2.0,        # V2 — tighter trail to lock profits faster
    "KZ_HUNT": 0,        # 2026-05-05: disabled. Flat-TP exit policy chosen after sweep on 117 live trades (see project_kz_hunt_exit_optimum.md).
    "LONDON_SWEEP": 1.5,
    "WEDGE": 1.5,        # D1 patterns need more room
}

# Per-pattern flat-TP override. When set, overrides target_1/target_2 with a
# fixed pip distance from entry — disables KZ-extreme-derived dynamic TPs.
# Pairs with SPLIT_ORDER_BY_PATTERN = False to deliver pure broker-side
# TP/SL with no partial close, no trailing, no BE-at-T1.
# 2026-05-05: KZ_HUNT switched to 20p flat after exit-giveback analysis
# (see memory project_kz_hunt_exit_optimum.md). +12p was the local optimum
# but +20p chosen for durability (R:R 1.18 vs 0.7).
FLAT_TP_PIPS_BY_PATTERN = {
    "KZ_HUNT": 12.0,    # 2026-05-05: 20→12. Backtest +12p PF 1.03 (best WR 59%, smallest DD); 20p was -13p PF 0.99. User chose +12p after side-by-side comparison.
}

# Per-pattern split-order toggle. False = single order with broker-side TP
# at target_1; trade monitor only handles SL/time-exit. True = legacy 60/40
# split (60% partial at T1, 40% trailed). 2026-05-05: KZ_HUNT switched to
# False — flat exits proved superior in backtest.
SPLIT_ORDER_BY_PATTERN = {
    "KZ_HUNT": False,
    "HVF": True,
    "VIPER": True,
    "LONDON_SWEEP": True,
    "WEDGE": True,
}

# Limit-style entry: per-pattern toggle. When enabled, the order request goes
# out with the intended_entry ± LIMIT_TOLERANCE_PIPS as the price and zero
# deviation. MT5 fills at limit-or-better; if drift moves price past the cap,
# the request returns REQUOTE and we skip the trade. Caps adverse slippage
# regardless of how far live drifted from intended (drift gate already filters
# the worst cases; this caps the residual).
LIMIT_ORDERS_ENABLED_BY_PATTERN = {
    "KZ_HUNT": True,
    "HVF": False,
    "VIPER": False,
    "LONDON_SWEEP": False,
    "WEDGE": False,
}
LIMIT_TOLERANCE_PIPS = 2.0          # Non-JPY pairs
LIMIT_TOLERANCE_PIPS_JPY = 5.0      # JPY crosses

# Memory monitor: alert via Telegram when free physical memory drops below
# this threshold (MB). VPS has 3 GB total; ~900 MB free is normal steady-
# state, so 500 MB is the warning floor (gives ~400 MB cushion before OOM).
# Throttled to one alert per 6 hours.
MEMORY_ALERT_THRESHOLD_MB = 500

# Max deviation pips for market-order fills. Previously hardcoded to 20 points
# in order_manager (=2p on 5-digit, 0.2p on JPY 3-digit — silently slack on
# majors, too tight on JPY). Now converted to points per symbol at runtime.
MAX_DEVIATION_PIPS = 2.0

# Entry-drift gate: refuse to fill when the live price has moved away from
# the pattern's intended entry by more than this many pips. Live KZ_HUNT had
# 6.06p mean adverse drift; this gate skips fills > N pips to recover ~$2,800
# of $3,479 adverse cost. JPY crosses need wider tolerance because their
# session-open spread spikes hit 14p+ on average.
MAX_ENTRY_DRIFT_PIPS = 6.0          # Non-JPY pairs (3p→6p 2026-04-30: M30 confirmation gap is wider than H1; 3p was rejecting 100% of overnight signals).
MAX_ENTRY_DRIFT_PIPS_JPY = 12.0     # JPY crosses (8p→12p, same reasoning + JPY's wider native range).

# Time-stop: force-close trades that have aged past N hours without hitting
# TP or SL. KZ_HUNT: 4 H1 bars (backstop for slow drifters). 0 disables.
TIME_STOP_HOURS_BY_PATTERN = {
    "KZ_HUNT": 0,    # 2026-05-06: 4→0. Time-stop sweep on 62-trade live filtered sample showed 4h was capping +117p potential at +5p (PF 1.01 vs 1.33 at no-stop). Removing aligns with the broker-handles-exits policy.
    "HVF": 0,
    "VIPER": 0,
    "LONDON_SWEEP": 0,
    "WEDGE": 0,
}

# Pre-partial ATR trail: once MFE >= N×ATR_H1, trail SL at N×ATR from peak.
# Combined with BE@50%T1 yields +94p net across 109 live KZ_HUNT trades.
# 0.0 disables for that pattern.
PRE_PARTIAL_TRAIL_ATR_BY_PATTERN = {
    "KZ_HUNT": 0.0,      # 2026-05-05: disabled. Flat-TP exit policy.
    "HVF": 0.0,
    "VIPER": 0.0,
    "LONDON_SWEEP": 0.0,
    "WEDGE": 0.0,
}

# Move SL to breakeven when price reaches N% of the T1 distance from entry.
# 0.0 disables the feature for that pattern. Backtest: BE@50% T1 recovers
# +113p from the SL bucket across 109 live KZ_HUNT trades.
BE_AT_T1_PROGRESS_BY_PATTERN = {
    "KZ_HUNT": 0.0,      # 2026-05-05: disabled. Flat-TP exit policy.
    "HVF": 0.0,
    "VIPER": 0.0,
    "LONDON_SWEEP": 0.0,
    "WEDGE": 0.0,
}

# Per-pattern invalidation toggle. Disabled for KZ_HUNT 2026-04-28 after live
# data showed it net-negative: 25 invalidations, 10 cut would-be winners (TP1
# or TP2), only 13 cut real losers. Net cost -$651 over 25 trades. Backtest
# claimed 79% accuracy; live measured 52%. Backtest-overfit bolt-on.
INVALIDATION_ENABLED_BY_PATTERN = {
    "KZ_HUNT": False,
    "HVF": True,
    "VIPER": True,
    "LONDON_SWEEP": True,
    "WEDGE": True,
}

# Per-pattern freshness (max bars from detection to arming)
PATTERN_FRESHNESS_BARS = {
    "HVF": 100,           # Breakouts can take time
    "VIPER": 10,          # Momentum continuation must be recent
    "KZ_HUNT": 2,         # On M30 (was H1): 2 M30 bars = 60min wall clock — same as H1's 1-bar window. Backtest +57% pips on this combo.
    "LONDON_SWEEP": 12,
    "WEDGE": 72,          # D1 breakouts can take several days to confirm
}

# ─── News Filter ─────────────────────────────────────────────────────────────
# Per-pattern minimum stop distance in pips (rejects patterns with stops in noise range)
MIN_STOP_PIPS_BY_PATTERN = {
    "HVF": 5,
    "KZ_HUNT": 8,        # Lowered from 15 (blocked all KZ entries) — 8 pips still filters noise
    "VIPER": 5,
    "LONDON_SWEEP": 5,
    "WEDGE": 10,          # D1 patterns have wider stops; per-symbol override in MIN_STOP_PIPS_BY_SYMBOL
}

NEWS_BLOCK_MINUTES = 30           # Block trading 30min before/after high-impact
NEWS_CACHE_MAX_AGE_HOURS = 6.0    # Block trading if calendar cache older than this

# ─── Health Check ────────────────────────────────────────────────────────────
HEARTBEAT_INTERVAL_SEC = 30       # MT5 heartbeat check interval
RECONNECT_BASE_DELAY_SEC = 5     # Exponential backoff starting delay
RECONNECT_MAX_DELAY_SEC = 60     # Max backoff delay
RECONNECT_MAX_ATTEMPTS = 10
DISCONNECT_CLOSE_THRESHOLD_SEC = 900  # 15 min = close all positions on reconnect

# ─── Trade Monitor ───────────────────────────────────────────────────────────
TRADE_MONITOR_INTERVAL_SEC = 1    # 1s polling — CPU verified comfortable; per-minute heartbeat log confirms thread is alive

# ─── Performance Monitor ───────────────────────────────────────────────────
PERF_MONITOR_INTERVAL_SEC = 3600      # Check every hour
PERF_ROLLING_TRADE_COUNT = 20         # Rolling window size
PERF_MIN_PF_THRESHOLD = 1.0           # Alert if rolling PF < 1.0
PERF_WIN_RATE_DROP_PCT = 10            # Alert if WR drops >10% from baseline
PERF_MAX_CONSECUTIVE_LOSSES = 5        # Alert at 5+ consecutive losses
PERF_ALERT_COOLDOWN_HOURS = 24         # Don't re-alert same issue for 24h
PERF_ROUTINE_ALERTS_ENABLED = False    # 2026-07-01: silence routine perf/health
                                       # Telegram alerts (PF/WR/Sharpe/loss-streak/
                                       # WR-decay) — noise for strategies already
                                       # being managed. Kill switch is exempt: it
                                       # still runs, trips the breaker, and alerts.
PERF_SHARPE_WINDOW_DAYS = 60           # Rolling Sharpe ratio window
PERF_SHARPE_WARN_THRESHOLD = 0.5       # Sharpe < 0.5 → alert: reduce size
PERF_SHARPE_HALT_THRESHOLD = 0.0       # Sharpe < 0.0 → alert: halt trading
PERF_WR_DECAY_THRESHOLD = 15           # Alert if recent WR drops >15% below all-time WR
PERF_KILL_SWITCH_MIN_TRADES = 200      # Min trades before kill switch can activate
PERF_KILL_SWITCH_MIN_PF = 1.2          # Auto-halt if live PF < this after min trades
PERF_KILL_SWITCH_SINCE = "2026-07-01"  # Kill switch counts trades since THIS date
                                       # only (decoupled from PERF_GO_LIVE_DATE).
                                       # Reset 2026-07-01 after retiring KZ/QL/HVF
                                       # + EURJPY so their pre-cleanup losses can't
                                       # trip the auto-halt on the clean forward
                                       # book. Reporting still uses PERF_GO_LIVE_DATE
                                       # so full history is preserved.
PERF_GO_LIVE_DATE = "2026-03-25"       # Ignore trades before this date for performance stats (reset after bug fixes)
STARTING_EQUITY = 10000.0              # Fallback when MT5 unavailable (current demo account balance)
ACCOUNT_CURRENCY_SYMBOL = "$"          # Fallback display symbol when MT5 unavailable
CURRENCY_SYMBOLS = {"EUR": "€", "USD": "$", "GBP": "£", "JPY": "¥", "CHF": "CHF ", "AUD": "A$", "NZD": "NZ$", "CAD": "C$"}

# ─── Logging ─────────────────────────────────────────────────────────────────
LOG_RETENTION_DAYS = 90
LOG_MAX_BYTES = 10 * 1024 * 1024  # 10 MB per log file
LOG_BACKUP_COUNT = 5

# ─── Session Quality (for scoring) ──────────────────────────────────────────
# UTC hours for trading sessions
LONDON_OPEN = 8
LONDON_CLOSE = 16
NY_OPEN = 13
NY_CLOSE = 21
ASIAN_OPEN = 0
ASIAN_CLOSE = 8

# ─── Backtesting ─────────────────────────────────────────────────────────────
WALKFORWARD_TRAIN_MONTHS = 6
WALKFORWARD_TEST_MONTHS = 2

# ─── Wedge Detection ────────────────────────────────────────────────────────
WEDGE_DETECTION_TIMEFRAME = "D1"        # Primary detection timeframe
WEDGE_MIN_TOUCHES = 2                   # Minimum touches per trendline (quality handled by scorer)
WEDGE_MIN_BARS = 15                     # Minimum pattern duration (D1 bars)
WEDGE_MAX_BARS = 120                    # Maximum pattern duration (D1 bars)
WEDGE_SWING_LOOKBACK = 5               # N-bar lookback for swing detection
WEDGE_MIN_R_SQUARED = 0.65             # Minimum trendline fit quality (relaxed for gold's volatility)
WEDGE_CONVERGENCE_MIN = 0.15           # Lines must converge by at least 15%
WEDGE_BREAKOUT_ATR_BUFFER = 0.1        # Close must exceed trendline by 0.1x ATR
WEDGE_SL_ATR_MULT = 0.5               # SL beyond opposite trendline + ATR buffer
WEDGE_TARGET_1_MULT = 0.5             # T1: 50% of measured move (from midpoint)
WEDGE_TARGET_2_MULT = 1.0             # T2: 100% of measured move (from midpoint)

# ─── Contract Sizes ──────────────────────────────────────────────────────────
# Standard lot size per instrument. Forex = 100,000 currency units (default).
# Metals use different contract sizes.
CONTRACT_SIZES = {
    "XAUUSD": 100,       # 100 troy ounces
    "XAGUSD": 1000,      # 1000 troy ounces (IC Markets)
    # All forex pairs default to 100,000 in position_sizer.py
}

# ─── Per-Symbol Overrides ────────────────────────────────────────────────────
# Max absolute spread (price units). Default MAX_SPREAD_ABSOLUTE used for forex.
MAX_SPREAD_ABSOLUTE_BY_SYMBOL = {
    "XAUUSD": 0.50,      # $0.50 = 50 pips (gold spreads are wider)
    "XAGUSD": 0.05,      # $0.05 for silver
}

# Min stop distance (pips). Overrides MIN_STOP_PIPS_BY_PATTERN when present.
MIN_STOP_PIPS_BY_SYMBOL = {
    "XAUUSD": 300,       # $3.00 minimum stop (gold is volatile)
    "XAGUSD": 50,        # $0.50 minimum stop
}

# ─── Asian Gravity Strategy ─────────────────────────────────────────────────
ASIAN_GRAVITY = {
    "enabled": False,               # Superseded by Quantum London (better params, 95% WR)
    "instrument": "EURGBP",
    "formation_timeframe": "M15",
    "poll_interval_sec": 30,
    "days": [3],
    "formation_start_utc": 0,
    "formation_end_utc": 2,
    "trading_end_utc": 6,
    "forced_exit_utc": 6,
    "trigger_pips": 5,
    "target_pips": 2,
    "stop_pips": 8,
    "max_range_pips": 20,
    "max_spread_pips": 1.5,
    "max_trades_per_session": 1,
    "direction": "SHORT",
    "risk_pct": 2.0,
    "daily_loss_limit_pct": 3.0,
    "kill_switch_consecutive_losses": 2,
}

RISK_PCT_BY_PATTERN["ASIAN_GRAVITY"] = 2.0
MIN_RRR_BY_PATTERN["ASIAN_GRAVITY"] = 0.5
TRAILING_STOP_ATR_MULT_BY_PATTERN["ASIAN_GRAVITY"] = 0
MIN_STOP_PIPS_BY_PATTERN["ASIAN_GRAVITY"] = 3
PATTERN_FRESHNESS_BARS["ASIAN_GRAVITY"] = 1

# ─── Quantum London Strategy ────────────────────────────────────────────────
# Rebuilt 2026-05-05 as faithful FF mean-reversion (thread #743125 by
# Alphaomega). Replaces the prior 7p/5p/18p grid-EA derivative.
# 2026-05-06: extended to multi-instrument with per-pair param sets.
# Each entry in QUANTUM_LONDON["instances"] gets its own scanner thread.
#
# Per-instrument backtests (IC Markets):
#  - EURGBP M5 8mo: 40/12.5/40 → PF 2.52, +107p, 22p DD, 15% fire rate
#  - EURCHF M15 4yr: 20/5/20 → PF 1.23, +468p, 90% fire rate, 85% WR
#    (R:R 0.25, requires high WR; safer 35/10/35 alt would give PF 1.16)
#
# Pair-specific tuning matters: EURCHF is SNB-managed, low volatility,
# tight reverts often → tight params win. EURGBP has bigger ranges → wide
# params catch real reversals, tight ones get noise-shaken.
QUANTUM_LONDON = {
    # RETIRED 2026-06-22: EURCHF instance disabled 2026-06-04 (-$225, low-R:R fade
    # needing ~85% WR). Remaining EURGBP instance (R:R 0.31, needs ~76% WR) was 0/4 on
    # clean live trades and dormant since 2026-05-18. Same fragile design that killed
    # EURCHF. Config kept intact for backtest history.
    "enabled": False,
    "pattern_type": "QUANTUM_LONDON",
    "risk_pct": 1.0,
    "capture_timeframe": "M5",
    "poll_interval_sec": 1,
    "days": [6, 0, 1, 2, 3],            # Sun-Thu capture nights → Mon-Fri trading sessions
    "capture_utc_hour": 22,             # Daily open captured at 22:00 UTC (= 00:00 GMT+2)
    "force_exit_utc_hour": 20,          # Force-close at 20:00 UTC next day (~22hr hold). Avoids IC Markets' 21:00 UTC rollover halt where close orders return retcode 10018.
    "instances": [
        {   # EURGBP — IC Markets 8mo backtest PF 2.52
            "instrument": "EURGBP",
            "trigger_pips": 40,
            "target_pips": 12.5,
            "stop_pips": 40,
        },
        # EURCHF — DISABLED 2026-06-04 after 9 live trades, 4W 5L, net -$266.
        # Structural problems:
        #   - 5p TP / 1.3p spread = 26% friction per win
        #   - 20p SL gives 1:4 R:R; needs ~85% WR after friction
        #   - No news filter; 2 of 9 trades hit full SL on scheduled news
        #     (CHF GDP 06-01, USD ISM Services 06-03)
        # Backtest PF 1.23 over 4 years didn't survive live broker tax and
        # news exposure. EURGBP instance below uses wider 40/12.5/40 params
        # and is kept for now (limited live data).
        # {
        #     "instrument": "EURCHF",
        #     "trigger_pips": 20,
        #     "target_pips": 5,
        #     "stop_pips": 20,
        # },
    ],
}

RISK_PCT_BY_PATTERN["QUANTUM_LONDON"] = QUANTUM_LONDON["risk_pct"]
MIN_RRR_BY_PATTERN["QUANTUM_LONDON"] = 0.2          # spans both 0.71 (EURGBP) and 0.25 (EURCHF)
TRAILING_STOP_ATR_MULT_BY_PATTERN["QUANTUM_LONDON"] = 0  # No trailing — fixed TP/SL
MIN_STOP_PIPS_BY_PATTERN["QUANTUM_LONDON"] = 3      # 5p TP on EURCHF needs lower floor
PATTERN_FRESHNESS_BARS["QUANTUM_LONDON"] = 1
INVALIDATION_ENABLED_BY_PATTERN["QUANTUM_LONDON"] = False

# ─── London Breakout Strategy ───────────────────────────────────────────────
LONDON_BREAKOUT = {
    "enabled": True,
    "instrument": "GBPUSD",
    "days": [0, 1],                 # Monday + Tuesday (0=Mon, 1=Tue)
    "min_range_pips": 12,
    "max_range_pips": 20,
    "tp_multiplier": 1.0,           # TP = 1.0x Asian range from entry
    "exit_hour_utc": 13,            # Force close at 13:00 UTC
    "spread_pips": 1.0,
    "risk_pct": 1.0,
}

RISK_PCT_BY_PATTERN["LONDON_BO"] = LONDON_BREAKOUT["risk_pct"]
MIN_RRR_BY_PATTERN["LONDON_BO"] = 0.5
TRAILING_STOP_ATR_MULT_BY_PATTERN["LONDON_BO"] = 0
MIN_STOP_PIPS_BY_PATTERN["LONDON_BO"] = 10
PATTERN_FRESHNESS_BARS["LONDON_BO"] = 1

# ─── Night Tide Strategy ────────────────────────────────────────────────────
# Quiet-Hours BB+RSI mean reversion on cross pairs.
# Window: 22-01 UTC summer (DST), 23-01 UTC winter (skip NY-rollover spike).
# Backtest 2022-04 → 2026-04: PF 3.17, 76% WR, +7782p, DD 79p (1253 trades).
# IC-native baseline (2026-07-02 diagnostic, scripts/nt_ic_feed_diag.py):
# IC's feed produces ~4x fewer signals than the Dukascopy data the backtests
# ran on (~13.5/mo vs ~50/mo, same detector/months, stable since 2022). Tune
# and judge this strategy against the IC-native expectation — PF ~1.3-1.5,
# ~60% WR, ~6-11 fills/mo across the 4 pairs, max DD ~80p — NOT the Dukascopy
# backtest PF 2-3. EURCHF: near-zero setups on IC feed since 2025-10.
NIGHT_TIDE = {
    "enabled": True,
    "instruments": ["AUDNZD", "NZDCAD", "AUDCAD", "EURCHF"],
    "timeframe": "M15",
    "stop_pips": 12,
    "max_hold_hours": 4,            # 16 M15 bars
    "spread_buffer_pips": 2.0,       # min TP-distance overhead vs spread
    "max_spread_pips": 7.0,          # 2026-05-06: 5→7. Live got 4 fills/30d vs backtest expectation of ~25/mo. Realistic-spread sweep showed PF 1.65 at 5p spread, PF 1.10 at 7p — strategy still profitable at 7p but captures more rollover-spike signals previously rejected. 2026-07-02: that fill-rate gap is now explained — dominant cause is the IC-vs-Dukascopy feed difference (~4x, see header comment), not this gate; don't widen further chasing backtest fill rates.
    "risk_pct": 1.0,                 # 1% per trade — 4 pairs can fire concurrently
    "max_concurrent": 4,
}

RISK_PCT_BY_PATTERN["NIGHT_TIDE"] = NIGHT_TIDE["risk_pct"]
MIN_RRR_BY_PATTERN["NIGHT_TIDE"] = 0.25   # TP = BB-mid, can be tight
TRAILING_STOP_ATR_MULT_BY_PATTERN["NIGHT_TIDE"] = 0
MIN_STOP_PIPS_BY_PATTERN["NIGHT_TIDE"] = 8
PATTERN_FRESHNESS_BARS["NIGHT_TIDE"] = 1

# ─── Asian Session Breakout Strategy ─────────────────────────────────────────
# Backtest 2025-08 to 2026-04 (8mo, hardened harness on M5):
#   GBPJPY+EURJPY 2-pair: PF 1.40, 119 trades, WR 56%, MaxDD 5.4%, +15.5% USD.
#   GBPUSD dropped — PF 0.58 standalone, dragged portfolio.
# Limited backtest sample (8mo only on M5 data). Deploy at 0.5% risk for
# research-mode data collection; re-evaluate after 30-50 live fills.
ASIAN_SESSION_BREAKOUT = {
    "enabled": True,
    # EURJPY dropped 2026-06-26: spread-correct backtest PF 1.06 (~1.0 after
    # commission) — no reliable edge. GBPJPY (PF 1.79) carries the strategy.
    "instruments": ["GBPJPY"],
    "asian_start_hour": 0,            # UTC
    "asian_end_hour": 7,              # UTC — capture range at this hour
    "active_end_hour": 11,            # UTC — cancel unfilled pendings at this hour
    "eod_force_close_hour": 20,       # UTC — force-close any open position
    "min_range_pct_adr": 0.4,         # default min: range >= 0.4 * ADR(14). Per-pair backtest 2026-05-26 showed 0.4 PF=1.97 vs 0.3 PF=1.50 — extra trades from 0.3 dilute edge. GBPJPY edge is narrow (PF 3.66 at 0.4 -> 1.62 at 0.3); EURJPY flat (PF 1.33 vs 1.38). Per-pair override below for EURJPY.
    "min_range_pct_adr_by_symbol": {
        # GBPJPY uses the default 0.4 (don't dilute its narrow edge).
        # (EURJPY override removed 2026-06-26 when EURJPY was dropped.)
    },
    "max_range_pct_adr": 1.0,         # range <= 1.0 * ADR(14)
    "min_buffer_pips": 2.0,
    "buffer_pct_range": 0.10,         # buffer = max(min_buffer, 10% of range)
    "tp_range_mult": 1.0,             # TP at 1× range from entry
    "risk_pct": 0.5,                  # conservative for first deploy
    "skip_weekdays": [4, 5, 6],       # Fri/Sat/Sun (Fri = weekend gap risk)
    # Trend-aligned overlay (H1 EMA200 regime filter).
    # Backtest 2026-05-16 showed PF 1.40 -> 1.89 with this filter, DD 5.4% -> 4.1%.
    # Skips the side fighting the H1 EMA200 trend when price is > threshold_pips
    # away from EMA200; allows both sides in chop near EMA200.
    "trend_filter_enabled": True,
    "trend_filter_threshold_pips": 30,
}

RISK_PCT_BY_PATTERN["ASIAN_SESSION_BREAKOUT"] = ASIAN_SESSION_BREAKOUT["risk_pct"]
MIN_RRR_BY_PATTERN["ASIAN_SESSION_BREAKOUT"] = 0.8   # natural R:R near 1.0; allow some slip
MIN_STOP_PIPS_BY_PATTERN["ASIAN_SESSION_BREAKOUT"] = 5
TRAILING_STOP_ATR_MULT_BY_PATTERN["ASIAN_SESSION_BREAKOUT"] = 0
PATTERN_FRESHNESS_BARS["ASIAN_SESSION_BREAKOUT"] = 1

# ─── Daily Donchian on crypto (Turtle System 2 variant) ──────────────────────
# 9-year backtest with walk-forward validation (2026-06-01 work):
#   55/20 lookback + 1.0× ATR(20) stop survives the 2023-2025 regime change
#   where the 20/10 default broke. Aggregate PF ~5; worst regime PF 2.94.
#   Per-asset (2026-06-01 multi-crypto sweep):
#     BTCUSD 9y: PF 5.09 / MAR 5.93. Walk-forward 2023-25: PF 2.94.
#     ETHUSD 10y: PF 3.22 / MAR 1.37. Walk-forward 2023-25: PF 4.69.
#     Signal overlap between BTC and ETH: 9.8% (low — real diversification).
# Each instance in `instances` becomes its own scanner thread with the
# parent config merged with per-instrument overrides (mirroring QL's setup).
BTC_DONCHIAN = {
    "enabled": True,                   # Scanner runs and alerts; dry_run gates live orders
    "pattern_type": "BTC_DONCHIAN",
    "entry_lookback_days": 55,
    "exit_lookback_days": 20,
    "atr_period_days": 20,
    "atr_stop_multiplier": 1.0,
    "risk_pct": 1.0,
    "poll_interval_sec": 60,
    "magic": 20260601,
    "dry_run": False,                  # LIVE — primitives verified 2026-06-01
    "alert_on_detection": True,
    "instances": [
        {"instrument": "BTCUSD"},      # 9-year PF 5.09, walk-forward 2.94
        {"instrument": "ETHUSD"},      # 10-year PF 3.22, walk-forward 4.69
    ],
}

RISK_PCT_BY_PATTERN["BTC_DONCHIAN"] = BTC_DONCHIAN["risk_pct"]
MIN_RRR_BY_PATTERN["BTC_DONCHIAN"] = 0.0      # no fixed TP — trailing exits only
TRAILING_STOP_ATR_MULT_BY_PATTERN["BTC_DONCHIAN"] = 0  # trail via Donchian extreme, not ATR
MIN_STOP_PIPS_BY_PATTERN["BTC_DONCHIAN"] = 0           # bypass — BTCUSD uses dollar stops not pip stops
PATTERN_FRESHNESS_BARS["BTC_DONCHIAN"] = 1

# ─── NR7 Breakout on equity indices ──────────────────────────────────────────
# Volatility-compression-then-expansion strategy on D1. If today's range is the
# narrowest of the last 7 days (NR7), place BUY_STOP at today's high and
# SELL_STOP at today's low for tomorrow. Whichever fires becomes the trade;
# the other is cancelled. Trail SL via 10-day opposite extreme.
#
# Backtest cross-validation 2026-06-05 — all four indices, 14 years each:
#   US500: PF 5.46  CAGR 18.7%  MAR 15.6
#   DE40:  PF 5.74  CAGR 17.9%  MAR 10.4
#   JP225: PF 4.04  CAGR 18.2%  MAR  5.5
#   UK100: PF 5.55  CAGR 16.6%  MAR 14.2
# Walk-forward: every 3-year window since 2013 positive on every index.
# Friction-robust: PF still 3.92 at 10x assumed round-trip cost.
#
# Deployed at 0.5% risk per trade for first month to bound surprise downside.
# Scale to 1% after 30 live trades if performance tracks backtest expectation.
NR7_BREAKOUT = {
    "enabled": True,
    "pattern_type": "NR7_BREAKOUT",
    "nr_lookback": 7,                  # today's range = min of past N
    "atr_period": 14,
    "atr_stop_multiplier": 1.0,        # initial stop = 1x ATR
    "exit_lookback_days": 10,          # trailing extreme
    "risk_pct": 0.5,                   # half-size first month
    "poll_interval_sec": 60,
    "magic": 20260605,                 # distinct from other strategies
    "alert_on_detection": True,
    "instances": [
        {"instrument": "US500"},
        {"instrument": "DE40"},
    ],
}

RISK_PCT_BY_PATTERN["NR7_BREAKOUT"] = NR7_BREAKOUT["risk_pct"]
MIN_RRR_BY_PATTERN["NR7_BREAKOUT"] = 0.0
TRAILING_STOP_ATR_MULT_BY_PATTERN["NR7_BREAKOUT"] = 0
MIN_STOP_PIPS_BY_PATTERN["NR7_BREAKOUT"] = 0
PATTERN_FRESHNESS_BARS["NR7_BREAKOUT"] = 1

# ─── Pip Values ──────────────────────────────────────────────────────────────
PIP_VALUES = {
    "EURUSD": 0.0001,
    "GBPUSD": 0.0001,
    "AUDUSD": 0.0001,
    "NZDUSD": 0.0001,
    "USDCAD": 0.0001,
    "USDCHF": 0.0001,
    "EURGBP": 0.0001,
    "EURAUD": 0.0001,
    "AUDNZD": 0.0001,
    "NZDCAD": 0.0001,
    "AUDCAD": 0.0001,
    "EURCHF": 0.0001,
    "USDJPY": 0.01,
    "GBPJPY": 0.01,
    "EURJPY": 0.01,
    "CHFJPY": 0.01,
    "XAUUSD": 0.01,
    "XAGUSD": 0.001,
    "BTCUSD": 1.0,
    "US30": 1.0,
}


def active_traded_symbols() -> set:
    """Symbols currently traded by an ENABLED strategy.

    Single source of truth for filtering Telegram reports so abandoned pairs
    (e.g. EURJPY after 2026-06-26) drop out automatically as the config changes.
    Respects each strategy's `enabled` flag and its instrument-list shape
    ("instruments" list / "instrument" single / "instances" list-of-dicts).
    """
    syms: set = set()
    # Main-loop patterns (KZ_HUNT) use the INSTRUMENTS universe — only live
    # when ENABLED_PATTERNS is non-empty (KZ is currently disabled).
    if ENABLED_PATTERNS:
        syms.update(INSTRUMENTS)
    for cfg in (NIGHT_TIDE, ASIAN_SESSION_BREAKOUT):          # "instruments" list
        if cfg.get("enabled"):
            syms.update(cfg.get("instruments", []))
    for cfg in (LONDON_BREAKOUT, ASIAN_GRAVITY):             # single "instrument"
        if cfg.get("enabled") and cfg.get("instrument"):
            syms.add(cfg["instrument"])
    for cfg in (BTC_DONCHIAN, NR7_BREAKOUT, QUANTUM_LONDON):  # "instances" dicts
        if cfg.get("enabled"):
            syms.update(i["instrument"] for i in cfg.get("instances", []) if i.get("instrument"))
    return syms
