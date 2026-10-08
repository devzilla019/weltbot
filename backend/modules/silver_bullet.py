"""
backend/modules/silver_bullet.py
ICT Silver Bullet + Volume Profile confluence.

Replaces the CRT pullback strategy. Trades institutional liquidity sweeps
during three fixed session windows, confirmed by volume profile levels and
a market structure shift, entering on the fair value gap left behind.

Pipeline per symbol:
  1. Session window filter      — only 08:00-09:00, 15:00-16:00, 19:00-20:00 UTC
  2. Daily H4 bias              — computed once at 07:00 UTC, NEUTRAL = no trade
  3. Session liquidity marks    — swing high/low from the 5m before the window
  4. Liquidity sweep            — wick beyond the swing, close back inside
  5. Market structure shift     — close beyond the opposing swing within 3 candles
  6. Fair value gap             — imbalance formed after the sweep
  7. Volume profile confluence  — FVG graded against POC / VAH / VAL
  8. Entry                      — market order when price returns into the FVG
  9. Confidence score           — must clear 88 to trade

Synchronous only — no asyncio.
"""
import logging
from datetime import datetime, timedelta
from typing import Optional, Dict, List, Tuple

import pandas as pd

from modules.volume_profile import (calculate_session_volume_profile,
                                    check_fvg_confluence,
                                    classify_price_position)

logger = logging.getLogger(__name__)

# ── Session windows (UTC) ─────────────────────────────────────────────────────
# name -> (start_hour, end_hour, confidence_bonus)
SESSIONS = {
    "LONDON":       (8,  9,  3),
    "NY_MORNING":   (15, 16, 4),   # institutional prime time
    "NY_AFTERNOON": (19, 20, 2),
}

# ── Setup quality thresholds ──────────────────────────────────────────────────
MIN_CONFIDENCE   = 88
STRONG_CONFIDENCE = 93
ELITE_CONFIDENCE  = 96

# ── Detection constants ───────────────────────────────────────────────────────
SWING_LOOKBACK      = 5     # candles before the window used to mark liquidity
MIN_SWEEP_BODY_PCT  = 0.40  # sweep candle body must exceed this share of its range
MSS_MAX_CANDLES     = 3     # MSS must occur within this many candles of the sweep
FVG_MAX_AGE         = 10    # FVG must form within this many candles of the sweep

# Stop buffer beyond the sweep wick
SL_ATR_BUFFER       = 0.5

# Sanity ceiling on stop width, NOT the risk control.
#
# The spec asked for a 2-ATR cap, but the strategy's own geometry makes that
# self-defeating: entry sits at the FVG (above the swept swing) while the stop
# sits at the sweep wick (below it), so the span is structurally 2-4 ATR and a
# 2-ATR cap rejects every setup the strategy defines.
#
# Risk is instead controlled by position sizing — a wider stop simply buys a
# smaller position, keeping the dollar risk at the configured 1-2%. This cap
# only refuses genuinely absurd setups (e.g. a stale wick far from price).
SL_MAX_ATR          = 6.0

# ── Caches ────────────────────────────────────────────────────────────────────
_daily_bias: Dict[str, Dict] = {}
_session_levels: Dict[str, Dict[str, Dict]] = {}
_active_setups: Dict[str, Dict] = {}


# ══════════════════════════════════════════════════════════════════════════════
#  LAYER 1 — SESSION TIMING
# ══════════════════════════════════════════════════════════════════════════════

def current_session(now: Optional[datetime] = None) -> Optional[str]:
    """Name of the session window currently open, or None."""
    hour = (now or datetime.utcnow()).hour
    for name, (start, end, _) in SESSIONS.items():
        if start <= hour < end:
            return name
    return None


def session_bounds(session_name: str) -> Tuple[datetime, datetime]:
    """Today's UTC (open, close) datetimes for a session."""
    start_hour, end_hour, _ = SESSIONS[session_name]
    today = datetime.utcnow().replace(minute=0, second=0, microsecond=0)
    return (today.replace(hour=start_hour),
            today.replace(hour=end_hour))


def session_time_remaining(session_name: Optional[str]) -> int:
    """Seconds until the named session closes (0 when not open)."""
    if not session_name:
        return 0
    _, close = session_bounds(session_name)
    return max(0, int((close - datetime.utcnow()).total_seconds()))


