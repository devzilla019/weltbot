"""
backend/routers/forex.py
Forex/Metals API endpoints
"""
from fastapi import APIRouter, HTTPException
from typing import Dict, List
import logging

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/forex", tags=["forex"])


@router.get("/status")
def forex_status() -> Dict:
    """
    Get forex bot status and overview
    """
    try:
        from config import FOREX_ENABLED, FOREX_PAIRS
        from modules.kronos_engine import get_all_biases, is_kronos_available
        from modules.crt_detector import get_cached_levels
        from modules.forex_position_manager import get_forex_position_summary
        
        if not FOREX_ENABLED:
            return {
                'enabled': False,
                'message': 'Forex trading disabled'
            }
        
        biases = get_all_biases()
        levels = get_cached_levels()
        position_summary = get_forex_position_summary()
        
        # MT5 account balance (separate from crypto)
        account = None
        try:
            from modules.market_data_forex import get_account_info
            account = get_account_info()
        except Exception as e:
            logger.warning(f"[forex-api] account info unavailable: {e}")
        
        return {
            'enabled': True,
            'kronos_available': is_kronos_available(),
            'pairs': FOREX_PAIRS,
            'biases': biases,
            'crt_levels': levels,
            'positions': position_summary,
            'account': account
        }
        
    except Exception as e:
        logger.error(f"[forex-api] status error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/balance")
def forex_balance() -> Dict:
    """Get MT5 account balance/equity (separate from crypto balance)."""
    try:
        from config import FOREX_ENABLED
        if not FOREX_ENABLED:
            return {'enabled': False, 'balance': 0.0, 'equity': 0.0}
        from modules.market_data_forex import get_account_info
        info = get_account_info()
        if not info:
            return {'enabled': True, 'balance': 0.0, 'equity': 0.0, 'connected': False}
        return {'enabled': True, 'connected': True, **info}
    except Exception as e:
        logger.error(f"[forex-api] balance error: {e}")
        return {'enabled': True, 'connected': False, 'balance': 0.0, 'equity': 0.0}


@router.get("/signals")
def forex_signals() -> List[Dict]:
    """
    Get active forex signals and setups
    """
    try:
        from config import FOREX_PAIRS
        from modules.kronos_engine import get_cached_bias
        from modules.crt_detector import get_cached_levels
        from modules.market_data_forex import get_current_price
        
        signals = []
        
        for symbol in FOREX_PAIRS:
            try:
                bias = get_cached_bias(symbol)
                levels = get_cached_levels(symbol)
                price = get_current_price(symbol)
                
                if not levels:
                    continue
                
                signal = {
                    'symbol': symbol,
                    'current_price': price,
                    'pdh': levels.get('pdh'),
                    'pdl': levels.get('pdl'),
                    'kronos_bias': bias.get('bias', 'NEUTRAL') if bias else 'NEUTRAL',
                    'kronos_confidence_boost': bias.get('confidence_boost', 0) if bias else 0,
                    'crt_status': 'WAITING',
                    'predicted_change': bias.get('predicted_change_pct', 0) if bias else 0
                }
                
                signals.append(signal)
                
            except Exception as e:
                logger.error(f"[forex-api] signal error {symbol}: {e}")
                continue
        
        return signals
        
    except Exception as e:
        logger.error(f"[forex-api] signals error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/positions")
def forex_positions() -> Dict:
    """
    Get open forex positions with live P&L
    """
    try:
        from modules.forex_position_manager import get_forex_position_summary
        
        return get_forex_position_summary()
        
    except Exception as e:
        logger.error(f"[forex-api] positions error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/trades")
def forex_trades(limit: int = 50) -> List[Dict]:
    """
    Get forex trade history
    """
    try:
        from modules.forex_position_manager import get_forex_trade_history
        
        return get_forex_trade_history(limit)
        
    except Exception as e:
        logger.error(f"[forex-api] trades error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/update-bias/{symbol}")
def update_kronos_bias(symbol: str) -> Dict:
    """
    Manually trigger Kronos bias update for a symbol
    """
    try:
        from modules.market_data_forex import get_candles
        from modules.kronos_engine import predict_bias
        
        df = get_candles(symbol, timeframe='1h', limit=400)
        if df is None:
            raise HTTPException(status_code=400, detail="Failed to fetch candles")
        
        bias = predict_bias(symbol, df)
        if bias is None:
            raise HTTPException(status_code=500, detail="Kronos prediction failed")
        
        return bias
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[forex-api] bias update error {symbol}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/update-crt/{symbol}")
def update_crt_levels(symbol: str) -> Dict:
    """
    Manually trigger CRT level update for a symbol
    """
    try:
        from modules.market_data_forex import get_candles
        from modules.crt_detector import calculate_pdh_pdl
        
        daily = get_candles(symbol, timeframe='1d', limit=5)
        if daily is None:
            raise HTTPException(status_code=400, detail="Failed to fetch daily candles")
        
        levels = calculate_pdh_pdl(symbol, daily)
        if levels is None:
            raise HTTPException(status_code=500, detail="PDH/PDL calculation failed")
        
        return levels
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[forex-api] crt update error {symbol}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/pair/{symbol}")
def forex_pair_detail(symbol: str) -> Dict:
    """
    Get detailed info for a specific forex pair
    """
    try:
        from modules.kronos_engine import get_cached_bias
        from modules.crt_detector import get_cached_levels
        from modules.market_data_forex import get_current_price
        from database import SessionLocal
        from models import ForexTrade
        
        bias = get_cached_bias(symbol)
        levels = get_cached_levels(symbol)
        price = get_current_price(symbol)
        
        db = SessionLocal()
        try:
            open_trade = db.query(ForexTrade).filter(
                ForexTrade.symbol == symbol,
                ForexTrade.outcome == 'OPEN'
            ).first()
            
            recent_trades = db.query(ForexTrade).filter(
                ForexTrade.symbol == symbol
            ).order_by(ForexTrade.created_at.desc()).limit(10).all()
            
        finally:
            db.close()
        
        return {
            'symbol': symbol,
            'current_price': price,
            'kronos_bias': bias,
            'crt_levels': levels,
            'open_trade': {
                'id': open_trade.id,
                'signal': open_trade.signal,
                'entry': open_trade.entry_price,
                'sl': open_trade.stop_loss,
                'tp': open_trade.take_profit,
                'lots': open_trade.lots,
                'confidence': open_trade.confidence
            } if open_trade else None,
            'recent_trades_count': len(recent_trades),
            'recent_wins': len([t for t in recent_trades if t.outcome == 'WIN']),
            'recent_losses': len([t for t in recent_trades if t.outcome == 'LOSS'])
        }
        
    except Exception as e:
        logger.error(f"[forex-api] pair detail error {symbol}: {e}")
        raise HTTPException(status_code=500, detail=str(e))
