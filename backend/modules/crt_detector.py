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

# ── Cascade: which timeframes to use for confirmation + entry ─────────────────
# When a CRT sweep is found on the KEY timeframe, we drop down to:
#   confirm -> look for a POI (order block / breaker / FVG / S&R) that price respects
#   entry   -> look for the final SMC trigger (OB + FVG + liquidity grab)
CRT_CASCADE = {
    "1d":  {"confirm": "4h",  "entry": "15m"},
    "4h":  {"confirm": "1h",  "entry": "15m"},
    "1h":  {"confirm": "15m", "entry": "5m"},
    "15m": {"confirm": "5m",  "entry": "5m"},
}


def get_cascade(timeframe: str) -> Dict[str, str]:
    """Return {confirm, entry} timeframes for a given CRT timeframe."""
    return CRT_CASCADE.get(timeframe, {"confirm": "15m", "entry": "5m"})

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


# ══════════════════════════════════════════════════════════════════════════════
#  REFINED CRT WITH PULLBACK ENTRY
#  Trade WITH the H4 trend by finding the H1 pullback, then the sweep of that
#  pullback's range. This replaces the old per-pair PDH/PDL sweep logic.
# ══════════════════════════════════════════════════════════════════════════════

# H4 EMA used for the trend filter
_TREND_EMA_PERIOD = 50

# How many H1 candles back to look for pullback candidates
_PULLBACK_LOOKBACK = 20

# Swing detection lookback (bars either side of a pivot)
_SWING_LOOKBACK = 3


def _ema(series: pd.Series, period: int = _TREND_EMA_PERIOD) -> float:
    """Last EMA value of a series (0.0 when there is not enough data)."""
    if series is None or len(series) < period:
        return 0.0
    val = series.ewm(span=period, adjust=False).mean().iloc[-1]
    return float(val) if pd.notna(val) else 0.0


def _swing_indices(df: pd.DataFrame, lookback: int = _SWING_LOOKBACK):
    """Return (swing_high_idx, swing_low_idx) lists of positional indices."""
    highs, lows = [], []
    n = len(df)
    h = df["high"].values
    l = df["low"].values
    for i in range(lookback, n - lookback):
        if all(h[i] > h[i - j] for j in range(1, lookback + 1)) and \
           all(h[i] > h[i + j] for j in range(1, lookback + 1)):
            highs.append(i)
        if all(l[i] < l[i - j] for j in range(1, lookback + 1)) and \
           all(l[i] < l[i + j] for j in range(1, lookback + 1)):
            lows.append(i)
    return highs, lows


# ── STEP 1: trend direction filter ────────────────────────────────────────────

def identify_trend_direction(symbol: str, h4_df: pd.DataFrame) -> str:
    """
    Determine H4 market direction from structure (HH/HL vs LL/LH) AND EMA50.

    Both must agree — if structure and EMA50 conflict the result is NEUTRAL.

    Returns: 'BULLISH' | 'BEARISH' | 'NEUTRAL'
    """
    try:
        if h4_df is None or len(h4_df) < _TREND_EMA_PERIOD + 5:
            logger.info(f"[crt] {symbol} H4 trend: NEUTRAL (insufficient candles)")
            return "NEUTRAL"

        df = h4_df.reset_index(drop=True)
        sh_idx, sl_idx = _swing_indices(df)

        price = float(df["close"].iloc[-1])
        ema50 = _ema(df["close"])

        structure = "NEUTRAL"
        if len(sh_idx) >= 2 and len(sl_idx) >= 2:
            hh = df["high"].iloc[sh_idx[-1]] > df["high"].iloc[sh_idx[-2]]
            hl = df["low"].iloc[sl_idx[-1]] > df["low"].iloc[sl_idx[-2]]
            lh = df["high"].iloc[sh_idx[-1]] < df["high"].iloc[sh_idx[-2]]
            ll = df["low"].iloc[sl_idx[-1]] < df["low"].iloc[sl_idx[-2]]
            if hh and hl:
                structure = "BULLISH"
            elif lh and ll:
                structure = "BEARISH"

        ema_bias = "NEUTRAL"
        if ema50 > 0:
            ema_bias = "BULLISH" if price > ema50 else "BEARISH"

        if structure == "BULLISH" and ema_bias == "BULLISH":
            logger.info(f"[crt] {symbol} H4 trend: BULLISH (HH/HL confirmed, above EMA50)")
            return "BULLISH"
        if structure == "BEARISH" and ema_bias == "BEARISH":
            logger.info(f"[crt] {symbol} H4 trend: BEARISH (LL/LH confirmed, below EMA50)")
            return "BEARISH"

        logger.info(f"[crt] {symbol} H4 trend: NEUTRAL "
                    f"(structure={structure}, EMA50={ema_bias} — conflict or unclear)")
        return "NEUTRAL"

    except Exception as e:
        logger.error(f"[crt] trend error {symbol}: {e}")
        return "NEUTRAL"