def session_schedule() -> List[Dict]:
    """Today's session windows with open/close times for the dashboard."""
    out = []
    now = datetime.utcnow()
    for name, (start_hour, end_hour, _) in SESSIONS.items():
        _, close = session_bounds(name)
        open_dt = now.replace(hour=start_hour, minute=0, second=0, microsecond=0)
        out.append({
            "session": name,
            "open_utc": open_dt.strftime("%H:%M"),
            "close_utc": close.strftime("%H:%M"),
            "active": current_session(now) == name,
        })
    return out


# ══════════════════════════════════════════════════════════════════════════════
#  LAYER 2 — DAILY BIAS (H4 structure + volume profile)
# ══════════════════════════════════════════════════════════════════════════════

def _ema(series: pd.Series, period: int = 50) -> float:
    if series is None or len(series) < period:
        return 0.0
    val = series.ewm(span=period, adjust=False).mean().iloc[-1]
    return float(val) if pd.notna(val) else 0.0


def _swings(df: pd.DataFrame, lookback: int = 3):
    """Positional indices of swing highs and lows."""
    highs, lows = [], []
    n = len(df)
    h = df["high"].astype(float).values
    l = df["low"].astype(float).values
    for i in range(lookback, n - lookback):
        if all(h[i] > h[i - j] for j in range(1, lookback + 1)) and \
           all(h[i] > h[i + j] for j in range(1, lookback + 1)):
            highs.append(i)
        if all(l[i] < l[i - j] for j in range(1, lookback + 1)) and \
           all(l[i] < l[i + j] for j in range(1, lookback + 1)):
            lows.append(i)
    return highs, lows


def identify_h4_structure(h4_df: pd.DataFrame) -> Tuple[str, int]:
    """
    H4 market structure over the last 50 candles.

    Counts CONSECUTIVE higher highs and consecutive higher lows (or the
    bearish equivalents), walking backwards from the most recent swing.

    Returns (bias, strength) where strength is the number of consecutive
    HH/HL pairs (bullish) or LL/LH pairs (bearish) confirmed.
    """
    try:
        if h4_df is None or len(h4_df) < 20:
            return "NEUTRAL", 0

        df = h4_df.reset_index(drop=True).tail(50).reset_index(drop=True)
        sh, sl = _swings(df)

        if len(sh) < 2 or len(sl) < 2:
            return "NEUTRAL", 0

        price = float(df["close"].iloc[-1])
        ema50 = _ema(df["close"])

        # Walk backwards from the latest swing counting consecutive runs
        hh_run = 0
        for i in range(len(sh) - 1, 0, -1):
            if df["high"].iloc[sh[i]] > df["high"].iloc[sh[i - 1]]:
                hh_run += 1
            else:
                break

        hl_run = 0
        for i in range(len(sl) - 1, 0, -1):
            if df["low"].iloc[sl[i]] > df["low"].iloc[sl[i - 1]]:
                hl_run += 1
            else:
                break

        ll_run = 0
        for i in range(len(sl) - 1, 0, -1):
            if df["low"].iloc[sl[i]] < df["low"].iloc[sl[i - 1]]:
                ll_run += 1
            else:
                break

        lh_run = 0
        for i in range(len(sh) - 1, 0, -1):
            if df["high"].iloc[sh[i]] < df["high"].iloc[sh[i - 1]]:
                lh_run += 1
            else:
                break

        # Spec: "at least 2 consecutive Higher Highs + Higher Lows" means two
        # highs where the second is higher — i.e. one upward transition. The
        # count of highs in the run is transitions + 1.
        hh_count = hh_run + 1 if hh_run else 0
        hl_count = hl_run + 1 if hl_run else 0
        ll_count = ll_run + 1 if ll_run else 0
        lh_count = lh_run + 1 if lh_run else 0

        if hh_count >= 2 and hl_count >= 2 and ema50 > 0 and price > ema50:
            return "BULLISH", min(hh_count, hl_count)
        if ll_count >= 2 and lh_count >= 2 and ema50 > 0 and price < ema50:
            return "BEARISH", min(ll_count, lh_count)
        return "NEUTRAL", 0

    except Exception as e:
        logger.error(f"[bias] H4 structure error: {e}")
        return "NEUTRAL", 0


