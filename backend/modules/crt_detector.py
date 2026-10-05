"""
backend/modules/crt_detector.py
Candle Range Theory (CRT) — multi-timeframe range marking + sweep detection.

CRT logic (per timeframe):
  1. Mark the range of the PREVIOUS completed candle (its high + low).
  2. A sweep occurs when a candle wicks beyond that range (high > range_high
     or low < range_low).
  3. Confirmation: that same candle CLOSES BACK INSIDE the range.
  4. Direction:
       swept HIGH + closed inside -> SELL, target = range LOW
       swept LOW  + closed inside -> BUY,  target = range HIGH
  5. The opposing range edge becomes the CRT target, which the SMC layer
     (order block + FVG + liquidity grab) then times the entry for.

Timeframes scanned: 1d (daily), 4h, 1h, 15m.
Kronos is an OPTIONAL filter — if disabled/unavailable, setups still fire
with a neutral bias so CRT + SMC can run standalone.
"""
import logging
from datetime import datetime
from typing import Optional, Dict, List

import pandas as pd

from database import SessionLocal
from models import CRTLevel

logger = logging.getLogger(__name__)

# Timeframes we scan, in priority order (highest first)
CRT_TIMEFRAMES = ["1d", "4h", "1h", "15m"]

# How many recent candles to inspect for a sweep
_SWEEP_LOOKBACK = 5

# Cache: {symbol: {timeframe: level_dict}}
_crt_levels_cache: Dict[str, Dict[str, dict]] = {}


# ── Range marking ─────────────────────────────────────────────────────────────

def calculate_range(symbol: str, candles: pd.DataFrame, timeframe: str = "1d") -> Optional[Dict]:
    """
    Mark the previous completed candle's range (high/low).

    Args:
        symbol:    Trading pair
        candles:   DataFrame with OHLCV (timestamp, open, high, low, close)
        timeframe: '1d' | '4h' | '1h' | '15m'

    Returns:
        dict with range_high, range_low, range, timeframe, date
    """
    try:
        if candles is None or len(candles) < 2:
            return None

        prev = candles.iloc[-2]
        range_high = float(prev["high"])
        range_low = float(prev["low"])

        if range_high <= range_low:
            return None

        ts = prev.get("timestamp")
        if ts is not None and hasattr(ts, "strftime"):
            stamp = ts.strftime("%Y-%m-%d %H:%M")
        else:
            stamp = datetime.utcnow().strftime("%Y-%m-%d %H:%M")

        result = {
            "symbol": symbol,
            "timeframe": timeframe,
            "range_high": range_high,
            "range_low": range_low,
            "range": range_high - range_low,
            "date": stamp,
            # legacy aliases so existing callers keep working
            "pdh": range_high,
            "pdl": range_low,
        }

        _crt_levels_cache.setdefault(symbol, {})[timeframe] = result
        logger.info(f"[crt] {symbol} {timeframe} range "
                    f"H={range_high:.5f} L={range_low:.5f} ({result['range']:.5f})")
        return result

    except Exception as e:
        logger.error(f"[crt] range calc error {symbol} {timeframe}: {e}")
        return None


# Backwards-compatible alias (daily range)
def calculate_pdh_pdl(symbol: str, daily_candles: pd.DataFrame) -> Optional[Dict]:
    return calculate_range(symbol, daily_candles, timeframe="1d")


# ── Sweep detection ───────────────────────────────────────────────────────────

def detect_sweep(symbol: str, candles: pd.DataFrame,
                 range_high: float, range_low: float,
                 timeframe: str = "1d") -> Optional[Dict]:
    """
    Detect a sweep of the range edge with a close back inside.

    Scans the most recent candles (newest first) for:
      - high > range_high AND close < range_high  -> SELL (target range_low)
      - low  < range_low  AND close > range_low   -> BUY  (target range_high)
    """
    try:
        if candles is None or len(candles) < 3:
            return None

        recent = candles.tail(_SWEEP_LOOKBACK)

        for idx in range(len(recent) - 1, -1, -1):
            candle = recent.iloc[idx]
            high = float(candle["high"])
            low = float(candle["low"])
            close = float(candle["close"])

            swept_high = high > range_high and close < range_high
            swept_low = low < range_low and close > range_low

            if swept_high:
                logger.info(f"[crt] {symbol} {timeframe} SWEPT HIGH — "
                            f"H={range_high:.5f} wick={high:.5f} close={close:.5f}")
                return {
                    "symbol": symbol,
                    "timeframe": timeframe,
                    "sweep_type": "HIGH",
                    "direction": "SELL",
                    "range_high": range_high,
                    "range_low": range_low,
                    "pdh": range_high,
                    "pdl": range_low,
                    "sweep_candle_high": high,
                    "sweep_candle_close": close,
                    "confirmed": True,
                    "target": range_low,
                    "timestamp": datetime.utcnow().isoformat(),
                }

            if swept_low:
                logger.info(f"[crt] {symbol} {timeframe} SWEPT LOW — "
                            f"L={range_low:.5f} wick={low:.5f} close={close:.5f}")
                return {
                    "symbol": symbol,
                    "timeframe": timeframe,
                    "sweep_type": "LOW",
                    "direction": "BUY",
                    "range_high": range_high,
                    "range_low": range_low,
                    "pdh": range_high,
                    "pdl": range_low,
                    "sweep_candle_low": low,
                    "sweep_candle_close": close,
                    "confirmed": True,
                    "target": range_high,
                    "timestamp": datetime.utcnow().isoformat(),
                }

        return None

    except Exception as e:
        logger.error(f"[crt] sweep detection error {symbol} {timeframe}: {e}")
        return None


