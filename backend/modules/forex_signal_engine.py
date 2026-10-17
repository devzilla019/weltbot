"""
backend/modules/forex_signal_engine.py

Forex signal logic. Two layers live here:

1. **SMC entry primitives** (order blocks, FVGs, liquidity grabs, Quasimodo,
   premium/discount) — the CRT/pullback toolkit. `signal_engine` and
   `crypto_strategy` still import these, so they are kept intact.

2. **The Silver Bullet signal engine** (everything below the
   `SILVER BULLET SIGNAL ENGINE` banner). This is the authoritative, testable
   implementation of the forex strategy:

       session window -> liquidity sweep -> MSS -> FVG -> volume-profile
       confluence -> heuristic confidence -> hard 88 gate -> state machine ->
       session-scoped pending store -> FVG-retest entry

   `silver_bullet` orchestrates this engine; it does not re-implement it. The
   daily H4 bias and the previous-day volume profile are PASSED IN from
   Phase 2 rather than recomputed here, so one symbol can never be scored
   against two different sets of levels.

A confidence score is a rule-based RANKING of setup quality. It is not a
probability, and a score of 94 does not mean a 94% chance of success.
"""
import pandas as pd
import numpy as np
from typing import Optional, Dict, List, Tuple
import logging
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


def detect_order_block(df: pd.DataFrame, direction: str) -> Optional[Dict]:
    """
    Detect Order Block - last opposing candle before impulsive move
    
    Args:
        df: 5m or 15m candles
        direction: BUY or SELL
    
    Returns:
        dict with ob_high, ob_low, ob_index
    """
    try:
        if len(df) < 10:
            return None
        
        recent = df.tail(20)
        
        if direction == 'BUY':
            for i in range(len(recent) - 5, 0, -1):
                candle = recent.iloc[i]
                next_candles = recent.iloc[i+1:i+4]
                
                is_bearish = candle['close'] < candle['open']
                next_bullish = (next_candles['close'] > next_candles['open']).sum() >= 2
                impulsive = (next_candles['close'].max() - candle['close']) > (candle['high'] - candle['low']) * 2
                
                if is_bearish and next_bullish and impulsive:
                    return {
                        'ob_high': float(candle['high']),
                        'ob_low': float(candle['low']),
                        'ob_index': i,
                        'type': 'bullish_ob'
                    }
        
        else:
            for i in range(len(recent) - 5, 0, -1):
                candle = recent.iloc[i]
                next_candles = recent.iloc[i+1:i+4]
                
                is_bullish = candle['close'] > candle['open']
                next_bearish = (next_candles['close'] < next_candles['open']).sum() >= 2
                impulsive = (candle['close'] - next_candles['close'].min()) > (candle['high'] - candle['low']) * 2
                
                if is_bullish and next_bearish and impulsive:
                    return {
                        'ob_high': float(candle['high']),
                        'ob_low': float(candle['low']),
                        'ob_index': i,
                        'type': 'bearish_ob'
                    }
        
        return None
        
    except Exception as e:
        logger.error(f"[smc] order block detection error: {e}")
        return None


def detect_fvg(df: pd.DataFrame, direction: str) -> Optional[Dict]:
    """
    Detect Fair Value Gap - 3 candle imbalance
    
    Args:
        df: 5m or 15m candles
        direction: BUY or SELL
    
    Returns:
        dict with fvg_high, fvg_low, fvg_index
    """
    try:
        if len(df) < 5:
            return None
        
        recent = df.tail(10)
        
        for i in range(len(recent) - 3, 0, -1):
            c1 = recent.iloc[i]
            c2 = recent.iloc[i + 1]
            c3 = recent.iloc[i + 2]
            
            if direction == 'BUY':
                gap = c3['low'] > c1['high']
                if gap:
                    return {
                        'fvg_high': float(c3['low']),
                        'fvg_low': float(c1['high']),
                        'fvg_index': i,
                        'type': 'bullish_fvg'
                    }
            
            else:
                gap = c3['high'] < c1['low']
                if gap:
                    return {
                        'fvg_high': float(c1['low']),
                        'fvg_low': float(c3['high']),
                        'fvg_index': i,
                        'type': 'bearish_fvg'
                    }
        
        return None
        
    except Exception as e:
        logger.error(f"[smc] fvg detection error: {e}")
        return None


def detect_liquidity_grab(df: pd.DataFrame, direction: str) -> bool:
    """
    Detect liquidity grab - wick below recent lows (BUY) or above highs (SELL)
    
    Args:
        df: 5m or 15m candles
        direction: BUY or SELL
    
    Returns:
        True if liquidity grab detected
    """
    try:
        if len(df) < 10:
            return False
        
        recent = df.tail(10)
        last = recent.iloc[-1]
        prev_candles = recent.iloc[:-1]
        
        if direction == 'BUY':
            recent_low = prev_candles['low'].min()
            wick_below = last['low'] < recent_low
            close_above = last['close'] > recent_low
            return wick_below and close_above
        
        else:
            recent_high = prev_candles['high'].max()
            wick_above = last['high'] > recent_high
            close_below = last['close'] < recent_high
            return wick_above and close_below
        
    except Exception as e:
        logger.error(f"[smc] liquidity grab detection error: {e}")
        return False


def detect_breaker_block(df: pd.DataFrame, direction: str) -> Optional[Dict]:
    """
    Detect a Breaker Block — a failed order block that price broke through
    and now acts as support/resistance in the opposite direction.

    BUY  breaker: a bearish OB that price broke ABOVE, now retested as support
    SELL breaker: a bullish OB that price broke BELOW, now retested as resistance
    """
    try:
        if len(df) < 15:
            return None

        recent = df.tail(25)

        if direction == 'BUY':
            for i in range(len(recent) - 6, 0, -1):
                c = recent.iloc[i]
                after = recent.iloc[i + 1:]
                if c['close'] < c['open']:                       # bearish candle
                    broke_above = (after['close'] > c['high']).any()
                    if broke_above:
                        return {
                            'bb_high': float(c['high']),
                            'bb_low': float(c['low']),
                            'bb_index': i,
                            'type': 'bullish_breaker',
                        }
        else:
            for i in range(len(recent) - 6, 0, -1):
                c = recent.iloc[i]
                after = recent.iloc[i + 1:]
                if c['close'] > c['open']:                       # bullish candle
                    broke_below = (after['close'] < c['low']).any()
                    if broke_below:
                        return {
                            'bb_high': float(c['high']),
                            'bb_low': float(c['low']),
                            'bb_index': i,
                            'type': 'bearish_breaker',
                        }

        return None

    except Exception as e:
        logger.error(f"[smc] breaker block detection error: {e}")
        return None


def detect_support_resistance(df: pd.DataFrame, direction: str) -> Optional[Dict]:
    """
    Detect a key support/resistance level from recent swing highs/lows.
    BUY  -> nearest swing LOW below price (support)
    SELL -> nearest swing HIGH above price (resistance)
    """
    try:
        if len(df) < 20:
            return None

        recent = df.tail(40)
        highs = recent['high'].values
        lows = recent['low'].values
        price = float(recent['close'].iloc[-1])

        # Simple swing detection (3-bar pivot)
        swing_highs, swing_lows = [], []
        for i in range(2, len(recent) - 2):
            if highs[i] > highs[i-1] and highs[i] > highs[i-2] and \
               highs[i] > highs[i+1] and highs[i] > highs[i+2]:
                swing_highs.append(float(highs[i]))
            if lows[i] < lows[i-1] and lows[i] < lows[i-2] and \
               lows[i] < lows[i+1] and lows[i] < lows[i+2]:
                swing_lows.append(float(lows[i]))

        if direction == 'BUY':
            below = [l for l in swing_lows if l < price]
            if below:
                level = max(below)          # nearest support
                return {'sr_level': level, 'type': 'support'}
        else:
            above = [h for h in swing_highs if h > price]
            if above:
                level = min(above)          # nearest resistance
                return {'sr_level': level, 'type': 'resistance'}

        return None

    except Exception as e:
        logger.error(f"[smc] support/resistance detection error: {e}")
        return None