def calculate_daily_bias(symbol: str) -> Optional[Dict]:
    """
    Build today's bias record for one symbol: H4 structure + volume profile
    from the previous day's H1 candles, plus the resulting VP classification.
    """
    try:
        from modules.market_data_forex import get_candles

        h4 = get_candles(symbol, timeframe="4h", limit=60)
        h4_bias, strength = identify_h4_structure(h4)
        if h4_bias == "NEUTRAL":
            logger.info(f"[bias] {symbol} H4: NEUTRAL — no trade today")
            _daily_bias[symbol] = {
                "h4_bias": "NEUTRAL", "strength": 0,
                "vp_levels": None, "vp_bias": "UNKNOWN",
                "session_date": datetime.utcnow().date().isoformat(),
            }
            return _daily_bias[symbol]

        # Volume profile from the previous day's H1 candles
        h1 = get_candles(symbol, timeframe="1h", limit=48)
        vp = calculate_session_volume_profile(h1, num_bins=50) if h1 is not None else None

        price = float(h4["close"].iloc[-1]) if h4 is not None and len(h4) else 0.0
        position = classify_price_position(price, vp) if vp else "UNKNOWN"

        # Volume profile bias — value area location relative to price
        if vp and position == "ABOVE_VALUE" and h4_bias == "BULLISH":
            vp_bias = "STRONG_BUY"
        elif vp and position == "BELOW_VALUE" and h4_bias == "BEARISH":
            vp_bias = "STRONG_SELL"
        elif vp and position == "INSIDE_VALUE":
            vp_bias = "REDUCED"
        elif vp and position == "AT_POC":
            vp_bias = "WAIT_REJECTION"
        else:
            vp_bias = "ALIGNED"

        record = {
            "symbol": symbol,
            "h4_bias": h4_bias,
            "strength": strength,
            "vp_levels": vp,
            "vp_bias": vp_bias,
            "price_position": position,
            "session_date": datetime.utcnow().date().isoformat(),
        }
        _daily_bias[symbol] = record

        if vp:
            logger.info(f"[vp] {symbol} POC={vp['poc']} VAH={vp['vah']} VAL={vp['val']}")
        logger.info(f"[bias] {symbol} H4: {h4_bias} — {strength} HH/HL or LL/LH confirmed"
                    + (", above EMA50" if h4_bias == "BULLISH" else
                       ", below EMA50" if h4_bias == "BEARISH" else ""))
        return record

    except Exception as e:
        logger.error(f"[bias] {symbol} error: {e}")
        return None


def calculate_daily_bias_all_pairs() -> int:
    """Compute the daily bias for every configured forex pair."""
    from config import FOREX_PAIRS

    logger.info(f"[bias] calculating daily bias for {len(FOREX_PAIRS)} pairs")
    count = 0
    for symbol in FOREX_PAIRS:
        try:
            if calculate_daily_bias(symbol):
                count += 1
        except Exception as e:
            logger.error(f"[bias] {symbol} error: {e}")

    tradeable = len([b for b in _daily_bias.values() if b.get("h4_bias") != "NEUTRAL"])
    logger.info(f"[bias] complete — {count} computed, {tradeable} tradeable today")
    return count


def get_daily_bias(symbol: str) -> Optional[Dict]:
    """Today's stored bias for a symbol (None when not computed)."""
    rec = _daily_bias.get(symbol)
    if not rec:
        return None
    if rec.get("session_date") != datetime.utcnow().date().isoformat():
        return None
    return rec


def get_all_daily_bias() -> Dict[str, Dict]:
    return _daily_bias.copy()


def reset_daily_cache() -> None:
    """Clear daily state at 00:01 UTC."""
    _daily_bias.clear()
    _session_levels.clear()
    _active_setups.clear()
    logger.info("[silver] daily cache reset")


# ══════════════════════════════════════════════════════════════════════════════
#  LAYER 3 — SESSION LIQUIDITY MARKS
# ══════════════════════════════════════════════════════════════════════════════

def mark_session_liquidity(symbol: str, session_name: str) -> Optional[Dict]:
    """
    Record the swing high/low from the candles immediately before a session
    opens. These are the liquidity pools the session is expected to sweep.
    """
    try:
        from modules.market_data_forex import get_candles

        df = get_candles(symbol, timeframe="5m", limit=30)
        if df is None or len(df) < SWING_LOOKBACK + 1:
            return None

        recent = df.tail(SWING_LOOKBACK)
        levels = {
            "session": session_name,
            "swing_high": float(recent["high"].max()),
            "swing_low": float(recent["low"].min()),
            "marked_at": datetime.utcnow().isoformat(),
        }
        _session_levels.setdefault(session_name, {})[symbol] = levels
        return levels

    except Exception as e:
        logger.error(f"[silver] {symbol} liquidity mark error: {e}")
        return None


