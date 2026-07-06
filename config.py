"""
backend/config.py - COMPLETE
All settings in one place, all from environment variables.
"""
import os

# ── Exchange ───────────────────────────────────────────────────────────────────
BINANCE_API_KEY    = os.getenv("BINANCE_API_KEY",    "")
BINANCE_SECRET_KEY = os.getenv("BINANCE_SECRET_KEY", "")
BINANCE_TESTNET    = os.getenv("BINANCE_TESTNET",    "true").lower() == "true"

# ── Database ───────────────────────────────────────────────────────────────────
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./weltbot.db")

# ── Risk ───────────────────────────────────────────────────────────────────────
MAX_RISK_PCT          = float(os.getenv("MAX_RISK_PCT",          "0.03"))   # 3% base
DEFAULT_PORTFOLIO     = float(os.getenv("DEFAULT_PORTFOLIO",     "5000.0"))
DAILY_DRAWDOWN_LIMIT  = float(os.getenv("DAILY_DRAWDOWN_LIMIT",  "0.05"))   # 5%
MAX_OPEN_TRADES       = int(os.getenv("MAX_OPEN_TRADES",         "2"))      # 2 max positions
SL_COOLDOWN_HOURS     = int(os.getenv("SL_COOLDOWN_HOURS",       "6"))

# ── Signal ─────────────────────────────────────────────────────────────────────
MIN_CONFIDENCE     = float(os.getenv("MIN_CONFIDENCE",    "90.0"))   # raised to 90
SCAN_INTERVAL_MIN  = int(os.getenv("SCAN_INTERVAL_MIN",   "15"))

# ── Leverage tiers (confidence threshold → leverage) ──────────────────────────
LEVERAGE_TIERS = {
    98: 100,   # 98%+ AND in HIGH_LEV_ASSETS only
    95: 50,
    90: 20,
    85: 10,
}
HIGH_LEV_ASSETS = ["BTC/USDT", "ETH/USDT", "BNB/USDT", "SOL/USDT"]

# ── Auth ───────────────────────────────────────────────────────────────────────
SECRET_KEY = os.getenv("SECRET_KEY", "")
if not SECRET_KEY:
    import secrets
    SECRET_KEY = secrets.token_hex(32)
    print("[config] WARNING: SECRET_KEY not set — using random key (sessions will reset on restart)")

# ── Allowed origins ────────────────────────────────────────────────────────────
ALLOWED_ORIGINS = os.getenv(
    "ALLOWED_ORIGINS",
    "https://weltbot.vercel.app,http://localhost:5173"
).split(",")

# ── News / Twitter ─────────────────────────────────────────────────────────────
NEWS_BLACKOUT_ENABLED = os.getenv("NEWS_BLACKOUT_ENABLED", "true").lower() == "true"
TWITTER_BEARER_TOKEN  = os.getenv("TWITTER_BEARER_TOKEN",  "")

# ── Safety ─────────────────────────────────────────────────────────────────────
LIQUIDATION_BUFFER_ATR = float(os.getenv("LIQUIDATION_BUFFER_ATR", "2.5"))

# ── Kelly ─────────────────────────────────────────────────────────────────────
# These are defaults — bot learns live values from actual trade history
KELLY_WIN_RATE_DEFAULT = float(os.getenv("KELLY_WIN_RATE", "0.50"))
KELLY_RR_DEFAULT       = float(os.getenv("KELLY_RR",       "2.95"))
KELLY_FRACTION         = float(os.getenv("KELLY_FRACTION",  "0.55"))  # 55% Kelly
