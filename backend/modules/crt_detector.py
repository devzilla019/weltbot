"""
backend/modules/crt_detector.py
Candle Range Theory - PDH/PDL detection and sweep confirmation
"""
import pandas as pd
from datetime import datetime, timedelta
from typing import Optional, Dict
import logging
from database import SessionLocal
from models import CRTLevel

logger = logging.getLogger(__name__)

_crt_levels_cache: Dict[str, dict] = {}


def calculate_pdh_pdl(symbol: str, daily_candles: pd.DataFrame) -> Optional[Dict]:
    """
    Calculate Previous Day High and Previous Day Low
    
    Args:
        symbol: Trading pair
        daily_candles: DataFrame with daily OHLCV data
    
    Returns:
        dict with pdh, pdl, date
    """
    try:
        if len(daily_candles) < 2:
            return None
        
        prev_day = daily_candles.iloc[-2]
        
        pdh = float(prev_day['high'])
        pdl = float(prev_day['low'])
        prev_date = prev_day['timestamp'].strftime('%Y-%m-%d') if 'timestamp' in prev_day else datetime.utcnow().date().isoformat()
        
        result = {
            'symbol': symbol,
            'pdh': pdh,
            'pdl': pdl,
            'date': prev_date,
            'range': pdh - pdl
        }
        
        _crt_levels_cache[symbol] = result
        logger.info(f"[crt] {symbol} PDH={pdh:.5f} PDL={pdl:.5f} range={result['range']:.5f}")
        
        return result
        
    except Exception as e:
        logger.error(f"[crt] pdh/pdl calc error {symbol}: {e}")
        return None


def detect_sweep(symbol: str, h1_candles: pd.DataFrame, pdh: float, pdl: float) -> Optional[Dict]:
    """
    Detect if price swept PDH or PDL and closed back inside
    
    Args:
        symbol: Trading pair
        h1_candles: Recent H1 candles
        pdh: Previous Day High
        pdl: Previous Day Low
    
    Returns:
        dict with setup info if sweep confirmed, None otherwise
    """
    try:
        if len(h1_candles) < 3:
            return None
        
        recent = h1_candles.tail(5)
        
        for idx in range(len(recent) - 1, -1, -1):
            candle = recent.iloc[idx]
            high = float(candle['high'])
            low = float(candle['low'])
            close = float(candle['close'])
            
            swept_high = high > pdh and close < pdh
            swept_low = low < pdl and close > pdl
            
            if swept_high:
                logger.info(f"[crt] {symbol} SWEPT HIGH — PDH={pdh:.5f} high={high:.5f} close={close:.5f}")
                return {
                    'symbol': symbol,
                    'sweep_type': 'HIGH',
                    'direction': 'SELL',
                    'pdh': pdh,
                    'pdl': pdl,
                    'sweep_candle_high': high,
                    'sweep_candle_close': close,
                    'confirmed': True,
                    'target': pdl,
                    'timestamp': datetime.utcnow().isoformat()
                }
            
            if swept_low:
                logger.info(f"[crt] {symbol} SWEPT LOW — PDL={pdl:.5f} low={low:.5f} close={close:.5f}")
                return {
                    'symbol': symbol,
                    'sweep_type': 'LOW',
                    'direction': 'BUY',
                    'pdh': pdh,
                    'pdl': pdl,
                    'sweep_candle_low': low,
                    'sweep_candle_close': close,
                    'confirmed': True,
                    'target': pdh,
                    'timestamp': datetime.utcnow().isoformat()
                }
        
        return None
        
    except Exception as e:
        logger.error(f"[crt] sweep detection error {symbol}: {e}")
        return None


def validate_with_kronos(crt_setup: Dict, kronos_bias: Optional[Dict]) -> bool:
    """
    Validate CRT setup against Kronos bias
    
    Args:
        crt_setup: CRT setup dict
        kronos_bias: Kronos bias dict
    
    Returns:
        True if setup aligns with Kronos bias
    """
    if not kronos_bias:
        logger.warning(f"[crt] {crt_setup['symbol']} no Kronos bias — rejecting setup")
        return False
    
    bias = kronos_bias.get('bias', 'NEUTRAL')
    direction = crt_setup['direction']
    
    if direction == 'BUY' and bias == 'BULLISH':
        logger.info(f"[crt] {crt_setup['symbol']} BUY setup confirmed by BULLISH Kronos")
        return True
    
    if direction == 'SELL' and bias == 'BEARISH':
        logger.info(f"[crt] {crt_setup['symbol']} SELL setup confirmed by BEARISH Kronos")
        return True
    
    logger.info(f"[crt] {crt_setup['symbol']} {direction} rejected — Kronos bias={bias}")
    return False


def store_crt_level(crt_setup: Dict):
    """Store CRT level in database"""
    db = SessionLocal()
    try:
        existing = db.query(CRTLevel).filter(
            CRTLevel.symbol == crt_setup['symbol'],
            CRTLevel.date == datetime.utcnow().date().isoformat()
        ).first()
        
        if existing:
            existing.sweep_type = crt_setup['sweep_type']
            existing.sweep_confirmed = 1
        else:
            level = CRTLevel(
                symbol=crt_setup['symbol'],
                date=datetime.utcnow().date().isoformat(),
                pdh=crt_setup['pdh'],
                pdl=crt_setup['pdl'],
                sweep_type=crt_setup['sweep_type'],
                sweep_confirmed=1
            )
            db.add(level)
        
        db.commit()
        logger.info(f"[crt] stored level for {crt_setup['symbol']}")
        
    except Exception as e:
        logger.error(f"[crt] db store error: {e}")
        db.rollback()
    finally:
        db.close()


def get_cached_levels(symbol: Optional[str] = None) -> Dict:
    """Get cached CRT levels"""
    if symbol:
        return _crt_levels_cache.get(symbol, {})
    return _crt_levels_cache.copy()


def update_pdh_pdl_all_pairs():
    """Update PDH/PDL for all forex pairs (run daily at 00:01 UTC)"""
    from config import FOREX_PAIRS
    from modules.market_data_forex import get_candles
    
    logger.info("[crt] updating PDH/PDL for all pairs")
    
    for symbol in FOREX_PAIRS:
        try:
            daily = get_candles(symbol, timeframe='1d', limit=5)
            if daily is not None and len(daily) >= 2:
                calculate_pdh_pdl(symbol, daily)
        except Exception as e:
            logger.error(f"[crt] update error {symbol}: {e}")
    
    logger.info(f"[crt] updated {len(_crt_levels_cache)} pairs")