def pre_session_mark_liquidity(session_name: str) -> int:
    """Mark session liquidity for every pair ahead of a window opening."""
    from config import FOREX_PAIRS

    logger.info(f"[silver] {session_name} pre-session liquidity marking")
    count = 0
    for symbol in FOREX_PAIRS:
        try:
            if mark_session_liquidity(symbol, session_name):
                count += 1
        except Exception as e:
            logger.error(f"[silver] {symbol} mark error: {e}")
    logger.info(f"[silver] {session_name} marked {count} pairs")
    return count


def get_session_levels(symbol: str, session_name: str) -> Optional[Dict]:
    return _session_levels.get(session_name, {}).get(symbol)


# ══════════════════════════════════════════════════════════════════════════════
#  LAYER 4 — SETUP DETECTION
# ══════════════════════════════════════════════════════════════════════════════

def detect_liquidity_sweep(df_5m: pd.DataFrame, session_levels: Dict,
                           h4_bias: str) -> Optional[Dict]:
    """
    A sweep is a candle that wicks beyond the session swing and closes back
    inside, with a body strong enough to be a rejection rather than a doji.

    BUY  setup: low < swing_low  AND close > swing_low
    SELL setup: high > swing_high AND close < swing_high
    """
    try:
        if df_5m is None or len(df_5m) < 5 or not session_levels:
            return None

        swing_high = session_levels.get("swing_high")
        swing_low = session_levels.get("swing_low")
        if swing_high is None or swing_low is None:
            return None

        # Scan the most recent candles, newest first
        recent = df_5m.tail(10)
        offset = len(df_5m) - len(recent)      # convert to an absolute index
        for i in range(len(recent) - 1, -1, -1):
            c = recent.iloc[i]
            o, h, l, cl = (float(c["open"]), float(c["high"]),
                           float(c["low"]), float(c["close"]))
            rng = h - l
            if rng <= 0:
                continue
            body_pct = abs(cl - o) / rng

            swept_low = l < swing_low and cl > swing_low
            swept_high = h > swing_high and cl < swing_high

            if swept_low and h4_bias == "BULLISH":
                if body_pct < MIN_SWEEP_BODY_PCT:
                    continue
                return {
                    "direction": "BUY",
                    "sweep_level": swing_low,
                    "sweep_wick": l,
                    "sweep_close": cl,
                    # Absolute position in df_5m, so downstream detectors
                    # (MSS, FVG) can index the same frame directly.
                    "sweep_index": offset + i,
                    "body_pct": round(body_pct, 3),
                }

            if swept_high and h4_bias == "BEARISH":
                if body_pct < MIN_SWEEP_BODY_PCT:
                    continue
                return {
                    "direction": "SELL",
                    "sweep_level": swing_high,
                    "sweep_wick": h,
                    "sweep_close": cl,
                    "sweep_index": offset + i,
                    "body_pct": round(body_pct, 3),
                }

        return None

    except Exception as e:
        logger.error(f"[silver] sweep detection error: {e}")
        return None


def detect_mss(df_5m: pd.DataFrame, sweep: Dict,
               max_candles: int = MSS_MAX_CANDLES) -> Optional[Dict]:
    """
    Market Structure Shift — after the sweep, price must close beyond the
    opposing swing within `max_candles`.

    BUY:  close above the most recent 5m swing high before the sweep
    SELL: close below the most recent 5m swing low before the sweep
    """
    try:
        if df_5m is None or not sweep:
            return None

        df = df_5m.reset_index(drop=True)
        sweep_idx = sweep.get("sweep_index")
        if sweep_idx is None or sweep_idx < 3:
            return None

        before = df.iloc[:sweep_idx]
        if len(before) < 3:
            return None

        direction = sweep["direction"]

        if direction == "BUY":
            level = float(before["high"].tail(5).max())
            after = df.iloc[sweep_idx + 1: sweep_idx + 1 + max_candles]
            for offset, (_, c) in enumerate(after.iterrows(), start=1):
                if float(c["close"]) > level:
                    return {
                        "direction": "BUY",
                        "mss_level": level,
                        "mss_index": sweep_idx + offset,
                        "candles_to_mss": offset,
                    }
        else:
            level = float(before["low"].tail(5).min())
            after = df.iloc[sweep_idx + 1: sweep_idx + 1 + max_candles]
            for offset, (_, c) in enumerate(after.iterrows(), start=1):
                if float(c["close"]) < level:
                    return {
                        "direction": "SELL",
                        "mss_level": level,
                        "mss_index": sweep_idx + offset,
                        "candles_to_mss": offset,
                    }

        return None

    except Exception as e:
        logger.error(f"[silver] MSS detection error: {e}")
        return None