# ── STEP 2: CRT range identification (refined) ────────────────────────────────

def identify_pullback_candles(h1_df: pd.DataFrame, trend: str) -> List[Dict]:
    """
    Find candidate CRT range candles — the counter-trend pullback candles.

    BULLISH: bearish candles (pullback down) — each candidate carries its
             high/low so the sweep of its low can be tested later.
    BEARISH: bullish candles (pullback up) — sweep of its high is tested.

    Returns a list of dicts, oldest first, each with:
        index, candle_index, high, low, open, close, body_pct
    """
    try:
        if h1_df is None or len(h1_df) < 5:
            return []
        if trend not in ("BULLISH", "BEARISH"):
            return []

        df = h1_df.reset_index(drop=True)
        start = max(0, len(df) - _PULLBACK_LOOKBACK)
        candidates: List[Dict] = []

        for i in range(start, len(df) - 1):
            c = df.iloc[i]
            o, h, l, cl = float(c["open"]), float(c["high"]), float(c["low"]), float(c["close"])
            rng = h - l
            if rng <= 0:
                continue

            is_bearish = cl < o
            is_bullish = cl > o

            if trend == "BULLISH" and is_bearish:
                candidates.append({
                    "index": i,
                    "candle_index": i,
                    "open": o, "high": h, "low": l, "close": cl,
                    "body_pct": abs(cl - o) / rng,
                    "direction": "BEARISH",
                })
            elif trend == "BEARISH" and is_bullish:
                candidates.append({
                    "index": i,
                    "candle_index": i,
                    "open": o, "high": h, "low": l, "close": cl,
                    "body_pct": abs(cl - o) / rng,
                    "direction": "BULLISH",
                })

        return candidates

    except Exception as e:
        logger.error(f"[crt] pullback candle error: {e}")
        return []


def validate_crt_range(candle: Dict, next_candle) -> bool:
    """
    A CRT range stays valid when the NEXT candle closes INSIDE the range —
    i.e. it does not close above the candle's high (range invalidated) and
    does not close below the candle's low (pullback too deep).
    """
    try:
        if candle is None or next_candle is None:
            return False
        n_close = float(next_candle["close"])
        return float(candle["low"]) <= n_close <= float(candle["high"])
    except Exception as e:
        logger.error(f"[crt] range validation error: {e}")
        return False


def detect_crt_sweep(h1_df: pd.DataFrame, crt_range_candle: Dict, trend: str) -> Optional[Dict]:
    """
    Look for a liquidity sweep of the CRT range after the range candle.

    BULLISH: candle_low < crt_low AND candle_close > crt_low
             (wick below the range low, close back above it)
    BEARISH: candle_high > crt_high AND candle_close < crt_high
             (wick above the range high, close back below it)

    Returns a sweep dict or None.
    """
    try:
        if h1_df is None or crt_range_candle is None:
            return None
        if trend not in ("BULLISH", "BEARISH"):
            return None

        df = h1_df.reset_index(drop=True)
        idx = crt_range_candle["index"]

        crt_high = float(crt_range_candle["high"])
        crt_low = float(crt_range_candle["low"])

        # Scan forward from the candle AFTER the range candle
        for i in range(idx + 1, len(df)):
            c = df.iloc[i]
            high = float(c["high"])
            low = float(c["low"])
            close = float(c["close"])

            if trend == "BULLISH":
                if low < crt_low and close > crt_low:
                    return {
                        "sweep_type": "LOW",
                        "direction": "BUY",
                        "trend_direction": trend,
                        "crt_high": crt_high,
                        "crt_low": crt_low,
                        "crt_range": crt_high - crt_low,
                        "sweep_candle_low": low,
                        "sweep_candle_high": high,
                        "sweep_candle_close": close,
                        "sweep_index": i,
                        "body_pct": abs(close - float(c["open"])) / (high - low) if high > low else 0.0,
                        "range_high": crt_high,
                        "range_low": crt_low,
                        "pdh": crt_high,
                        "pdl": crt_low,
                        "target": crt_high,
                        "confirmed": True,
                    }
                # Pullback too deep — range is invalidated, stop looking
                if close < crt_low:
                    return None
            else:
                if high > crt_high and close < crt_high:
                    return {
                        "sweep_type": "HIGH",
                        "direction": "SELL",
                        "trend_direction": trend,
                        "crt_high": crt_high,
                        "crt_low": crt_low,
                        "crt_range": crt_high - crt_low,
                        "sweep_candle_high": high,
                        "sweep_candle_low": low,
                        "sweep_candle_close": close,
                        "sweep_index": i,
                        "body_pct": abs(close - float(c["open"])) / (high - low) if high > low else 0.0,
                        "range_high": crt_high,
                        "range_low": crt_low,
                        "pdh": crt_high,
                        "pdl": crt_low,
                        "target": crt_low,
                        "confirmed": True,
                    }
                # Pullback too deep — range is invalidated, stop looking
                if close > crt_high:
                    return None

        return None

    except Exception as e:
        logger.error(f"[crt] sweep error: {e}")
        return None


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


