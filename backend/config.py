from dotenv import load_dotenv
import os

load_dotenv()

DATABASE_URL         = os.getenv("DATABASE_URL", "sqlite:///./weltbot.db")
MAX_RISK_PCT         = float(os.getenv("MAX_RISK_PCT", "0.01"))
DEFAULT_PORTFOLIO    = float(os.getenv("DEFAULT_PORTFOLIO", "10000.0"))
MAX_DAILY_TRADES     = int(os.getenv("MAX_DAILY_TRADES", "20"))
DAILY_DRAWDOWN_LIMIT = float(os.getenv("DAILY_DRAWDOWN_LIMIT", "0.05"))

BINANCE_API_KEY    = os.getenv("BINANCE_API_KEY", "")
BINANCE_SECRET_KEY = os.getenv("BINANCE_SECRET_KEY", "")
BINANCE_TESTNET    = os.getenv("BINANCE_TESTNET", "true").lower() == "true"

BUY_THRESHOLD  = 0.15
SELL_THRESHOLD = -0.15

MIN_CONFIDENCE               = 15.0
MAX_OPEN_TRADES              = 3
SL_COOLDOWN_HOURS            = 4
REENTRY_MIN_SCORE            = 0.10
SCAN_INTERVAL_MIN            = 15
MAX_TRADES_PER_ASSET_PER_DAY = 4