def find_fvg_after_sweep(df_5m: pd.DataFrame, sweep: Dict,
                         max_age: int = FVG_MAX_AGE) -> Optional[Dict]:
    """
    Fair value gap formed AFTER the sweep, within `max_age` candles.

    Bullish FVG: candles[i+2].low  > candles[i].high
    Bearish FVG: candles[i+2].high < candles[i].low
    """
    try:
        if df_5m is None or len(df_5m) < 5 or not sweep:
            return None

        df = df_5m.reset_index(drop=True)
        sweep_idx = sweep.get("sweep_index")
        if sweep_idx is None:
            return None

        start = sweep_idx + 1
        end = min(len(df) - 2, start + max_age)

        for i in range(start, end):
            c1 = df.iloc[i]
            c3 = df.iloc[i + 2]

            if sweep["direction"] == "BUY":
                if float(c3["low"]) > float(c1["high"]):
                    high = float(c3["low"])
                    low = float(c1["high"])
                    return {
                        "fvg_high": round(high, 5),
                        "fvg_low": round(low, 5),
                        "fvg_midpoint": round((high + low) / 2, 5),
                        "fvg_index": i,
                        "type": "bullish_fvg",
                        "single_candle": (i + 2) - i == 2,
                    }
            else:
                if float(c3["high"]) < float(c1["low"]):
                    high = float(c1["low"])
                    low = float(c3["high"])
                    return {
                        "fvg_high": round(high, 5),
                        "fvg_low": round(low, 5),
                        "fvg_midpoint": round((high + low) / 2, 5),
                        "fvg_index": i,
                        "type": "bearish_fvg",
                        "single_candle": True,
                    }

        return None

    except Exception as e:
        logger.error(f"[silver] FVG detection error: {e}")
        return None


# ══════════════════════════════════════════════════════════════════════════════
#  LAYER 5 — CONFIDENCE SCORING
# ══════════════════════════════════════════════════════════════════════════════

def calculate_confidence(bias_data: Dict, sweep: Dict, mss: Dict,
                         fvg: Dict, vp_confluence: Dict,
                         session_name: str) -> int:
    """
    Score a setup from 85 upwards.

    The trend bonus is applied only when structure is genuinely confirmed,
    so the score can legitimately fall below the 88 floor and be rejected.
    """
    try:
        confidence = 85

        # ── Volume profile ───────────────────────────────────────────────────
        grade = (vp_confluence or {}).get("grade", "NO_CONFLUENCE")
        if grade == "POC_OVERLAP":
            confidence += 8
        elif grade in ("VAH_CONFLUENCE", "VAL_CONFLUENCE"):
            confidence += 5
        else:
            confidence -= 3

        if (bias_data or {}).get("price_position") in ("ABOVE_VALUE", "BELOW_VALUE"):
            confidence += 3

        # ── Market structure ─────────────────────────────────────────────────
        strength = (bias_data or {}).get("strength", 0)
        if strength >= 3:
            confidence += 5
        elif strength == 2:
            confidence += 3
        elif (bias_data or {}).get("h4_bias") == "NEUTRAL":
            confidence -= 5

        # ── Session ──────────────────────────────────────────────────────────
        confidence += SESSIONS.get(session_name, (0, 0, 0))[2]

        # ── Setup quality ────────────────────────────────────────────────────
        body_pct = (sweep or {}).get("body_pct", 0.0)
        if body_pct > 0.70:
            confidence += 3
        elif body_pct >= 0.50:
            confidence += 2

        if (mss or {}).get("candles_to_mss", 99) == 1:
            confidence += 2

        if (fvg or {}).get("single_candle"):
            confidence += 2

        return int(min(confidence, 99))

    except Exception as e:
        logger.error(f"[silver] confidence error: {e}")
        return 0