def scan_symbol_refined(symbol: str) -> Optional[Dict]:
    """
    Refined CRT with Pullback Entry scan for one symbol.

    H4 -> trend direction (HH/HL + EMA50, both must agree)
    H1 -> pullback CRT range candle, validated, then swept

    Returns a setup dict (ready for the SMC entry layer) or None.
    """
    from modules.market_data_forex import get_candles

    try:
        h4 = get_candles(symbol, timeframe="4h", limit=200)
        trend = identify_trend_direction(symbol, h4)
        if trend == "NEUTRAL":
            return None

        h1 = get_candles(symbol, timeframe="1h", limit=100)
        if h1 is None or len(h1) < 10:
            return None

        candidates = identify_pullback_candles(h1, trend)
        if not candidates:
            logger.info(f"[crt] {symbol} no {trend.lower()} pullback candles on H1")
            return None

        h1 = h1.reset_index(drop=True)
        n = len(h1)

        valid_count = 0
        # Newest candidates first — the most recent range is the tradeable one
        for cand in reversed(candidates):
            idx = cand["index"]
            if idx + 1 >= n:
                continue

            if not validate_crt_range(cand, h1.iloc[idx + 1]):
                continue
            valid_count += 1

            sweep = detect_crt_sweep(h1, cand, trend)
            if not sweep:
                continue

            side = "bearish" if trend == "BULLISH" else "bullish"
            logger.info(f"[crt] {symbol} H1 pullback: {len(candidates)} {side} "
                        f"candles identified, range valid")
            logger.info(f"[crt] {symbol} SWEEP CONFIRMED — "
                        f"{'low' if sweep['sweep_type'] == 'LOW' else 'high'} swept, "
                        f"closed back inside, {trend.lower()} setup")

            sweep.update({
                "symbol": symbol,
                "timeframe": "1h",
                "trend_direction": trend,
                "crt_high": cand["high"],
                "crt_low": cand["low"],
                "crt_range": cand["high"] - cand["low"],
                "range_high": cand["high"],
                "range_low": cand["low"],
                "pdh": cand["high"],
                "pdl": cand["low"],
                "pullback_high": cand["high"],
                "pullback_low": cand["low"],
                "crt_pullback": True,
                "_df_h1": h1,
                "timestamp": datetime.utcnow().isoformat(),
            })
            _crt_levels_cache.setdefault(symbol, {})["1h"] = {
                "symbol": symbol,
                "timeframe": "1h",
                "range_high": cand["high"],
                "range_low": cand["low"],
                "range": cand["high"] - cand["low"],
                "date": datetime.utcnow().strftime("%Y-%m-%d %H:%M"),
                "pdh": cand["high"],
                "pdl": cand["low"],
                "trend_direction": trend,
            }
            return sweep

        logger.info(f"[crt] {symbol} H1 pullback: {len(candidates)} {side} "
                    f"candles identified, {valid_count} ranges valid, no sweep yet")
        return None

    except Exception as e:
        logger.error(f"[crt] refined scan error {symbol}: {e}")
        return None


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
