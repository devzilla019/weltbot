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
            'pdh': crt_setup.get('range_high', crt_setup.get('pdh')),
            'pdl': crt_setup.get('range_low', crt_setup.get('pdl')),
            'timestamp': datetime.utcnow().isoformat()
        }
        
        logger.info(f"[smc] {symbol} ENTRY CONFIRMED — {direction} @ {entry:.5f} conf={confidence}% R:R={rr:.2f}")
        return signal
        
    except Exception as e:
        logger.error(f"[smc] entry check error: {e}")
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
