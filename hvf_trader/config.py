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
INSTRUMENTS = ["EURUSD", "NZDUSD", "EURGBP", "USDCHF", "EURAUD", "GBPJPY", "EURJPY", "CHFJPY"]
# XAUUSD: add to INSTRUMENTS when WEDGE or gold-specific KZ_HUNT goes live.
# Currently available for backtesting only.
# Which pattern detectors to run live. Others remain available for backtesting.
ENABLED_PATTERNS = ["KZ_HUNT"]  # HVF disabled — PF=0.06 live. TREND_RIDE removed — PF=0.86 backtest. WEDGE available for backtesting only.
PRIMARY_TIMEFRAME = "H1"
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
    "KZ_HUNT": 1.0,
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
    "KZ_HUNT": 50,
    "LONDON_SWEEP": 50,
    "WEDGE": 40,
}

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
    "KZ_HUNT": 1.0,        # Reduced from 2% — expert panel: 2% on correlated pairs too aggressive for micro account
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
    "KZ_HUNT": 1.0,      # V2 — tight trail on volume engine to secure gains
    "LONDON_SWEEP": 1.5,
    "WEDGE": 1.5,        # D1 patterns need more room
}

# Per-pattern freshness (max bars from detection to arming)
PATTERN_FRESHNESS_BARS = {
    "HVF": 100,           # Breakouts can take time
    "VIPER": 10,          # Momentum continuation must be recent
    "KZ_HUNT": 24,
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
TRADE_MONITOR_INTERVAL_SEC = 5    # Check open positions every 5s — catches single-tick wicks at T1

# ─── Performance Monitor ───────────────────────────────────────────────────
PERF_MONITOR_INTERVAL_SEC = 3600      # Check every hour
PERF_ROLLING_TRADE_COUNT = 20         # Rolling window size
PERF_MIN_PF_THRESHOLD = 1.0           # Alert if rolling PF < 1.0
PERF_WIN_RATE_DROP_PCT = 10            # Alert if WR drops >10% from baseline
PERF_MAX_CONSECUTIVE_LOSSES = 5        # Alert at 5+ consecutive losses
PERF_ALERT_COOLDOWN_HOURS = 24         # Don't re-alert same issue for 24h
PERF_SHARPE_WINDOW_DAYS = 60           # Rolling Sharpe ratio window
PERF_SHARPE_WARN_THRESHOLD = 0.5       # Sharpe < 0.5 → alert: reduce size
PERF_SHARPE_HALT_THRESHOLD = 0.0       # Sharpe < 0.0 → alert: halt trading
PERF_WR_DECAY_THRESHOLD = 15           # Alert if recent WR drops >15% below all-time WR
PERF_KILL_SWITCH_MIN_TRADES = 200      # Min trades before kill switch can activate
PERF_KILL_SWITCH_MIN_PF = 1.2          # Auto-halt if live PF < this after min trades
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
QUANTUM_LONDON = {
    "enabled": True,
    "instrument": "EURGBP",
    "formation_timeframe": "M15",
    "poll_interval_sec": 30,
    "days": [0, 1, 2, 3, 4],           # Sun-Thu nights (trading happens Mon-Fri 00:00-05:00 UTC)
    "formation_start_utc": 22,          # Daily open at 22:00 UTC (00:00 GMT+2)
    "formation_end_utc": 0,             # No formation needed — just grab the 22:00 open
    "trading_start_utc": 0,             # Trading window: 00:00-05:00 UTC
    "trading_end_utc": 5,
    "forced_exit_utc": 5,              # Exit before Frankfurt pre-market
    "trigger_pips": 8,
    "target_pips": 5,
    "stop_pips": 18,
    "max_range_pips": 999,              # No range filter — use daily open deviation only
    "max_spread_pips": 2.5,             # Asian-hours EURGBP spread is 3-5p live; 1.2p filtered out virtually all triggers
    "max_trades_per_session": 1,
    "direction": "BOTH",
    "risk_pct": 5.0,
    "daily_loss_limit_pct": 5.0,
    "kill_switch_consecutive_losses": 3,
    "pattern_type": "QUANTUM_LONDON",
    "daily_open_utc_hour": 22,          # Reference price: bar open at this UTC hour
}

RISK_PCT_BY_PATTERN["QUANTUM_LONDON"] = QUANTUM_LONDON["risk_pct"]
MIN_RRR_BY_PATTERN["QUANTUM_LONDON"] = 0.25
TRAILING_STOP_ATR_MULT_BY_PATTERN["QUANTUM_LONDON"] = 0
MIN_STOP_PIPS_BY_PATTERN["QUANTUM_LONDON"] = 3
PATTERN_FRESHNESS_BARS["QUANTUM_LONDON"] = 1

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
    "USDJPY": 0.01,
    "GBPJPY": 0.01,
    "EURJPY": 0.01,
    "CHFJPY": 0.01,
    "XAUUSD": 0.01,
    "XAGUSD": 0.001,
    "BTCUSD": 1.0,
    "US30": 1.0,
}
