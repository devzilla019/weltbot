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

# Refined CRT with Pullback Entry — forex majors, crosses and metals.
_FOREX_PAIRS_DEFAULT = (
    "XAUUSD,XAGUSD,"
    "EURUSD,GBPUSD,USDJPY,USDCHF,USDCAD,AUDUSD,NZDUSD,"
    "EURGBP,EURCHF,EURJPY,GBPJPY,GBPCHF,AUDJPY,CADJPY,NZDCAD"
)
FOREX_PAIRS = [p.strip() for p in os.getenv(
    "FOREX_PAIRS", _FOREX_PAIRS_DEFAULT
).split(",") if p.strip()]

# Capital.com uses short epic codes
CAPITAL_EPIC_MAP = {
    "XAUUSD": "GOLD",
    "XAGUSD": "SILVER",
    "EURUSD": "EURUSD",
    "GBPUSD": "GBPUSD",
    "USDJPY": "USDJPY",
    "USDCHF": "USDCHF",
    "USDCAD": "USDCAD",
    "AUDUSD": "AUDUSD",
    "NZDUSD": "NZDUSD",
    "EURGBP": "EURGBP",
    "EURCHF": "EURCHF",
    "EURJPY": "EURJPY",
    "GBPJPY": "GBPJPY",
    "GBPCHF": "GBPCHF",
    "AUDJPY": "AUDJPY",
    "CADJPY": "CADJPY",
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
# Risk per trade scales DOWN as the account gets smaller, because a fixed
# percentage of a small balance cannot satisfy the broker's minimum order
# size and would silently risk far more than intended.
FOREX_MAX_RISK_PCT       = env_float("FOREX_MAX_RISK_PCT",       0.02)   # >= $500
FOREX_MAX_RISK_PCT_MID   = env_float("FOREX_MAX_RISK_PCT_MID",   0.015)  # $200-$500
FOREX_MAX_RISK_PCT_SMALL = env_float("FOREX_MAX_RISK_PCT_SMALL", 0.01)   # < $200
FOREX_MID_ACCOUNT        = env_float("FOREX_MID_ACCOUNT",        500.0)
FOREX_SMALL_ACCOUNT      = env_float("FOREX_SMALL_ACCOUNT",      200.0)

# Smallest balance worth trading — below this the broker's minimum order
# size forces more risk than the strategy is designed for.
FOREX_MIN_TRADEABLE_BALANCE = env_float("FOREX_MIN_TRADEABLE_BALANCE", 50.0)

# Hard ceiling on the risk a single trade may carry once the broker's minimum
# order size is taken into account. On a very small account the minimum size
# can imply far more risk than the target percentage, so the trade is skipped
# rather than opened oversized.
FOREX_MAX_IMPLIED_RISK_PCT = env_float("FOREX_MAX_IMPLIED_RISK_PCT", 0.05)  # 5%

FOREX_MAX_TRADES   = env_int("FOREX_MAX_TRADES",   3)       # 3 max forex positions
FOREX_MIN_CONF     = env_float("FOREX_MIN_CONF",   88.0)    # 88% minimum (refined CRT)
# Halt new forex entries once the day's realised loss reaches this share of
# the balance. Protects a small account from a losing streak.
FOREX_DAILY_LOSS_LIMIT = env_float("FOREX_DAILY_LOSS_LIMIT", 0.06)   # 6%


def forex_risk_pct(balance: float) -> float:
    """
    Risk-per-trade fraction for the given account balance.

    Smaller accounts take proportionally less risk so that the broker's
    minimum order size does not push realised risk far above the target.
    """
    if balance <= 0:
        return FOREX_MAX_RISK_PCT_SMALL
    if balance < FOREX_SMALL_ACCOUNT:
        return FOREX_MAX_RISK_PCT_SMALL
    if balance < FOREX_MID_ACCOUNT:
        return FOREX_MAX_RISK_PCT_MID
    return FOREX_MAX_RISK_PCT

# ── Forex Leverage Tiers ───────────────────────────────────────────────────────
FOREX_LEVERAGE_TIERS = {
    95: 100,  # 95%+ = 100:1
    90: 50,   # 90%+ = 50:1
    85: 20,   # 85%+ = 20:1
}

# ── Safety ─────────────────────────────────────────────────────────────────────
LIQUIDATION_BUFFER_ATR = env_float("LIQUIDATION_BUFFER_ATR", 2.5)

# ── Silver Bullet + Volume Profile strategy ────────────────────────────────────
# Silver Bullet is the ONLY signal-generation strategy in the application. Every
# enabled instrument below is scanned by it; the CRT/SMC engines are retained on
# disk for reference but are unreachable from any scheduling or entry path.
#
# The roster is DERIVED, never hand-listed, so an instrument cannot be enabled
# in the crypto universe and then silently never scanned:
#
#   forex + metals  <- FOREX_PAIRS (Capital.com)
#   crypto          <- modules.universe.get_universe() (Binance)
#
# `SILVER_BULLET_EXTRA_SYMBOLS` remains as an escape hatch for an instrument
# that is not in either list (a new listing, a manually pinned pair).
SILVER_BULLET_EXTRA_SYMBOLS = [
    s.strip() for s in os.getenv(
        "SILVER_BULLET_EXTRA_SYMBOLS", ""
    ).split(",") if s.strip()
]


def _crypto_universe() -> list:
    """
    Every enabled Binance symbol, from the universe the crypto engine uses.

    Imported lazily and defensively: a failure here must degrade to "no crypto
    scanned" rather than to "an empty instrument list", because an empty list
    would look like a valid configuration with nothing enabled.
    """
    try:
        from modules.universe import get_universe
        return list(get_universe())
    except Exception as e:      # pragma: no cover - import-time guard
        print(f"[config] WARNING: crypto universe unavailable ({e}) — "
              f"crypto instruments will not be scanned")
        return []


SILVER_BULLET_INSTRUMENTS = list(dict.fromkeys(
    list(FOREX_PAIRS)
    + _crypto_universe()
    + [s for s in SILVER_BULLET_EXTRA_SYMBOLS if s]
))

# Whether a volume profile may gate an entry when its volume is a range proxy
# rather than real traded volume. Binance reports genuine traded volume, so
# every crypto symbol clears it. Capital.com CFDs report only the provider's own
# cleared contracts, which is a proxy for a decentralised market — gating on
# that would be gating on time-at-price while calling it volume. Set to true to
# admit FX/metals profiles too, and label the resulting trades as such.
VP_REQUIRE_TRUSTED_VOLUME = env_bool("VP_REQUIRE_TRUSTED_VOLUME", True)

# ── Legacy strategy entry lock ────────────────────────────────────────────────
# The Silver Bullet engine is the unified forex strategy. The older CRT/SMC
# path is retained only for the dashboard data it publishes (CRT levels, Kronos
# bias) and must not submit orders while the migration is in progress.
#
# Default FALSE — the safe state is the migration, not the exception. The lock
# is enforced inside `forex_executor.place_forex_order`, the single function
# that sends a Capital.com order, and it FAILS CLOSED: an unreadable flag denies
# the order rather than permitting it. Flip this only to run the old strategy
# deliberately.
LEGACY_FOREX_ENTRIES_ENABLED = env_bool("LEGACY_FOREX_ENTRIES_ENABLED", False)

# ── Kelly ─────────────────────────────────────────────────────────────────────
# These are defaults — bot learns live values from actual trade history
KELLY_WIN_RATE_DEFAULT = env_float("KELLY_WIN_RATE", 0.50)
KELLY_RR_DEFAULT       = env_float("KELLY_RR",       2.95)
KELLY_FRACTION         = env_float("KELLY_FRACTION", 0.55)  # 55% Kelly

# ── Auth (DISABLED for now — single-user open dashboard) ───────────────────────
AUTH_ENABLED = env_bool("AUTH_ENABLED", False)
