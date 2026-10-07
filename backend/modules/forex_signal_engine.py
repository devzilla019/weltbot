"""
backend/modules/forex_signal_engine.py
Layer 3: SMC entry logic for Forex CRT setups
"""
import pandas as pd
import numpy as np
from typing import Optional, Dict
import logging
from datetime import datetime

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

        # +5 H4 trend and H1 pullback clearly aligned
        confidence += 5

        # +4 sweep candle closed strongly back inside range (body > 60%)
        if float(crt_setup.get('body_pct') or 0) > 0.60:
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
