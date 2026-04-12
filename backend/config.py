from dotenv import load_dotenv
import os

load_dotenv()

DATABASE_URL         = os.getenv("DATABASE_URL", "sqlite:///./weltbot.db")
MAX_RISK_PCT         = float(os.getenv("MAX_RISK_PCT", "0.01"))
DEFAULT_PORTFOLIO    = float(os.getenv("DEFAULT_PORTFOLIO", "10000.0"))
DAILY_DRAWDOWN_LIMIT = float(os.getenv("DAILY_DRAWDOWN_LIMIT", "0.05"))
MAX_OPEN_TRADES      = int(os.getenv("MAX_OPEN_TRADES", "3"))
SCAN_INTERVAL_MIN    = int(os.getenv("SCAN_INTERVAL_MIN", "15"))
SL_COOLDOWN_HOURS    = int(os.getenv("SL_COOLDOWN_HOURS", "4"))

BINANCE_API_KEY    = os.getenv("BINANCE_API_KEY", "")
BINANCE_SECRET_KEY = os.getenv("BINANCE_SECRET_KEY", "")
BINANCE_TESTNET    = os.getenv("BINANCE_TESTNET", "true").lower() == "true"

BUY_THRESHOLD  = 0.15
SELL_THRESHOLD = -0.15

MAX_TRADES_PER_ASSET_PER_DAY = 99
MIN_CONFIDENCE               = 15.0
REENTRY_MIN_SCORE            = 0.10
DEFAULT_LEVERAGE = int(os.getenv("DEFAULT_LEVERAGE", "5"))