def find_poi(df: pd.DataFrame, direction: str, current_price: float,
             atr: float) -> Optional[Dict]:
    """
    Find a Point of Interest on the CONFIRMATION timeframe that price is
    respecting: order block, breaker block, FVG, or support/resistance.

    Returns the strongest POI found (OB > breaker > FVG > S/R), or None.
    """
    try:
        tolerance = max(atr * 0.5, current_price * 0.0002)

        # 1) Order block
        ob = detect_order_block(df, direction)
        if ob and (ob['ob_low'] - tolerance) <= current_price <= (ob['ob_high'] + tolerance):
            return {'kind': 'order_block', **ob}

        # 2) Breaker block
        bb = detect_breaker_block(df, direction)
        if bb and (bb['bb_low'] - tolerance) <= current_price <= (bb['bb_high'] + tolerance):
            return {'kind': 'breaker_block', **bb}

        # 3) Fair value gap
        fvg = detect_fvg(df, direction)
        if fvg:
            dist = min(abs(current_price - fvg['fvg_high']),
                       abs(current_price - fvg['fvg_low']))
            if dist <= tolerance:
                return {'kind': 'fvg', **fvg}

        # 4) Support / resistance
        sr = detect_support_resistance(df, direction)
        if sr and abs(current_price - sr['sr_level']) <= tolerance:
            return {'kind': 'support_resistance', **sr}

        return None

    except Exception as e:
        logger.error(f"[smc] POI detection error: {e}")
        return None


def check_entry_condition(crt_setup: Dict, current_price: float, df_5m: pd.DataFrame) -> Optional[Dict]:
    """
    Check if SMC entry conditions are met
    
    Args:
        crt_setup: CRT setup from detector
        current_price: Current market price
        df_5m: 5-minute candles
    
    Returns:
        Entry signal dict or None
    """
    try:
        direction = crt_setup['direction']
        symbol = crt_setup['symbol']
        
        ob = detect_order_block(df_5m, direction)
        fvg = detect_fvg(df_5m, direction)
        liq_grab = detect_liquidity_grab(df_5m, direction)
        
        if not ob:
            logger.debug(f"[smc] {symbol} no order block")
            return None
        
        in_ob_zone = ob['ob_low'] <= current_price <= ob['ob_high']
        
        if not in_ob_zone:
            logger.debug(f"[smc] {symbol} price not in OB zone")
            return None
        
        if not fvg:
            logger.debug(f"[smc] {symbol} no FVG detected")
            return None
        
        atr = calculate_atr(df_5m)
        
        # Asset-agnostic proximity: FVG must be within half an ATR of price.
        # Works for forex (pips), metals and crypto (dollars) alike.
        fvg_distance = min(abs(current_price - fvg['fvg_high']), abs(current_price - fvg['fvg_low']))
        fvg_nearby = fvg_distance < (0.5 * atr) if atr > 0 else True
        
        if direction == 'BUY':
            entry = current_price
            sl = crt_setup['sweep_candle_low'] - (0.5 * atr)
            tp = crt_setup['target']
        else:
            entry = current_price
            sl = crt_setup['sweep_candle_high'] + (0.5 * atr)
            tp = crt_setup['target']
        
        risk = abs(entry - sl)
        reward = abs(tp - entry)
        rr = reward / risk if risk > 0 else 0
        
        if rr < 2.0:
            logger.info(f"[smc] {symbol} R:R too low: {rr:.2f}")
            return None
        
        confidence = 85
        if fvg_nearby:
            confidence += 2
        if liq_grab:
            confidence += 3
        if fvg and in_ob_zone:
            confidence += 2
        if rr >= 3.0:
            confidence += 1
        
        signal = {
            'symbol': symbol,
            'signal': direction,
            'entry_price': round(entry, 5),
            'stop_loss': round(sl, 5),
            'take_profit': round(tp, 5),
            'confidence': min(confidence, 99),
            'risk_reward': round(rr, 2),
            'order_block': ob,
            'fvg': fvg,
            'liquidity_grab': liq_grab,
            'crt_setup': crt_setup['sweep_type'],
            'crt_timeframe': crt_setup.get('timeframe', '1d'),
            'confirm_timeframe': crt_setup.get('confirm_timeframe'),
            'entry_timeframe': crt_setup.get('entry_timeframe', '5m'),
            'poi': crt_setup.get('poi'),
            'pdh': crt_setup.get('range_high', crt_setup.get('pdh')),
            'pdl': crt_setup.get('range_low', crt_setup.get('pdl')),
            'timestamp': datetime.utcnow().isoformat()
        }
        
        logger.info(f"[smc] {symbol} ENTRY CONFIRMED — {direction} @ {entry:.5f} "
                    f"conf={confidence}% R:R={rr:.2f} "
                    f"[CRT {crt_setup.get('timeframe','?')} → "
                    f"confirm {crt_setup.get('confirm_timeframe','?')} → "
                    f"entry {crt_setup.get('entry_timeframe','?')}]")
        return signal
        
    except Exception as e:
        logger.error(f"[smc] entry check error: {e}")
        return None


def confirm_on_timeframe(crt_setup: Dict, confirm_tf: str) -> Optional[Dict]:
    """
    CASCADE STEP 2 — drop to the confirmation timeframe and look for a POI
    (order block / breaker / FVG / support-resistance) that price is respecting
    in the direction of the CRT trade.

    Returns the POI dict (and attaches it to crt_setup) or None.
    """
    try:
        from modules.market_data_forex import get_candles

        symbol = crt_setup['symbol']
        direction = crt_setup['direction']

        df = get_candles(symbol, timeframe=confirm_tf, limit=60)
        if df is None or len(df) < 20:
            return None

        price = float(df['close'].iloc[-1])
        atr = calculate_atr(df)

        poi = find_poi(df, direction, price, atr)
        if not poi:
            logger.debug(f"[cascade] {symbol} no POI on {confirm_tf}")
            return None

        logger.info(f"[cascade] {symbol} POI on {confirm_tf}: {poi['kind']} "
                    f"(CRT {crt_setup.get('timeframe')})")
        return poi

    except Exception as e:
        logger.error(f"[cascade] confirm error: {e}")
        return None


def calculate_atr(df: pd.DataFrame, period: int = 14) -> float:
    """Calculate ATR"""
    try:
        high = df['high']
        low = df['low']
        close = df['close']
        
        tr1 = high - low
        tr2 = abs(high - close.shift())
        tr3 = abs(low - close.shift())
        
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        atr = tr.rolling(period).mean().iloc[-1]
        
        return float(atr) if not pd.isna(atr) else 0.0001
        
    except Exception as e:
        logger.error(f"[smc] atr calc error: {e}")
        return 0.0001


# ══════════════════════════════════════════════════════════════════════════════
#  REFINED CRT ENTRY LAYER
#  Priority: Quasimodo > FVG > Order Block
# ══════════════════════════════════════════════════════════════════════════════

# Max ATR distance the QM shoulder may already have been exceeded by
_QM_SHOULDER_TOLERANCE_ATR = 1.0

# FVG must form within this many candles after the sweep candle
_FVG_MAX_AGE_AFTER_SWEEP = 20

# Confidence scoring (Step 4)
_CONF_BASE = 85
_CONF_MIN_TRADE = 88


def _ema_value(series: pd.Series, period: int = 50) -> float:
    """Last EMA value of a series."""
    if series is None or len(series) < period:
        return 0.0
    val = series.ewm(span=period, adjust=False).mean().iloc[-1]
    return float(val) if not pd.isna(val) else 0.0


