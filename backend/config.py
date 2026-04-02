from dotenv import load_dotenv
import os

load_dotenv()

DATABASE_URL      = os.getenv("DATABASE_URL", "sqlite:///./trading.db")
MAX_RISK_PCT      = float(os.getenv("MAX_RISK_PCT", "0.02"))
DEFAULT_PORTFOLIO = float(os.getenv("DEFAULT_PORTFOLIO", "10000.0"))
MAX_DAILY_TRADES  = int(os.getenv("MAX_DAILY_TRADES", "5"))
BUY_THRESHOLD     = 0.55
SELL_THRESHOLD    = -0.55
CRYPTO_ASSETS     = ["BTC-USD", "ETH-USD"]
EQUITY_ASSETS     = ["AAPL", "MSFT", "NVDA"]
ALL_ASSETS        = CRYPTO_ASSETS + EQUITY_ASSETS