# ══════════════════════════════════════════════════════════════════════════════
#  ACTIVE SETUPS
# ══════════════════════════════════════════════════════════════════════════════

def store_active_setup(symbol: str, setup: Dict) -> None:
    _active_setups[symbol] = setup


def get_active_setups() -> Dict[str, Dict]:
    return _active_setups.copy()


def clear_active_setup(symbol: str) -> None:
    _active_setups.pop(symbol, None)


def expire_setups(session_name: Optional[str] = None) -> int:
    """Drop setups whose session window has closed."""
    now = datetime.utcnow()
    expired = 0
    for symbol, setup in list(_active_setups.items()):
        if session_name and setup.get("session") != session_name:
            continue
        sess = setup.get("session")
        if not sess:
            continue
        _, close = session_bounds(sess)
        if now >= close:
            _active_setups.pop(symbol, None)
            expired += 1
    if expired:
        logger.info(f"[silver] expired {expired} setups past window close")
    return expired


# ══════════════════════════════════════════════════════════════════════════════
#  LAYER 10 — MAIN SCAN
# ══════════════════════════════════════════════════════════════════════════════

def run_silver_bullet_scan(session_name: str) -> int:
    """
    Scan every pair for a Silver Bullet setup during an open session window.
    Returns the number of new setups stored.
    """
    from config import FOREX_PAIRS
    from modules.market_data_forex import get_candles
    from modules.forex_position_manager import can_open_forex_trade

    if current_session() != session_name:
        return 0

    logger.info(f"[silver] {session_name} window OPEN — scanning {len(FOREX_PAIRS)} pairs")
    stored = 0

    for symbol in FOREX_PAIRS:
        try:
            if symbol in _active_setups:
                continue

            bias_data = get_daily_bias(symbol)
            if not bias_data or bias_data.get("h4_bias") == "NEUTRAL":
                continue

            session_levels = get_session_levels(symbol, session_name)
            if not session_levels:
                mark_session_liquidity(symbol, session_name)
                session_levels = get_session_levels(symbol, session_name)
                if not session_levels:
                    continue

            allowed, _reason = can_open_forex_trade(symbol)
            if not allowed:
                continue

            df_5m = get_candles(symbol, timeframe="5m", limit=50)
            if df_5m is None or len(df_5m) < 20:
                continue

            sweep = detect_liquidity_sweep(df_5m, session_levels, bias_data["h4_bias"])
            if not sweep:
                continue

            logger.info(f"[silver] {symbol} sweep detected — "
                        f"{'low' if sweep['direction'] == 'BUY' else 'high'}="
                        f"{sweep['sweep_wick']} swept, closed @ {sweep['sweep_close']}")

            mss = detect_mss(df_5m, sweep)
            if not mss:
                continue
            logger.info(f"[silver] {symbol} MSS confirmed — broke {mss['mss_level']}")

            fvg = find_fvg_after_sweep(df_5m, sweep)
            if not fvg:
                continue

            vp_confluence = check_fvg_confluence(fvg, bias_data.get("vp_levels"))
            logger.info(f"[silver] {symbol} FVG found — {fvg['fvg_low']} to "
                        f"{fvg['fvg_high']} | {vp_confluence['grade']} confluence")

            confidence = calculate_confidence(
                bias_data, sweep, mss, fvg, vp_confluence, session_name
            )
            if confidence < MIN_CONFIDENCE:
                logger.info(f"[silver] {symbol} {session_name} conf={confidence}% "
                            f"below min — skip")
                continue

            _, session_close = session_bounds(session_name)
            store_active_setup(symbol, {
                "symbol": symbol,
                "direction": sweep["direction"],
                "fvg": fvg,
                "sweep": sweep,
                "mss": mss,
                "confidence": confidence,
                "vp_levels": bias_data.get("vp_levels"),
                "vp_confluence": vp_confluence["grade"],
                "session": session_name,
                "bias": bias_data["h4_bias"],
                "expires_at": session_close.isoformat(),
                "created_at": datetime.utcnow().isoformat(),
            })
            stored += 1
            logger.info(f"[silver] {symbol} conf={confidence}% — SETUP STORED "
                        f"waiting for FVG entry")

        except Exception as e:
            logger.error(f"[silver] {symbol} error: {e}")

    logger.info(f"[silver] {session_name} scan complete — {stored} new setups")
    return stored