def _sweep_index_in(df: pd.DataFrame, sweep_candle_low, sweep_candle_high) -> int:
    """
    Find the sweep candle's positional index in `df` by matching its wick.
    Returns -1 when it cannot be located (e.g. it has rolled off the window).
    """
    try:
        if df is None or len(df) == 0:
            return -1
        if sweep_candle_low is not None:
            hits = df.index[df["low"].astype(float) == float(sweep_candle_low)]
            if len(hits):
                return int(hits[-1])
        if sweep_candle_high is not None:
            hits = df.index[df["high"].astype(float) == float(sweep_candle_high)]
            if len(hits):
                return int(hits[-1])
        return -1
    except Exception:
        return -1


def detect_quasimodo(df: pd.DataFrame, direction: str) -> Optional[Dict]:
    """
    Detect a Quasimodo reversal pattern on the entry timeframe (15m/5m).

    BULLISH QM:
      LL1 -> LH (shoulder) -> LL2 below LL1 -> close back above LL1
      entry zone = the LH shoulder

    BEARISH QM:
      HH1 -> HL (shoulder) -> HH2 above HH1 -> close back below HH1
      entry zone = the HL shoulder

    Returns:
      {qm_shoulder, qm_ll1, qm_ll2, entry_zone_high, entry_zone_low}
      or None.
    """
    try:
        if df is None or len(df) < 12:
            return None
        if direction not in ('BUY', 'SELL'):
            return None

        recent = df.tail(20).reset_index(drop=True)
        n = len(recent)
        highs = recent['high'].astype(float).values
        lows = recent['low'].astype(float).values
        closes = recent['close'].astype(float).values

        # ── BULLISH: sweep BELOW an old low, close back above it ─────────────
        if direction == 'BUY':
            for i in range(n - 2, 3, -1):
                ll2 = lows[i]
                # LL2 must undercut a low at least 3 bars back
                for j in range(i - 3, -1, -1):
                    ll1 = lows[j]
                    if ll2 >= ll1:
                        continue
                    # Close back above the old low confirms the sweep
                    confirmed = any(closes[k] > ll1 for k in range(i + 1, n))
                    if not confirmed:
                        continue
                    # Shoulder = highest high between LL1 and LL2
                    shoulder = float(highs[j:i + 1].max()) if i > j else float(highs[i])
                    return {
                        'qm_shoulder': shoulder,
                        'qm_ll1': float(ll1),
                        'qm_ll2': float(ll2),
                        'entry_zone_high': shoulder,
                        'entry_zone_low': float(ll1),
                        'type': 'bullish_qm',
                    }

        # ── BEARISH: sweep ABOVE an old high, close back below it ────────────
        else:
            for i in range(n - 2, 3, -1):
                hh2 = highs[i]
                for j in range(i - 3, -1, -1):
                    hh1 = highs[j]
                    if hh2 <= hh1:
                        continue
                    confirmed = any(closes[k] < hh1 for k in range(i + 1, n))
                    if not confirmed:
                        continue
                    # Shoulder = lowest low between HH1 and HH2
                    shoulder = float(lows[j:i + 1].min()) if i > j else float(lows[i])
                    return {
                        'qm_shoulder': shoulder,
                        'qm_hh1': float(hh1),
                        'qm_hh2': float(hh2),
                        'entry_zone_high': float(hh1),
                        'entry_zone_low': shoulder,
                        'type': 'bearish_qm',
                    }

        return None

    except Exception as e:
        logger.error(f"[smc] quasimodo detection error: {e}")
        return None


def calculate_fib_premium_discount(pullback_high: float, pullback_low: float) -> Dict:
    """
    Fibonacci premium / discount split of the pullback range.

    0%   = pullback high
    100% = pullback low
    Premium  = 0%-50%  (above the midpoint — expensive, sell zone)
    Discount = 50%-100% (below the midpoint — cheap, buy zone)
    """
    try:
        high = float(pullback_high)
        low = float(pullback_low)
        if high < low:
            high, low = low, high

        mid = (high + low) / 2.0
        return {
            'range_high': high,
            'range_low': low,
            'midpoint': mid,
            'premium_zone_high': high,
            'premium_zone_low': mid,
            'discount_zone_high': mid,
            'discount_zone_low': low,
        }
    except Exception as e:
        logger.error(f"[smc] fib premium/discount error: {e}")
        return {
            'range_high': 0.0, 'range_low': 0.0, 'midpoint': 0.0,
            'premium_zone_high': 0.0, 'premium_zone_low': 0.0,
            'discount_zone_high': 0.0, 'discount_zone_low': 0.0,
        }


def detect_fvg_after_sweep(df: pd.DataFrame, direction: str,
                           sweep_index: int, max_age: int = _FVG_MAX_AGE_AFTER_SWEEP) -> Optional[Dict]:
    """
    Detect an FVG that formed AFTER the sweep candle (never before), within
    `max_age` candles of it, and that price has not yet mitigated.
    """
    try:
        if df is None or len(df) < 4:
            return None

        recent = df.tail(40).reset_index(drop=True)
        n = len(recent)

        # Locate the sweep inside this window when the caller's index is stale
        start = 0
        if 0 <= sweep_index < n:
            start = sweep_index + 1

        end = min(n, start + max_age)
        for i in range(start, end - 2):
            c1 = recent.iloc[i]
            c3 = recent.iloc[i + 2]

            if direction == 'BUY':
                if float(c3['low']) > float(c1['high']):
                    gap_low = float(c1['high'])
                    gap_high = float(c3['low'])
                    # Unmitigated: no later candle has traded back into the gap
                    later = recent.iloc[i + 3:]
                    if len(later) and (later['low'].astype(float) <= gap_low).any():
                        continue
                    return {
                        'fvg_high': gap_high,
                        'fvg_low': gap_low,
                        'fvg_index': i,
                        'type': 'bullish_fvg',
                        'unmitigated': True,
                    }
            else:
                if float(c3['high']) < float(c1['low']):
                    gap_high = float(c1['low'])
                    gap_low = float(c3['high'])
                    later = recent.iloc[i + 3:]
                    if len(later) and (later['high'].astype(float) >= gap_high).any():
                        continue
                    return {
                        'fvg_high': gap_high,
                        'fvg_low': gap_low,
                        'fvg_index': i,
                        'type': 'bearish_fvg',
                        'unmitigated': True,
                    }

        return None

    except Exception as e:
        logger.error(f"[smc] fvg-after-sweep error: {e}")
        return None


def _find_significant_target(df_h1: pd.DataFrame, direction: str, entry: float,
                             fallback: float, min_distance: float = 0.0) -> float:
    """
    Nearest significant swing high (BUY) / low (SELL) beyond the entry —
    the liquidity pool where the final TP sits.

    Swing points closer than `min_distance` to the entry are skipped so a
    micro-pivot cannot be used as a target. Falls back when none qualify.
    """
    try:
        if df_h1 is None or len(df_h1) < 20:
            return fallback

        recent = df_h1.tail(60).reset_index(drop=True)
        highs = recent['high'].astype(float).values
        lows = recent['low'].astype(float).values
        n = len(recent)

        swing_highs, swing_lows = [], []
        for i in range(2, n - 2):
            if highs[i] > highs[i - 1] and highs[i] > highs[i - 2] and \
               highs[i] > highs[i + 1] and highs[i] > highs[i + 2]:
                swing_highs.append(float(highs[i]))
            if lows[i] < lows[i - 1] and lows[i] < lows[i - 2] and \
               lows[i] < lows[i + 1] and lows[i] < lows[i + 2]:
                swing_lows.append(float(lows[i]))

        if direction == 'BUY':
            above = [h for h in swing_highs if h - entry > min_distance]
            if above:
                return min(above)
        else:
            below = [l for l in swing_lows if entry - l > min_distance]
            if below:
                return max(below)

        return fallback

    except Exception as e:
        logger.error(f"[smc] target detection error: {e}")
        return fallback