# ── Kronos validation (OPTIONAL filter) ───────────────────────────────────────

def validate_with_kronos(crt_setup: Dict, kronos_bias: Optional[Dict]) -> bool:
    """
    Validate a CRT setup against Kronos bias.

    Kronos is OPTIONAL: if it is disabled or unavailable, the setup is
    ACCEPTED with a neutral bias so CRT + SMC can run standalone.
    When Kronos IS available, it must agree with the trade direction.
    """
    symbol = crt_setup.get("symbol", "?")
    direction = crt_setup.get("direction")

    # No bias available -> allow (neutral mode)
    if not kronos_bias:
        logger.info(f"[crt] {symbol} no Kronos bias — accepting setup (neutral mode)")
        return True

    bias = kronos_bias.get("bias", "NEUTRAL")

    # Neutral Kronos reading -> allow
    if bias == "NEUTRAL":
        logger.info(f"[crt] {symbol} Kronos NEUTRAL — accepting {direction} setup")
        return True

    if direction == "BUY" and bias == "BULLISH":
        logger.info(f"[crt] {symbol} BUY confirmed by BULLISH Kronos")
        return True

    if direction == "SELL" and bias == "BEARISH":
        logger.info(f"[crt] {symbol} SELL confirmed by BEARISH Kronos")
        return True

    logger.info(f"[crt] {symbol} {direction} rejected — Kronos bias={bias}")
    return False


# ── Persistence ───────────────────────────────────────────────────────────────

def store_crt_level(crt_setup: Dict):
    """Store a confirmed CRT level in the database."""
    db = SessionLocal()
    try:
        symbol = crt_setup["symbol"]
        timeframe = crt_setup.get("timeframe", "1d")
        date = datetime.utcnow().date().isoformat()

        existing = db.query(CRTLevel).filter(
            CRTLevel.symbol == symbol,
            CRTLevel.date == date,
            CRTLevel.timeframe == timeframe,
        ).first()

        if existing:
            existing.sweep_type = crt_setup["sweep_type"]
            existing.sweep_confirmed = 1
            existing.pdh = crt_setup.get("range_high")
            existing.pdl = crt_setup.get("range_low")
        else:
            db.add(CRTLevel(
                symbol=symbol,
                date=date,
                timeframe=timeframe,
                pdh=crt_setup.get("range_high"),
                pdl=crt_setup.get("range_low"),
                sweep_type=crt_setup["sweep_type"],
                sweep_confirmed=1,
            ))

        db.commit()
        logger.info(f"[crt] stored {symbol} {timeframe} level")

    except Exception as e:
        logger.error(f"[crt] db store error: {e}")
        db.rollback()
    finally:
        db.close()


# ── Cache access ──────────────────────────────────────────────────────────────

def get_cached_levels(symbol: Optional[str] = None) -> Dict:
    """
    Get cached CRT levels.
      - get_cached_levels()        -> {symbol: {timeframe: level}}
      - get_cached_levels("XAUUSD")-> {timeframe: level}
    """
    if symbol:
        return _crt_levels_cache.get(symbol, {})
    return _crt_levels_cache.copy()


def get_level(symbol: str, timeframe: str) -> Optional[Dict]:
    """Get the cached range for one symbol + timeframe."""
    return _crt_levels_cache.get(symbol, {}).get(timeframe)


# ── Multi-timeframe scan ──────────────────────────────────────────────────────

def scan_symbol(symbol: str, timeframes: Optional[List[str]] = None) -> List[Dict]:
    """
    Scan one symbol across all CRT timeframes and return every confirmed sweep.

    Returns a list of setup dicts (may be empty).
    """
    from modules.market_data_forex import get_candles

    timeframes = timeframes or CRT_TIMEFRAMES
    setups: List[Dict] = []

    for tf in timeframes:
        try:
            candles = get_candles(symbol, timeframe=tf, limit=60)
            if candles is None or len(candles) < 3:
                continue

            level = calculate_range(symbol, candles, timeframe=tf)
            if not level:
                continue

            sweep = detect_sweep(symbol, candles, level["range_high"],
                                 level["range_low"], timeframe=tf)
            if sweep:
                setups.append(sweep)

        except Exception as e:
            logger.error(f"[crt] scan error {symbol} {tf}: {e}")
            continue

    return setups


def update_all_ranges():
    """Mark ranges for all forex pairs across every CRT timeframe."""
    from config import FOREX_PAIRS
    from modules.market_data_forex import get_candles

    logger.info("[crt] updating ranges for all pairs / timeframes")

    for symbol in FOREX_PAIRS:
        for tf in CRT_TIMEFRAMES:
            try:
                candles = get_candles(symbol, timeframe=tf, limit=60)
                if candles is not None and len(candles) >= 2:
                    calculate_range(symbol, candles, timeframe=tf)
            except Exception as e:
                logger.error(f"[crt] range update error {symbol} {tf}: {e}")

    logger.info(f"[crt] ranges updated for {len(_crt_levels_cache)} pairs")


# Backwards-compatible alias
def update_pdh_pdl_all_pairs():
    update_all_ranges()
