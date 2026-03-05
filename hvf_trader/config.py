"""
HVF Auto-Trader Configuration
All settings and thresholds. Nothing hardcoded elsewhere.
"""

import os
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

# ─── Instruments ─────────────────────────────────────────────────────────────
INSTRUMENTS = ["EURUSD", "GBPUSD"]
PRIMARY_TIMEFRAME = "H1"
CONFIRMATION_TIMEFRAME = "H4"

# ─── HVF Detection ──────────────────────────────────────────────────────────
ZIGZAG_ATR_MULTIPLIER = 2.0       # Zigzag threshold = ATR% * this multiplier (tuned for meaningful swings)
ATR_PERIOD = 14
EMA_PERIOD = 200
ADX_PERIOD = 14

HVF_ENTRY_BUFFER_PIPS = 3
HVF_ATR_STOP_MULT = 0.5          # SL = 3L - (this * ATR14) (tightened from 1.0 for better RRR)
HVF_MIN_RRR = 1.0                # Minimum reward:risk ratio (relaxed from 3.0→1.5→1.0)

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
    "VIPER": 50,
    "KZ_HUNT": 50,
    "LONDON_SWEEP": 50,
}

# ─── Multi-Pattern Indicators ───────────────────────────────────────────────
RSI_PERIOD = 14
MACD_FAST = 12
MACD_SLOW = 26
MACD_SIGNAL = 9

# ─── Kill Zones (UTC hours) ─────────────────────────────────────────────────
KILL_ZONES_UTC = {
    "london": (8, 11),          # London open session
    "ny_morning": (13, 16),     # NY morning / London-NY overlap
    "ny_evening": (16, 20),     # NY afternoon session
    "asian": (0, 4),            # Asian session (Tokyo/Sydney)
}

# ─── Risk Management ────────────────────────────────────────────────────────
RISK_PCT = 1.0                    # 1% per trade (conservative until validated)

# Per-pattern risk percentages
RISK_PCT_BY_PATTERN = {
    "HVF": 1.0,
    "VIPER": 0.75,
    "KZ_HUNT": 0.5,
    "LONDON_SWEEP": 0.5,
}
DAILY_LOSS_LIMIT_PCT = 3.0        # Pause until midnight UTC
WEEKLY_LOSS_LIMIT_PCT = 5.0       # Pause until Monday 00:00 UTC
MONTHLY_LOSS_LIMIT_PCT = 10.0     # Pause until 1st 00:00 UTC
MAX_CONCURRENT_TRADES = 2         # With £500 capital
MAX_SPREAD_PCT_OF_STOP = 0.05     # 5% of stop distance max
MAX_MARGIN_USAGE_PCT = 0.50       # Never use > 50% free margin

# ─── Trade Management ───────────────────────────────────────────────────────
PARTIAL_CLOSE_PCT = 0.50          # Close 50% at target_1
TRAILING_STOP_ATR_MULT = 1.5     # Trail SL at 1.5x ATR below highest since partial
TARGET_1_MULT = 0.5              # target_1 = midpoint + full_range * 0.5
TARGET_2_MULT = 1.0              # target_2 = midpoint + full_range * 1.0

# ─── News Filter ─────────────────────────────────────────────────────────────
NEWS_BLOCK_MINUTES = 30           # Block trading 30min before/after high-impact

# ─── Health Check ────────────────────────────────────────────────────────────
HEARTBEAT_INTERVAL_SEC = 60       # MT5 heartbeat check interval
RECONNECT_BASE_DELAY_SEC = 5     # Exponential backoff starting delay
RECONNECT_MAX_DELAY_SEC = 60     # Max backoff delay
RECONNECT_MAX_ATTEMPTS = 10
DISCONNECT_CLOSE_THRESHOLD_SEC = 900  # 15 min = close all positions on reconnect

# ─── Trade Monitor ───────────────────────────────────────────────────────────
TRADE_MONITOR_INTERVAL_SEC = 30   # Check open positions every 30 seconds

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

# ─── Pip Values ──────────────────────────────────────────────────────────────
PIP_VALUES = {
    "EURUSD": 0.0001,
    "GBPUSD": 0.0001,
    "AUDUSD": 0.0001,
    "USDJPY": 0.01,
    "GBPJPY": 0.01,
    "XAUUSD": 0.01,
    "BTCUSD": 1.0,
    "US30": 1.0,
}