def _build_signal(crt_setup: Dict, trend: str, entry: float, sl: float, tp2: float,
                  entry_type: str, df_entry: pd.DataFrame, df_h1: Optional[pd.DataFrame],
                  fib: Optional[Dict], extra: Optional[Dict] = None) -> Optional[Dict]:
    """
    Assemble the final signal dict, computing TP1 (50% of the move), R:R and
    the Step-4 confidence score. Returns None when R:R is below 1:2.
    """
    try:
        atr = calculate_atr(df_entry)

        risk = abs(entry - sl)
        reward = abs(tp2 - entry)
        if risk <= 0:
            return None

        rr = reward / risk

        tp1 = entry + (tp2 - entry) * 0.5

        # ── Confidence scoring (Step 4) ──────────────────────────────────────
        confidence = _CONF_BASE

        # +5 H4 trend and H1 pullback clearly aligned.
        # This block only runs when the trend is BULLISH or BEARISH (NEUTRAL
        # returns earlier), so awarding +5 unconditionally made the floor
        # unreachable: 85 + 5 = 90 was the minimum possible score, while the
        # floor is 88. The bonus is now tied to the setup actually being
        # well-formed, so weak setups can legitimately score below 88.
        body_pct = float(crt_setup.get('body_pct') or 0)

        # A sweep with a weak body is not a rejection — it is a doji. Score it
        # as such so it cannot clear the floor on session/entry bonuses alone.
        if body_pct >= 0.40:
            confidence += 5
        else:
            confidence -= 5

        # +4 sweep candle closed strongly back inside range (body > 60%)
        if body_pct > 0.60:
            confidence += 4

        # +3 NY session window (12:00-15:00 UTC) — peak volume
        hour = datetime.utcnow().hour
        if 12 <= hour <= 15:
            confidence += 3

        if entry_type == 'QM':
            confidence += 3          # strongest entry signal
        elif entry_type == 'FVG':
            confidence += 2          # clear imbalance

        # +2 OB + FVG overlap at the same price zone
        if extra and extra.get('ob_fvg_overlap'):
            confidence += 2

        # +2 liquidity grab visible before the sweep
        if extra and extra.get('liquidity_grab'):
            confidence += 2

        # +2 premium zone confirmed (bearish setups)
        if fib and trend == 'BEARISH':
            confidence += 2

        # +1 R:R >= 1:3
        if rr >= 3.0:
            confidence += 1

        confidence = min(confidence, 99)

        # Hard floor — never trade below the refined-CRT minimum
        if confidence < _CONF_MIN_TRADE:
            logger.info(f"[smc] {crt_setup.get('symbol')} confidence {confidence}% "
                        f"below minimum {_CONF_MIN_TRADE}%")
            return None

        if rr < 2.0:
            logger.info(f"[smc] {crt_setup.get('symbol')} R:R too low: {rr:.2f}")
            return None

        signal = {
            'symbol': crt_setup['symbol'],
            'signal': 'BUY' if trend == 'BULLISH' else 'SELL',
            'entry_price': round(entry, 5),
            'stop_loss': round(sl, 5),
            'take_profit': round(tp2, 5),
            'tp1': round(tp1, 5),
            'tp2': round(tp2, 5),
            'entry_type': entry_type,
            'trend_direction': trend,
            'confidence': confidence,
            'risk_reward': round(rr, 2),
            'atr': atr,
            'crt_setup': crt_setup.get('sweep_type', 'NONE'),
            'crt_timeframe': crt_setup.get('timeframe', '1h'),
            'confirm_timeframe': crt_setup.get('confirm_timeframe'),
            'entry_timeframe': crt_setup.get('entry_timeframe', '15m'),
            'poi': entry_type,
            'pdh': crt_setup.get('range_high', crt_setup.get('pdh')),
            'pdl': crt_setup.get('range_low', crt_setup.get('pdl')),
            'trend_structure': crt_setup.get('trend_direction', trend),
            'timestamp': datetime.utcnow().isoformat(),
        }
        if fib:
            signal['fib'] = fib
        if extra:
            signal.update({k: v for k, v in extra.items() if k not in signal})

        return signal

    except Exception as e:
        logger.error(f"[smc] signal build error: {e}")
        return None


def check_entry_condition_refined(crt_setup: Dict, current_price: float,
                                  df_15m: pd.DataFrame, df_5m: pd.DataFrame,
                                  trend: str) -> Optional[Dict]:
    """
    Refined CRT entry logic — implements the 3-option trigger set.

    Priority: QM (most precise) > FVG > OB.
    Bullish setups enter on the 15m/5m after the sweep; bearish setups must
    first retrace into the premium zone of the pullback range.

    Returns a signal with entry, sl, tp1, tp2, entry_type, confidence.
    """
    try:
        symbol = crt_setup.get('symbol', '?')
        if trend not in ('BULLISH', 'BEARISH'):
            return None

        direction = 'BUY' if trend == 'BULLISH' else 'SELL'
        df_entry = df_15m if df_15m is not None and len(df_15m) >= 20 else df_5m
        if df_entry is None or len(df_entry) < 20:
            return None

        atr = calculate_atr(df_entry)
        if atr <= 0:
            atr = current_price * 0.001

        sweep_low = crt_setup.get('sweep_candle_low')
        sweep_high = crt_setup.get('sweep_candle_high')

        # ── Bearish: premium-zone gate (Step 3B) ─────────────────────────────
        fib = None
        if trend == 'BEARISH':
            pb_high = crt_setup.get('pullback_high', crt_setup.get('crt_high'))
            pb_low = crt_setup.get('pullback_low', crt_setup.get('crt_low'))
            if pb_high is None or pb_low is None:
                return None
            fib = calculate_fib_premium_discount(pb_high, pb_low)
            if current_price < fib['premium_zone_low']:
                logger.debug(f"[smc] {symbol} price below premium zone "
                             f"({current_price:.5f} < {fib['premium_zone_low']:.5f})")
                return None

        df_h1 = crt_setup.get('_df_h1')

        # ── Option C: Quasimodo (highest priority) ───────────────────────────
        qm = detect_quasimodo(df_entry, direction)
        if qm:
            shoulder = qm['qm_shoulder']
            exceeded = abs(current_price - shoulder)
            if exceeded <= _QM_SHOULDER_TOLERANCE_ATR * atr:
                if trend == 'BULLISH':
                    entry = max(current_price, shoulder)
                    sl = float(qm['qm_ll2']) - (0.5 * atr)
                    fallback = float(crt_setup.get('target') or crt_setup.get('crt_high') or entry)
                    tp2 = _find_significant_target(df_h1, 'BUY', entry, fallback,
                                                   min_distance=abs(entry - sl) * 2)
                else:
                    entry = min(current_price, shoulder)
                    sl = float(qm['qm_hh2']) + (0.5 * atr)
                    fallback = float(crt_setup.get('target') or crt_setup.get('crt_low') or entry)
                    tp2 = _find_significant_target(df_h1, 'SELL', entry, fallback,
                                                   min_distance=abs(entry - sl) * 2)

                logger.info(f"[smc] {symbol} {crt_setup.get('entry_timeframe','15m')} "
                            f"QM detected — shoulder={shoulder:.5f} "
                            f"LL2={float(qm.get('qm_ll2', qm.get('qm_hh2', 0))):.5f} "
                            f"entry zone confirmed")

                sig = _build_signal(crt_setup, trend, entry, sl, tp2, 'QM',
                                    df_entry, df_h1, fib, {'qm': qm})
                if sig:
                    return sig

        # ── Option A: FVG formed after the sweep ─────────────────────────────
        sweep_idx = _sweep_index_in(df_entry.reset_index(drop=True),
                                    sweep_low, sweep_high)
        fvg = detect_fvg_after_sweep(df_entry, direction, sweep_idx)
        if fvg:
            in_zone = fvg['fvg_low'] <= current_price <= fvg['fvg_high']
            near_zone = min(abs(current_price - fvg['fvg_high']),
                            abs(current_price - fvg['fvg_low'])) <= (0.5 * atr)
            if in_zone or near_zone:
                if trend == 'BULLISH':
                    entry = current_price
                    sl = float(sweep_low) - (0.5 * atr) if sweep_low else entry - atr
                    fallback = float(crt_setup.get('target') or fvg['fvg_high'])
                    tp2 = _find_significant_target(df_h1, 'BUY', entry, fallback,
                                                   min_distance=abs(entry - sl) * 2)
                else:
                    entry = current_price
                    sl = float(sweep_high) + (0.5 * atr) if sweep_high else entry + atr
                    fallback = float(crt_setup.get('target') or fvg['fvg_low'])
                    tp2 = _find_significant_target(df_h1, 'SELL', entry, fallback,
                                                   min_distance=abs(entry - sl) * 2)

                sig = _build_signal(crt_setup, trend, entry, sl, tp2, 'FVG',
                                    df_entry, df_h1, fib, {'fvg': fvg})
                if sig:
                    return sig

        # ── Option B: Order Block retest ─────────────────────────────────────
        ob = detect_order_block(df_entry, direction)
        if ob:
            in_ob = ob['ob_low'] <= current_price <= ob['ob_high']
            near_ob = min(abs(current_price - ob['ob_high']),
                          abs(current_price - ob['ob_low'])) <= (0.5 * atr)
            if in_ob or near_ob:
                overlap = bool(fvg and fvg['fvg_low'] <= ob['ob_high']
                               and fvg['fvg_high'] >= ob['ob_low'])
                if trend == 'BULLISH':
                    entry = current_price
                    sl = float(ob['ob_low']) - (0.5 * atr)
                    fallback = float(crt_setup.get('target') or ob['ob_high'])
                    tp2 = _find_significant_target(df_h1, 'BUY', entry, fallback,
                                                   min_distance=abs(entry - sl) * 2)
                else:
                    entry = current_price
                    sl = float(ob['ob_high']) + (0.5 * atr)
                    fallback = float(crt_setup.get('target') or ob['ob_low'])
                    tp2 = _find_significant_target(df_h1, 'SELL', entry, fallback,
                                                   min_distance=abs(entry - sl) * 2)

                sig = _build_signal(crt_setup, trend, entry, sl, tp2, 'OB',
                                    df_entry, df_h1, fib,
                                    {'order_block': ob, 'ob_fvg_overlap': overlap})
                if sig:
                    return sig

        return None

    except Exception as e:
        logger.error(f"[smc] refined entry check error: {e}")
        return None


