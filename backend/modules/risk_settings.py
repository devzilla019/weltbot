"""
backend/modules/risk_settings.py
Runtime-tunable risk settings, persisted in the database.

Every limit can be switched off. A hard daily stop that cannot be relaxed
makes a strategy impossible to evaluate — once it trips, nothing fires until
the next day, so there is no feedback to act on.

Reads are cached briefly so the 60-second entry check does not hit the
database on every symbol.
"""
import logging
import threading
import time
from typing import Optional, Dict

from database import SessionLocal
from models import RiskSettings

logger = logging.getLogger(__name__)

_TTL = 15.0          # seconds
_cache: Optional[Dict] = None
_cache_ts: float = 0.0
_lock = threading.Lock()

# Fallbacks used when the row or table is unavailable
_DEFAULTS = {
    "forex_enabled": True,
    "crypto_enabled": True,
    "forex_daily_limit_enabled": True,
    "forex_daily_loss_limit": 0.06,
    "crypto_daily_limit_enabled": True,
    "crypto_daily_loss_limit": 0.05,
    "forex_risk_pct": 0.02,
    "crypto_risk_pct": 0.01,
    "forex_min_confidence": 88.0,
    "crypto_min_confidence": 90.0,
    "forex_max_trades": 3,
    "crypto_max_trades": 2,
    "diagnostic_mode": False,
    "auto_resume": True,
    "weekend_guard": True,
}


def _row_to_dict(row: RiskSettings) -> Dict:
    return {k: getattr(row, k) for k in _DEFAULTS}


def get_settings(force: bool = False) -> Dict:
    """Current risk settings, cached for a few seconds."""
    global _cache, _cache_ts

    with _lock:
        if not force and _cache and (time.time() - _cache_ts) < _TTL:
            return dict(_cache)

    try:
        db = SessionLocal()
        try:
            row = db.query(RiskSettings).first()
            if row is None:
                row = RiskSettings()
                db.add(row)
                db.commit()
                db.refresh(row)
            data = _row_to_dict(row)
        finally:
            db.close()
    except Exception as e:
        logger.error(f"[settings] read error: {e} — using defaults")
        data = dict(_DEFAULTS)

    with _lock:
        _cache = data
        _cache_ts = time.time()
    return dict(data)


def diagnostic_mode() -> bool:
    """
    True when the bot should evaluate signals but never place orders.

    Read straight from the settings cache so every execution path can check it
    cheaply on each cycle. Fails closed to normal trading only when the value
    is missing entirely, because a silently-ignored diagnostic switch would be
    worse than an explicit one.
    """
    try:
        return bool(get_settings().get("diagnostic_mode", False))
    except Exception:
        return False


def _coerce(key: str, current, value):
    """
    Convert an incoming value to the column's type.

    Booleans are matched first because bool is a subclass of int, so a naive
    isinstance(int) check would silently accept 5 for a boolean column.
    """
    if isinstance(current, bool):
        if isinstance(value, str):
            return value.strip().lower() in ("1", "true", "yes", "on")
        return bool(value)
    if isinstance(current, float):
        return float(value)
    if isinstance(current, int):
        return int(value)
    return value


# Hard bounds mirrored from routers/analytics.py so a bad value can never be
# persisted through any path (API, reset, or future caller).
_BOUNDS = {
    "forex_daily_loss_limit": (0.0, 0.50),
    "crypto_daily_loss_limit": (0.0, 0.50),
    "forex_risk_pct": (0.001, 0.05),
    "crypto_risk_pct": (0.001, 0.05),
    "forex_min_confidence": (60.0, 99.0),
    "crypto_min_confidence": (60.0, 99.0),
    "forex_max_trades": (1, 20),
    "crypto_max_trades": (1, 20),
}


def validate_changes(changes: Dict) -> tuple:
    """
    Split a change set into accepted values and rejected (key, reason) pairs.

    Out-of-range numbers are rejected rather than clamped: silently turning a
    requested 90% loss cap into 50% would hide a mistake behind a limit the
    user never chose.
    """
    accepted, rejected = {}, []
    for key, value in (changes or {}).items():
        if key not in _DEFAULTS:
            rejected.append((key, "unknown setting"))
            continue
        if value is None:
            continue
        current = _DEFAULTS[key]
        try:
            coerced = _coerce(key, current, value)
        except (TypeError, ValueError):
            rejected.append((key, f"invalid value for type {type(current).__name__}"))
            continue
        low, high = _BOUNDS.get(key, (None, None))
        if low is not None and not (low <= coerced <= high):
            rejected.append((key, f"out of range ({low}–{high})"))
            continue
        accepted[key] = coerced
    return accepted, rejected


def update_settings(changes: Dict) -> Dict:
    """Apply partial changes and return the stored result."""
    global _cache, _cache_ts

    accepted, rejected = validate_changes(changes)
    for key, reason in rejected:
        logger.warning(f"[settings] rejected {key}: {reason}")

    try:
        db = SessionLocal()
        try:
            row = db.query(RiskSettings).first()
            if row is None:
                row = RiskSettings()
                db.add(row)
                db.commit()
                db.refresh(row)

            for key, value in accepted.items():
                setattr(row, key, value)

            db.commit()
            db.refresh(row)
            data = _row_to_dict(row)
            if accepted:
                logger.info(f"[settings] updated: {sorted(accepted)}")
        finally:
            db.close()
    except Exception as e:
        logger.error(f"[settings] update error: {e}")
        return get_settings(force=True)

    with _lock:
        _cache = data
        _cache_ts = time.time()
    return dict(data)


def invalidate_cache() -> None:
    global _cache, _cache_ts
    with _lock:
        _cache = None
        _cache_ts = 0.0