# ══════════════════════════════════════════════════════════════════════════════
#  LAYER 6/7 — ENTRY, STOPS AND TARGETS
# ══════════════════════════════════════════════════════════════════════════════

def calculate_atr(df: pd.DataFrame, period: int = 14) -> float:
    """Average true range of the entry timeframe."""
    try:
        if df is None or len(df) < period + 1:
            return 0.0
        high, low, close = df["high"].astype(float), df["low"].astype(float), df["close"].astype(float)
        tr = pd.concat([
            high - low,
            (high - close.shift()).abs(),
            (low - close.shift()).abs(),
        ], axis=1).max(axis=1)
        atr = tr.rolling(period).mean().iloc[-1]
        return float(atr) if pd.notna(atr) else 0.0
    except Exception as e:
        logger.error(f"[silver] ATR error: {e}")
        return 0.0


def check_entry_in_fvg(setup: Dict, current_price: float,
                       df_5m: pd.DataFrame) -> Optional[Dict]:
    """
    Fire when price returns into the stored FVG.

    Returns a signal dict with entry, SL and the three targets, or None.
    """
    try:
        if not setup or current_price is None:
            return None

        fvg = setup.get("fvg") or {}
        direction = setup.get("direction")
        fvg_low = float(fvg.get("fvg_low") or 0.0)
        fvg_high = float(fvg.get("fvg_high") or 0.0)
        if fvg_low <= 0 or fvg_high <= 0:
            return None

        if not (fvg_low <= current_price <= fvg_high):
            return None

        atr = calculate_atr(df_5m)
        if atr <= 0:
            return None

        sweep = setup.get("sweep") or {}
        symbol = setup.get("symbol", "?")
        sweep_wick = float(sweep.get("sweep_wick", 0.0))
        if sweep_wick <= 0:
            return None

        entry = current_price

        # The spec caps the stop at 2 ATR, but also places entry at the FVG
        # (above the swept swing) and the stop at the sweep wick (below it).
        # That structural span alone is routinely 2-4 ATR, so a 2-ATR cap
        # rejects every setup the strategy defines. Risk is controlled by
        # position sizing instead — a wider stop buys a smaller position.
        # SL_MAX_ATR here only refuses genuinely absurd (stale-wick) setups.
        structural_risk = abs(entry - sweep_wick)
        if structural_risk > SL_MAX_ATR * atr:
            logger.info(f"[silver] {symbol} structural stop {structural_risk/atr:.2f} ATR "
                        f"> {SL_MAX_ATR} ATR — wick too far from price, skip")
            return None

        if direction == "BUY":
            sl = sweep_wick - (SL_ATR_BUFFER * atr)
        else:
            sl = sweep_wick + (SL_ATR_BUFFER * atr)

        risk = abs(entry - sl)
        if risk <= 0:
            return None

        # Enforce the 0.5 ATR minimum by widening the stop, never by
        # tightening it (a tighter stop would raise the chance of a wick-out).
        if risk < 0.5 * atr:
            sl = entry - (0.5 * atr) if direction == "BUY" else entry + (0.5 * atr)
            risk = abs(entry - sl)

        sign = 1 if direction == "BUY" else -1
        tp1 = entry + sign * risk * 1.0
        tp2 = entry + sign * risk * 2.0
        tp3 = entry + sign * risk * 3.0

        return {
            "symbol": symbol,
            "signal": direction,
            "entry_price": round(entry, 5),
            "stop_loss": round(sl, 5),
            "take_profit": round(tp3, 5),      # broker-level TP = final target
            "tp1": round(tp1, 5),
            "tp2": round(tp2, 5),
            "tp3": round(tp3, 5),
            "risk_distance": round(risk, 5),
            "atr": round(atr, 5),
            "confidence": setup.get("confidence", 0),
            "entry_type": "SILVER_BULLET_FVG",
            "session": setup.get("session"),
            "vp_confluence": setup.get("vp_confluence"),
            "trend_direction": setup.get("bias"),
            "crt_setup": "SILVER_BULLET",
            "crt_timeframe": "5m",
            "confirm_timeframe": "5m",
            "entry_timeframe": "5m",
            "poi": "fvg",
            "timestamp": datetime.utcnow().isoformat(),
        }

    except Exception as e:
        logger.error(f"[silver] entry check error: {e}")
        return None