# ══════════════════════════════════════════════════════════════════════════════
#  SILVER BULLET SIGNAL ENGINE
#
#  Everything below is the forex strategy. It is deliberately free of
#  module-scope imports from `silver_bullet` and `volume_profile` so it can be
#  unit tested without a broker connection, and so the dependency runs one way:
#
#      volume_profile  <-  forex_signal_engine  <-  silver_bullet
# ══════════════════════════════════════════════════════════════════════════════

# ── Session windows (UTC) ─────────────────────────────────────────────────────
# name -> (start_hour, end_hour, confidence_bonus)
#
# These are the widely-repeated ICT Silver Bullet windows. There is no
# documented academic source for them: they are community doctrine, not
# evidence. They are implemented faithfully because they define the strategy,
# not because the times themselves have demonstrated an edge.
#
# 15:00-16:00 UTC (the "NY morning" window) contains the 12:30 and 14:00 UTC US
# data releases, so a material share of its sweeps are news-driven. A liquidity
# sweep caused by a data release is not the setup this strategy describes, so
# NEWS_BLACKOUT_WINDOWS refuses to trade through one.
SESSIONS: Dict[str, Tuple[int, int, int]] = {
    "LONDON":       (8,  9,  3),
    "NY_MORNING":   (15, 16, 4),   # institutional prime time
    "NY_AFTERNOON": (19, 20, 2),
}

# High-impact US data lands at 12:30 and 14:00 UTC in US daylight time, inside
# the NY_MORNING window. Times are (hour, minute) UTC, inclusive of the guard.
NEWS_BLACKOUT_WINDOWS = [
    ((12, 25), (12, 45)),
    ((13, 55), (14, 15)),
]

# ── Setup quality thresholds ──────────────────────────────────────────────────
# The score is a ranking, not a probability. 88 is a hard floor: a setup that
# does not reach it is never executable, however clean its geometry.
CONFIDENCE_BASE    = 85
MIN_CONFIDENCE     = 88
STRONG_CONFIDENCE  = 93
ELITE_CONFIDENCE   = 96

# ── Detection constants ───────────────────────────────────────────────────────
SWING_LOOKBACK     = 5     # candles before the window used to mark liquidity
MIN_SWEEP_BODY_PCT = 0.40  # sweep candle body must exceed this share of its range
MSS_MAX_CANDLES    = 3     # MSS must occur within this many candles of the sweep
FVG_MAX_AGE        = 10    # FVG must form within this many candles of the sweep

# How many of the newest candles are scanned for a sweep.
SWEEP_SCAN_CANDLES = 10

# Stop buffer beyond the sweep wick, and the sanity ceiling on stop width.
# SL_MAX_ATR is NOT the risk control — see `check_entry_retest`.
SL_ATR_BUFFER      = 0.5
SL_MAX_ATR         = 6.0

# ── Setup states ──────────────────────────────────────────────────────────────
# The pipeline is strictly ordered, so a setup's state names the last stage it
# cleared. `advance_setup` never moves a setup backwards.
STATE_WAITING        = "WAITING"
STATE_SWEEP_DETECTED = "SWEEP_DETECTED"
STATE_MSS_CONFIRMED  = "MSS_CONFIRMED"
STATE_FVG_FOUND      = "FVG_FOUND"
STATE_IN_TRADE       = "IN_TRADE"
STATE_EXPIRED        = "EXPIRED"
STATE_INVALID        = "INVALID"

# Terminal states a setup can never leave.
TERMINAL_STATES = (STATE_EXPIRED, STATE_INVALID, STATE_IN_TRADE)

# The forward order of the live states, used to reject backwards transitions.
_STATE_ORDER = [
    STATE_WAITING,
    STATE_SWEEP_DETECTED,
    STATE_MSS_CONFIRMED,
    STATE_FVG_FOUND,
    STATE_IN_TRADE,
]


# ── Session clock ─────────────────────────────────────────────────────────────

def current_session(now: Optional[datetime] = None) -> Optional[str]:
    """Name of the session window currently open, or None."""
    hour = (now or datetime.utcnow()).hour
    for name, (start, end, _) in SESSIONS.items():
        if start <= hour < end:
            return name
    return None


def session_bounds(session_name: str,
                   now: Optional[datetime] = None) -> Tuple[datetime, datetime]:
    """
    Today's UTC (open, close) datetimes for a session.

    Derived from the UTC day of `now` rather than from `utcnow().replace(hour=...)`
    so the window cannot drift by a day when called at 23:5x.
    """
    start_hour, end_hour, _ = SESSIONS[session_name]
    ref = now or datetime.utcnow()
    base = datetime(ref.year, ref.month, ref.day)
    return (base.replace(hour=start_hour),
            base.replace(hour=end_hour))


def session_minutes_until_open(session_name: str,
                               now: Optional[datetime] = None) -> float:
    """Minutes until the named session opens today; negative once it has."""
    ref = now or datetime.utcnow()
    open_dt, _ = session_bounds(session_name, ref)
    return (open_dt - ref).total_seconds() / 60.0


def session_time_remaining(session_name: Optional[str],
                           now: Optional[datetime] = None) -> int:
    """Seconds until the named session closes (0 when it is not open)."""
    if not session_name:
        return 0
    ref = now or datetime.utcnow()
    _, close = session_bounds(session_name, ref)
    return max(0, int((close - ref).total_seconds()))


