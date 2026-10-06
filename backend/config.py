"""
backend/config.py - COMPLETE
All settings in one place, all from environment variables.

Robust parsing: env values are sanitized so stray comments/units
(e.g. "0.02 (2%)") never crash the app at import time.
"""
import os
import re
from pathlib import Path

try:
    from dotenv import load_dotenv
except Exception:  # pragma: no cover
    def load_dotenv(*args, **kwargs):
        return False

BASE_DIR = Path(__file__).resolve().parent
for _env_path in (BASE_DIR / ".env", BASE_DIR.parent / ".env"):
    if _env_path.exists():
        load_dotenv(_env_path, override=False)


def _clean(raw: str) -> str:
    """Strip whitespace, inline comments and trailing units from an env value."""
    if raw is None:
        return ""
    # cut anything after a '#' comment
    raw = raw.split("#", 1)[0]
    # keep only the leading numeric token (handles "0.02 (2%)", "15 min", "true ")
    m = re.match(r"\s*([-+]?\d*\.?\d+(?:[eE][-+]?\d+)?)", raw)
    if m:
        return m.group(1)
    return raw.strip()


def env_float(key: str, default: float) -> float:
    try:
        return float(_clean(os.getenv(key, str(default))))
    except (TypeError, ValueError):
        print(f"[config] WARNING: invalid float for {key}={os.getenv(key)!r} — using {default}")
        return float(default)


def env_int(key: str, default: int) -> int:
    try:
        return int(float(_clean(os.getenv(key, str(default)))))
    except (TypeError, ValueError):
        print(f"[config] WARNING: invalid int for {key}={os.getenv(key)!r} — using {default}")
        return int(default)


def env_bool(key: str, default: bool) -> bool:
    raw = os.getenv(key)
    if raw is None:
        return default
    return _clean(raw).strip().lower() in ("1", "true", "yes", "on")


# ── Exchange ───────────────────────────────────────────────────────────────────
BINANCE_API_KEY    = os.getenv("BINANCE_API_KEY",    "")
BINANCE_SECRET_KEY = os.getenv("BINANCE_SECRET_KEY", "")
BINANCE_TESTNET    = env_bool("BINANCE_TESTNET",    True)

# ── Database ───────────────────────────────────────────────────────────────────
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./weltbot.db")

# ── Risk ───────────────────────────────────────────────────────────────────────
MAX_RISK_PCT          = env_float("MAX_RISK_PCT",          0.03)   # 3% base
DEFAULT_PORTFOLIO     = env_float("DEFAULT_PORTFOLIO",     5000.0)
DAILY_DRAWDOWN_LIMIT  = env_float("DAILY_DRAWDOWN_LIMIT",  0.05)   # 5%
MAX_OPEN_TRADES       = env_int("MAX_OPEN_TRADES",         2)      # 2 max positions
SL_COOLDOWN_HOURS     = env_int("SL_COOLDOWN_HOURS",       6)

# ── Signal ─────────────────────────────────────────────────────────────────────
MIN_CONFIDENCE     = env_float("MIN_CONFIDENCE",    90.0)   # raised to 90
SCAN_INTERVAL_MIN  = env_int("SCAN_INTERVAL_MIN",   15)

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
NEWS_BLACKOUT_ENABLED = env_bool("NEWS_BLACKOUT_ENABLED", True)
TWITTER_BEARER_TOKEN  = os.getenv("TWITTER_BEARER_TOKEN",  "")

# ── Capital.com (Forex/Metals) ────────────────────────────────────────────────
CAPITAL_API_KEY  = os.getenv("CAPITAL_API_KEY",  "")
CAPITAL_EMAIL    = os.getenv("CAPITAL_EMAIL",    "")
CAPITAL_PASSWORD = os.getenv("CAPITAL_PASSWORD", "")
CAPITAL_DEMO     = env_bool("CAPITAL_DEMO", True)

CAPITAL_BASE_URL = (
    "https://demo-api-capital.backend-capital.com" if CAPITAL_DEMO
    else "https://api-capital.backend-capital.com"
)

FOREX_ENABLED = env_bool("FOREX_ENABLED", False)
FOREX_PAIRS   = [p.strip() for p in os.getenv(
    "FOREX_PAIRS", "XAUUSD,EURUSD,GBPUSD,EURCHF,EURJPY,GBPJPY,AUDJPY,NZDCAD"
).split(",") if p.strip()]

# Capital.com uses short epic codes
CAPITAL_EPIC_MAP = {
    "XAUUSD": "GOLD",
    "EURUSD": "EURUSD",
    "GBPUSD": "GBPUSD",
    "EURCHF": "EURCHF",
    "EURJPY": "EURJPY",
    "GBPJPY": "GBPJPY",
    "AUDJPY": "AUDJPY",
    "NZDCAD": "NZDCAD",
}


def to_epic(symbol: str) -> str:
    """XAUUSD -> GOLD, EURUSD -> EURUSD."""
    s = symbol.replace("/", "").replace("_", "").upper()
    return CAPITAL_EPIC_MAP.get(s, s)


def from_epic(epic: str) -> str:
    """GOLD -> XAUUSD, EURUSD -> EURUSD."""
    reverse = {v: k for k, v in CAPITAL_EPIC_MAP.items()}
    return reverse.get(epic, epic)

# ── Kronos AI ──────────────────────────────────────────────────────────────────
KRONOS_ENABLED     = env_bool("KRONOS_ENABLED", False)
KRONOS_MODEL_PATH  = os.getenv("KRONOS_MODEL_PATH", "NeoQuasar/Kronos-mini")
KRONOS_TOKENIZER   = os.getenv("KRONOS_TOKENIZER",  "NeoQuasar/Kronos-Tokenizer-2k")

# ── Forex Risk (separate from crypto) ──────────────────────────────────────────
FOREX_MAX_RISK_PCT = env_float("FOREX_MAX_RISK_PCT", 0.02)  # 2% per trade
FOREX_MAX_TRADES   = env_int("FOREX_MAX_TRADES",   3)       # 3 max forex positions
FOREX_MIN_CONF     = env_float("FOREX_MIN_CONF",   85.0)    # 85% minimum

# ── Forex Leverage Tiers ───────────────────────────────────────────────────────
FOREX_LEVERAGE_TIERS = {
    95: 100,  # 95%+ = 100:1
    90: 50,   # 90%+ = 50:1
    85: 20,   # 85%+ = 20:1
}

# ── Safety ─────────────────────────────────────────────────────────────────────
LIQUIDATION_BUFFER_ATR = env_float("LIQUIDATION_BUFFER_ATR", 2.5)

# ── Kelly ─────────────────────────────────────────────────────────────────────
# These are defaults — bot learns live values from actual trade history
KELLY_WIN_RATE_DEFAULT = env_float("KELLY_WIN_RATE", 0.50)
KELLY_RR_DEFAULT       = env_float("KELLY_RR",       2.95)
KELLY_FRACTION         = env_float("KELLY_FRACTION", 0.55)  # 55% Kelly

# ── Auth (DISABLED for now — single-user open dashboard) ───────────────────────
AUTH_ENABLED = env_bool("AUTH_ENABLED", False)