def sessions_opening_within(minutes: int = 5,
                            now: Optional[datetime] = None) -> List[str]:
    """
    Sessions whose window opens within the next `minutes`.

    Used by the pre-session job so it marks each window once, shortly before it
    opens, instead of continuously from midnight.
    """
    ref = now or datetime.utcnow()
    out = []
    for name in SESSIONS:
        until = session_minutes_until_open(name, ref)
        if 0 < until <= minutes:
            out.append(name)
    return out


def in_news_blackout(now: Optional[datetime] = None) -> Tuple[bool, Optional[str]]:
    """
    True while a scheduled high-impact release window is open.

    A sweep that a data release caused is not the setup this strategy
    describes, and the stop is far wider than the release's spike, so the trade
    is refused rather than sized around it.

    Returns (blocked, label).
    """
    ref = now or datetime.utcnow()
    minutes = ref.hour * 60 + ref.minute
    for (sh, sm), (eh, em) in NEWS_BLACKOUT_WINDOWS:
        if sh * 60 + sm <= minutes <= eh * 60 + em:
            return True, f"{sh:02d}:{sm:02d}-{eh:02d}:{em:02d} UTC"
    return False, None


def session_schedule(now: Optional[datetime] = None) -> List[Dict]:
    """
    Today's session windows for the dashboard.

    Served from here so the frontend stops keeping its own copy of the hours —
    a fourth hardcoded copy of the schedule is how the UI and the engine drift
    apart.
    """
    ref = now or datetime.utcnow()
    active = current_session(ref)
    blocked, label = in_news_blackout(ref)
    out = []
    for name, (start_hour, end_hour, _) in SESSIONS.items():
        open_dt, close_dt = session_bounds(name, ref)
        out.append({
            "session": name,
            "open_utc": open_dt.strftime("%H:%M"),
            "close_utc": close_dt.strftime("%H:%M"),
            "active": active == name,
            "blocked": bool(blocked and active == name),
            "blocked_by": label if active == name else None,
        })
    return out


# ── Candle helpers ────────────────────────────────────────────────────────────

def _frame(df: Optional[pd.DataFrame]) -> Optional[pd.DataFrame]:
    """Positional-indexed copy, so every detector indexes the same way."""
    if df is None or len(df) == 0:
        return None
    return df.reset_index(drop=True)


def closed_candles_only(df: Optional[pd.DataFrame], timeframe: str,
                        now: Optional[datetime] = None) -> Optional[pd.DataFrame]:
    """
    Drop the still-forming candle so no detector can read an incomplete bar.

    Capital.com returns the in-progress candle as the last row. Using it means
    the bar's high/low/close are not final when the setup is evaluated, so the
    same timestamp can produce a different setup depending on the second the
    scan ran. That is look-ahead bias in its most insidious form: invisible in
    both backtest and live, and it makes the setup non-reproducible.

    Bar boundaries are derived from the UTC clock, not from the data, so this
    works even when the feed is missing recent candles. The boundary is floored
    on the UNIX epoch, not on the current hour: at 13:00 UTC the live 4-hour bar
    is the one that opened at 12:00, and flooring to the hour would leave it in
    the frame.
    """
    if df is None or len(df) == 0:
        return df
    if "timestamp" not in df.columns:
        return df

    minutes = {"5m": 5, "15m": 15, "30m": 30, "1h": 60, "4h": 240, "1d": 1440}.get(timeframe)
    if minutes is None:
        return df

    ref = now or datetime.utcnow()
    if ref.tzinfo is not None:
        from datetime import timezone
        ref = ref.astimezone(timezone.utc).replace(tzinfo=None)

    epoch = datetime(1970, 1, 1)
    elapsed = int((ref - epoch).total_seconds() // 60)
    period_start = epoch + timedelta(minutes=(elapsed // minutes) * minutes)

    try:
        ts = pd.to_datetime(df["timestamp"], errors="coerce", utc=True)
        cutoff = pd.Timestamp(period_start, tz="UTC")
        keep = df[ts < cutoff]
        return keep.reset_index(drop=True) if len(keep) else df
    except Exception:
        return df


def calculate_atr(df: pd.DataFrame, period: int = 14) -> float:
    """
    Average true range of the entry timeframe. 0.0 when there is too little
    history, which callers treat as "cannot size a stop" rather than as a zero
    risk.
    """
    try:
        if df is None or len(df) < period + 1:
            return 0.0
        high, low = df["high"].astype(float), df["low"].astype(float)
        close = df["close"].astype(float)
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


# ── Stage 1: liquidity sweep ──────────────────────────────────────────────────

def detect_liquidity_sweep(df_5m: pd.DataFrame, session_levels: Dict,
                           h4_bias: str) -> Optional[Dict]:
    """
    A sweep is a candle that wicks beyond the session swing and closes back
    inside, with a body strong enough to be a rejection rather than a doji.

    BUY  setup: low < swing_low  AND close > swing_low
    SELL setup: high > swing_high AND close < swing_high

    The daily H4 bias is a hard filter: a sweep of the lows is only a setup when
    the higher timeframe is bullish. Sweeping WITH the higher timeframe is a
    breakout, not the reversal this strategy trades.
    """
    try:
        df = _frame(df_5m)
        if df is None or len(df) < 5 or not session_levels:
            return None

        swing_high = session_levels.get("swing_high")
        swing_low = session_levels.get("swing_low")
        if swing_high is None or swing_low is None:
            return None

        # Scan the most recent candles, newest first.
        recent = df.tail(SWEEP_SCAN_CANDLES)
        offset = len(df) - len(recent)      # convert to an absolute index
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


# ── Stage 2: market structure shift ───────────────────────────────────────────

def detect_mss(df_5m: pd.DataFrame, sweep: Dict,
               max_candles: int = MSS_MAX_CANDLES) -> Optional[Dict]:
    """
    Market Structure Shift — after the sweep, price must CLOSE beyond the
    opposing swing within `max_candles`.

    BUY:  close above the most recent 5m swing high before the sweep
    SELL: close below the most recent 5m swing low before the sweep

    A close is required, not a wick: a wick through the level that closes back
    inside is the same failed move the sweep was, not a shift in structure.
    """
    try:
        df = _frame(df_5m)
        if df is None or not sweep:
            return None

        sweep_idx = sweep.get("sweep_index")
        if sweep_idx is None or sweep_idx < 3:
            return None

        before = df.iloc[:sweep_idx]
        if len(before) < 3:
            return None

        direction = sweep["direction"]
        after = df.iloc[sweep_idx + 1: sweep_idx + 1 + max_candles]

        if direction == "BUY":
            level = float(before["high"].tail(SWING_LOOKBACK).max())
            for offset, (_, c) in enumerate(after.iterrows(), start=1):
                if float(c["close"]) > level:
                    return {
                        "direction": "BUY",
                        "mss_level": level,
                        "mss_index": sweep_idx + offset,
                        "candles_to_mss": offset,
                    }
        else:
            level = float(before["low"].tail(SWING_LOOKBACK).min())
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


# The master specification spells this `detect_msss`. Both names resolve to the
# same function so a caller using either spelling cannot silently get a
# different (or missing) implementation.
detect_msss = detect_mss


# ── Stage 3: fair value gap ───────────────────────────────────────────────────

def find_fvg_after_sweep(df_5m: pd.DataFrame, sweep: Dict,
                         max_age: int = FVG_MAX_AGE) -> Optional[Dict]:
    """
    Fair value gap formed AFTER the sweep, within `max_age` candles.

    A three-candle imbalance: with candles i, i+1, i+2,

        bullish  candles[i+2].low  > candles[i].high   -> gap [i.high, i+2.low]
        bearish  candles[i+2].high < candles[i].low    -> gap [i+2.high, i.low]

    `single_candle` reports whether the gap was left by ONE displacement candle
    (candle i+1 alone spanning the gap), which is the stronger imbalance. The
    gap is a three-candle structure either way, so this is a quality flag, not a
    claim that the gap is one candle wide.
    """
    try:
        df = _frame(df_5m)
        if df is None or len(df) < 5 or not sweep:
            return None

        sweep_idx = sweep.get("sweep_index")
        if sweep_idx is None:
            return None

        start = sweep_idx + 1
        end = min(len(df) - 2, start + max_age)

        for i in range(start, end):
            c1 = df.iloc[i]
            c3 = df.iloc[i + 2]
            c2 = df.iloc[i + 1]

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
                        "direction": "BUY",
                        "single_candle": bool(float(c1["high"]) >= float(c2["low"])),
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
                        "direction": "SELL",
                        "single_candle": bool(float(c1["low"]) <= float(c2["high"])),
                    }

        return None

    except Exception as e:
        logger.error(f"[silver] FVG detection error: {e}")
        return None


# ── Stage 4: volume profile confluence ────────────────────────────────────────

def volume_profile_confluence(fvg: Optional[Dict], vp: Optional[Dict]) -> Dict:
    """
    Grade the FVG against the previous-day POC / VAH / VAL.

    Thin wrapper over `volume_profile.check_fvg_confluence`, imported lazily so
    this module keeps a single direction of dependency. The profile itself is
    the one Phase 2 built: it is never rebuilt here, so the levels a setup is
    graded against are exactly the levels the bias record reports.
    """
    from modules.volume_profile import check_fvg_confluence
    return check_fvg_confluence(fvg, vp)


def volume_profile_gateable(vp: Optional[Dict],
                            require_trusted_volume: bool = True) -> Tuple[bool, str]:
    """Whether the profile is fit to gate an entry on (see volume_profile)."""
    from modules.volume_profile import gateable
    return gateable(vp, require_trusted_volume=require_trusted_volume)


# ── Stage 5: heuristic confidence ─────────────────────────────────────────────

def calculate_confidence(bias_data: Dict, sweep: Dict, mss: Dict,
                         fvg: Dict, vp_confluence: Dict,
                         session_name: str) -> int:
    """
    Rank a setup's quality from `CONFIDENCE_BASE` (85) upwards, capped at 99.

    This is a rule-based RANKING of how many of the strategy's own conditions
    lined up. It is NOT a probability: a 94 is a well-formed setup by these
    rules, not a 94% chance of winning. Nothing downstream may present it as
    one.

    The score can legitimately land below the 88 floor — the volume-profile term
    is negative without confluence — which is how a structurally valid but badly
    located setup gets rejected.
    """
    try:
        confidence = CONFIDENCE_BASE
        bias_data = bias_data or {}
        vp_confluence = vp_confluence or {}
        sweep = sweep or {}
        mss = mss or {}
        fvg = fvg or {}

        # ── Volume profile ───────────────────────────────────────────────────
        grade = vp_confluence.get("grade", "NO_CONFLUENCE")
        if grade == "POC_OVERLAP":
            confidence += 8
        elif grade in ("VAH_CONFLUENCE", "VAL_CONFLUENCE"):
            confidence += 5
        elif grade == "INSIDE_VALUE":
            confidence += 1
        else:
            confidence -= 3

        # Price trading outside the value area in the bias direction is the
        # location the strategy wants; at the POC it is a chop zone.
        if bias_data.get("price_position") in ("ABOVE_VALUE", "BELOW_VALUE"):
            confidence += 3
        elif bias_data.get("price_position") == "AT_POC":
            confidence -= 2

        # ── Market structure ─────────────────────────────────────────────────
        strength = bias_data.get("strength", 0)
        if strength >= 3:
            confidence += 5
        elif strength == 2:
            confidence += 3
        elif bias_data.get("h4_bias") == "NEUTRAL":
            confidence -= 5

        # ── Session ──────────────────────────────────────────────────────────
        confidence += SESSIONS.get(session_name, (0, 0, 0))[2]

        # ── Setup quality ────────────────────────────────────────────────────
        body_pct = sweep.get("body_pct", 0.0)
        if body_pct > 0.70:
            confidence += 3
        elif body_pct >= 0.50:
            confidence += 2

        if mss.get("candles_to_mss", 99) == 1:
            confidence += 2

        if fvg.get("single_candle"):
            confidence += 2

        return int(min(confidence, 99))

    except Exception as e:
        logger.error(f"[silver] confidence error: {e}")
        return 0


def is_executable(confidence: Optional[float],
                  minimum: int = MIN_CONFIDENCE) -> bool:
    """
    The hard gate. A score below the floor is never executable.

    Guarded against a missing or unparseable score: an unknown score fails
    closed, because treating it as passing would let a broken scoring path
    authorise a trade.
    """
    try:
        if confidence is None:
            return False
        return float(confidence) >= float(minimum)
    except (TypeError, ValueError):
        return False


# ── Setup record and state machine ────────────────────────────────────────────

def new_setup(symbol: str, session_name: str, direction: str,
              now: Optional[datetime] = None) -> Dict:
    """A fresh setup record in the WAITING state."""
    ref = now or datetime.utcnow()
    return {
        "symbol": symbol,
        "session": session_name,
        "direction": direction,
        "state": STATE_WAITING,
        "history": [STATE_WAITING],
        "sweep": None,
        "mss": None,
        "fvg": None,
        "vp_levels": None,
        "vp_confluence": None,
        "confidence": 0,
        "executable": False,
        "reject_reason": None,
        "entry_taken": False,
        "entry": None,
        "date": ref.strftime("%Y-%m-%d"),
        "created_at": ref.isoformat(),
        "updated_at": ref.isoformat(),
    }


def advance_setup(setup: Dict, state: str,
                  now: Optional[datetime] = None) -> Dict:
    """
    Move a setup forward in the pipeline.

    Transitions are checked, not trusted:

      * a terminal setup (EXPIRED / INVALID / IN_TRADE) never moves again, so an
        expired setup cannot be revived by a later scan;
      * a live setup never moves backwards, so a stale FVG cannot be re-labelled
        as merely MSS_CONFIRMED and re-entered later.

    Returns the setup, unchanged when the transition is refused.
    """
    if not setup:
        return setup

    current = setup.get("state")
    if current in TERMINAL_STATES:
        return setup

    if state in TERMINAL_STATES:
        setup["state"] = state
    elif state in _STATE_ORDER and current in _STATE_ORDER:
        if _STATE_ORDER.index(state) <= _STATE_ORDER.index(current):
            return setup
        setup["state"] = state
    else:
        logger.warning(f"[silver] unknown setup state {state!r} — ignored")
        return setup

    setup["updated_at"] = (now or datetime.utcnow()).isoformat()
    setup.setdefault("history", []).append(setup["state"])
    return setup


def invalidate_setup(setup: Dict, reason: str,
                     now: Optional[datetime] = None) -> Dict:
    """Mark a setup INVALID with the reason it was rejected."""
    if not setup:
        return setup
    setup["reject_reason"] = reason
    return advance_setup(setup, STATE_INVALID, now)


def expire_setup(setup: Dict, now: Optional[datetime] = None) -> Dict:
    """Mark a setup EXPIRED — its session window closed, or its day rolled."""
    if not setup:
        return setup
    setup["reject_reason"] = setup.get("reject_reason") or "session window closed"
    return advance_setup(setup, STATE_EXPIRED, now)


def setup_is_expired(setup: Dict, now: Optional[datetime] = None) -> bool:
    """
    Whether a setup is past its session expiry or its UTC day.

    The expiry is the session CLOSE, not a fixed number of minutes: the setup
    only exists because the session is open, so it dies with the session. A
    setup that somehow survives midnight in memory is dropped here rather than
    becoming sweepable against another day's liquidity.
    """
    if not setup:
        return True
    if setup.get("state") in TERMINAL_STATES:
        return True

    ref = now or datetime.utcnow()
    if setup.get("date") and setup["date"] != ref.strftime("%Y-%m-%d"):
        return True

    sess = setup.get("session")
    if not sess or sess not in SESSIONS:
        return False
    _, close = session_bounds(sess, ref)
    return ref >= close


def build_setup(symbol: str, df_5m: pd.DataFrame, session_levels: Dict,
                bias_data: Dict, session_name: str,
                now: Optional[datetime] = None) -> Dict:
    """
    Run the whole detection pipeline for one symbol and return the setup record.

    The record ALWAYS comes back, whatever happened: its `state` says how far the
    pipeline got and `reject_reason` says why it stopped. Returning None for a
    rejection would throw away the reason, and a strategy that cannot explain
    why it declined a trade cannot be debugged.

    `bias_data` is the Phase 2 daily-bias record. Its `vp_levels` are reused
    as-is; the profile is never recomputed here.
    """
    ref = now or datetime.utcnow()
    bias_data = bias_data or {}

    h4_bias = bias_data.get("h4_bias")
    setup = new_setup(symbol, session_name, "NONE", ref)

    if h4_bias not in ("BULLISH", "BEARISH"):
        return invalidate_setup(
            setup, f"no directional daily bias ({h4_bias})", ref)

    sweep = detect_liquidity_sweep(df_5m, session_levels, h4_bias)
    if not sweep:
        return invalidate_setup(
            setup,
            f"no {h4_bias.lower()} liquidity sweep of the pre-session swing", ref)

    setup["direction"] = sweep["direction"]
    setup["sweep"] = sweep
    advance_setup(setup, STATE_SWEEP_DETECTED, ref)

    mss = detect_mss(df_5m, sweep)
    if not mss:
        return invalidate_setup(
            setup, f"no MSS within {MSS_MAX_CANDLES} candles of the sweep", ref)

    setup["mss"] = mss
    advance_setup(setup, STATE_MSS_CONFIRMED, ref)

    fvg = find_fvg_after_sweep(df_5m, sweep)
    if not fvg:
        return invalidate_setup(
            setup, f"no FVG within {FVG_MAX_AGE} candles of the sweep", ref)

    setup["fvg"] = fvg
    advance_setup(setup, STATE_FVG_FOUND, ref)

    # ── Volume profile confluence, from the Phase 2 profile ──────────────────
    vp = bias_data.get("vp_levels")
    setup["vp_levels"] = vp
    vp_confluence = volume_profile_confluence(fvg, vp)
    setup["vp_confluence"] = vp_confluence.get("grade")
    setup["vp_source"] = vp_confluence.get("volume_source")
    setup["vp_trusted"] = bool(vp_confluence.get("source_trusted"))
    setup["vp_profile_valid"] = bool(vp_confluence.get("profile_valid"))
    setup["vp_confluence_detail"] = vp_confluence

    # A profile that cannot be gated on does not authorise an entry. Whether a
    # range proxy is acceptable is a config decision made once, in Phase 2's
    # `gateable`, not a second opinion invented here.
    gate_ok, gate_reason = volume_profile_gateable(vp)
    setup["vp_gateable"] = gate_ok
    setup["vp_gate_reason"] = gate_reason
    if not gate_ok:
        return invalidate_setup(
            setup, f"volume profile not gateable: {gate_reason}", ref)

    # ── Confidence and the hard floor ────────────────────────────────────────
    confidence = calculate_confidence(bias_data, sweep, mss, fvg,
                                      vp_confluence, session_name)
    setup["confidence"] = confidence
    setup["executable"] = is_executable(confidence)
    setup["expires_at"] = session_bounds(session_name, ref)[1].isoformat()

    if not setup["executable"]:
        return invalidate_setup(
            setup, f"confidence {confidence} below the {MIN_CONFIDENCE} floor", ref)

    return setup


# ── Stage 6: FVG-retest entry ─────────────────────────────────────────────────

def check_entry_retest(setup: Dict, current_price: float,
                       df_5m: pd.DataFrame,
                       now: Optional[datetime] = None) -> Optional[Dict]:
    """
    Fire when price returns into the stored FVG.

    This is the strategy's entry condition: the setup arms on the
    sweep/MSS/FVG sequence and only fills when price trades back into the gap.
    Returns the signal dict, or None when the entry condition is not met.

    Three refusals guard the trade:

      * a setup that is not executable is refused outright, so a sub-88 score
        can never produce an order even if it reached the store;
      * an expired setup is refused;
      * `entry_taken` makes the entry idempotent — the entry job runs every 30
        seconds and price sits inside the gap for several of those runs, so
        without the flag the same setup would open a position on every tick.
        The flag is set the moment the condition is met, not after the order
        succeeds, because the caller may be retrying a placement that already
        partially filled.

    The stop sits beyond the sweep wick, because that wick is the level the
    setup says was defended.
    """
    try:
        from modules.forex_executor import calculate_stops_and_targets
        if not setup or current_price is None:
            return None

        ref = now or datetime.utcnow()

        if not setup.get("executable"):
            logger.debug(f"[silver] {setup.get('symbol')} entry refused — not executable")
            return None

        if setup.get("entry_taken"):
            return None

        if setup_is_expired(setup, ref):
            expire_setup(setup, ref)
            return None

        fvg = setup.get("fvg") or {}
        direction = setup.get("direction")
        fvg_low = float(fvg.get("fvg_low") or 0.0)
        fvg_high = float(fvg.get("fvg_high") or 0.0)
        if fvg_low <= 0 or fvg_high <= 0 or fvg_high < fvg_low:
            return None

        # The retest: price must be inside the gap.
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
            logger.info(f"[silver] {symbol} structural stop "
                        f"{structural_risk / atr:.2f} ATR > {SL_MAX_ATR} ATR — "
                        f"wick too far from price, skip")
            return None

        if direction == "BUY":
            sl = sweep_wick - (SL_ATR_BUFFER * atr)
        else:
            sl = sweep_wick + (SL_ATR_BUFFER * atr)

        # ── Targets ──────────────────────────────────────────────────────────
        # The stop and TP1/TP2 are decided HERE, from the geometry of the setup.
        # TP3 is the one target the specification derives from the market rather
        # than from R, so it is delegated to the executor's calculation, which
        # applies the liquidity-target rules and the high-confidence extension
        # in one place. Duplicating that rule here would let the level the trade
        # is recorded with differ from the level it is managed against.
        targets = calculate_stops_and_targets(
            symbol, direction, entry, sweep_wick, atr,
            setup.get("confidence", 0),
            liquidity_target=setup.get("liquidity_target"),
        )
        if not targets:
            logger.info(f"[silver] {symbol} stop/target calculation refused "
                        f"the setup")
            return None

        sl = targets["stop_loss"]
        risk = targets["risk"]
        tp1 = targets["tp1"]
        tp2 = targets["tp2"]
        tp3 = targets["tp3"]

        signal = {
            "symbol": symbol,
            "signal": direction,
            "entry_price": round(entry, 5),
            "stop_loss": round(sl, 5),
            "take_profit": round(tp3, 5),      # broker-level TP = final target
            "tp1": round(tp1, 5),
            "tp2": round(tp2, 5),
            "tp3": round(tp3, 5),
            "tp3_extended": targets["tp3_extended"],
            "risk_distance": round(risk, 5),
            "atr": round(atr, 5),
            "confidence": setup.get("confidence", 0),
            "entry_type": "SILVER_BULLET_FVG",
            "session": setup.get("session"),
            "expires_at": setup.get("expires_at"),
            "vp_confluence": setup.get("vp_confluence"),
            "trend_direction": setup.get("bias"),
            "crt_setup": "SILVER_BULLET",
            "crt_timeframe": "5m",
            "confirm_timeframe": "5m",
            "entry_timeframe": "5m",
            "poi": "fvg",
            "state": STATE_IN_TRADE,
            "timestamp": ref.isoformat(),
        }

        # Consume the setup: one entry per setup, however many times the job runs.
        setup["entry_taken"] = True
        setup["entry"] = signal
        advance_setup(setup, STATE_IN_TRADE, ref)
        return signal

    except Exception as e:
        logger.error(f"[silver] entry check error: {e}")
        return None
