"""
backend/modules/forex_executor.py
MetaApi order execution for Forex/Metals
"""
import asyncio
import logging
from typing import Dict, Optional
from datetime import datetime
from database import SessionLocal
from models import ForexTrade

logger = logging.getLogger(__name__)


async def _place_order_async(symbol: str, signal: str, lots: float, sl: float, tp: float) -> Dict:
    """
    Place market order via MetaApi
    
    Args:
        symbol: Trading pair
        signal: BUY or SELL
        lots: Position size in lots
        sl: Stop loss price
        tp: Take profit price
    
    Returns:
        dict with success, position_id, fill_price
    """
    try:
        from modules.market_data_forex import _get_metaapi_connection
        
        conn, _ = await _get_metaapi_connection()
        if conn is None:
            return {'success': False, 'error': 'MetaApi connection failed'}
        
        if signal == 'BUY':
            result = await conn.create_market_buy_order(
                symbol=symbol,
                volume=lots,
                stop_loss=sl,
                take_profit=tp
            )
        else:
            result = await conn.create_market_sell_order(
                symbol=symbol,
                volume=lots,
                stop_loss=sl,
                take_profit=tp
            )
        
        if result.get('orderId'):
            logger.info(f"[forex] order placed — {signal} {symbol} {lots} lots @ {result.get('price', 0):.5f}")
            return {
                'success': True,
                'position_id': result['positionId'] if 'positionId' in result else result['orderId'],
                'fill_price': result.get('price', 0),
                'order_id': result['orderId']
            }
        else:
            error_msg = result.get('message', 'Unknown error')
            logger.error(f"[forex] order failed — {symbol}: {error_msg}")
            return {'success': False, 'error': error_msg}
        
    except Exception as e:
        logger.error(f"[forex] execution error {symbol}: {e}")
        return {'success': False, 'error': str(e)}


def place_forex_order(signal_data: Dict, kronos_bias: Dict) -> Dict:
    """
    Place forex order and record in database
    
    Args:
        signal_data: Signal from forex_signal_engine
        kronos_bias: Kronos bias data
    
    Returns:
        dict with success status and details
    """
    try:
        symbol = signal_data['symbol']
        signal = signal_data['signal']
        entry = signal_data['entry_price']
        sl = signal_data['stop_loss']
        tp = signal_data['take_profit']
        confidence = signal_data['confidence']
        
        lots = calculate_position_size(symbol, entry, sl, confidence)
        
        if lots <= 0:
            return {'success': False, 'error': 'Invalid position size'}
        
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
        
        result = loop.run_until_complete(
            _place_order_async(symbol, signal, lots, sl, tp)
        )
        
        if result['success']:
            db = SessionLocal()
            try:
                trade = ForexTrade(
                    symbol=symbol,
                    signal=signal,
                    confidence=confidence,
                    entry_price=entry,
                    stop_loss=sl,
                    take_profit=tp,
                    lots=lots,
                    kronos_bias=kronos_bias.get('bias', 'NEUTRAL'),
                    crt_setup=signal_data['crt_setup'],
                    pdh=signal_data['pdh'],
                    pdl=signal_data['pdl'],
                    metaapi_position_id=result['position_id'],
                    outcome='OPEN'
                )
                db.add(trade)
                db.commit()
                
                logger.info(f"[forex] trade recorded — {signal} {symbol} id={trade.id}")
                result['trade_id'] = trade.id
                
            except Exception as e:
                logger.error(f"[forex] db record error: {e}")
                db.rollback()
            finally:
                db.close()
        
        return result
        
    except Exception as e:
        logger.error(f"[forex] place order error: {e}")
        return {'success': False, 'error': str(e)}


def calculate_position_size(symbol: str, entry: float, sl: float, confidence: float) -> float:
    """
    Calculate position size in lots based on risk and confidence
    
    Args:
        symbol: Trading pair
        entry: Entry price
        sl: Stop loss price
        confidence: Signal confidence (85-99)
    
    Returns:
        Position size in lots
    """
    try:
        from config import FOREX_MAX_RISK_PCT, FOREX_LEVERAGE_TIERS, DEFAULT_PORTFOLIO
        
        account_balance = DEFAULT_PORTFOLIO
        risk_pct = FOREX_MAX_RISK_PCT
        
        risk_amount = account_balance * risk_pct
        
        pip_value = 0.0001 if 'JPY' not in symbol else 0.01
        if symbol.startswith('XAU'):
            pip_value = 0.01
        
        risk_pips = abs(entry - sl) / pip_value
        
        if risk_pips < 1:
            logger.warning(f"[forex] {symbol} risk too small: {risk_pips:.2f} pips")
            return 0.0
        
        leverage = 1
        for conf_threshold in sorted(FOREX_LEVERAGE_TIERS.keys(), reverse=True):
            if confidence >= conf_threshold:
                leverage = FOREX_LEVERAGE_TIERS[conf_threshold]
                break
        
        standard_lot_value = 100000
        if symbol.startswith('XAU'):
            standard_lot_value = 100
        
        pip_value_per_lot = 10 if 'JPY' not in symbol else 1000
        if symbol.startswith('XAU'):
            pip_value_per_lot = 1
        
        lots_needed = risk_amount / (risk_pips * pip_value_per_lot)
        
        lots_with_leverage = lots_needed * (leverage / 10)
        
        lots = round(lots_with_leverage, 2)
        lots = max(0.01, min(lots, 10.0))
        
        logger.info(f"[forex] {symbol} position size: {lots} lots (leverage={leverage}:1 conf={confidence}% risk_pips={risk_pips:.1f})")
        
        return lots
        
    except Exception as e:
        logger.error(f"[forex] position size calc error: {e}")
        return 0.01


async def _close_position_async(position_id: str) -> bool:
    """Close position via MetaApi"""
    try:
        from modules.market_data_forex import _get_metaapi_connection
        
        conn, _ = await _get_metaapi_connection()
        if conn is None:
            return False
        
        await conn.close_position(position_id)
        logger.info(f"[forex] position closed — id={position_id}")
        return True
        
    except Exception as e:
        logger.error(f"[forex] close position error {position_id}: {e}")
        return False


def close_forex_position(position_id: str, trade_id: int, pnl: float) -> bool:
    """
    Close forex position and update database
    
    Args:
        position_id: MetaApi position ID
        trade_id: Database trade ID
        pnl: Profit/loss in USD
    
    Returns:
        True if successful
    """
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    
    success = loop.run_until_complete(_close_position_async(position_id))
    
    if success:
        db = SessionLocal()
        try:
            trade = db.query(ForexTrade).filter(ForexTrade.id == trade_id).first()
            if trade:
                trade.outcome = 'WIN' if pnl > 0 else 'LOSS'
                trade.pnl = pnl
                trade.closed_at = datetime.utcnow()
                db.commit()
                logger.info(f"[forex] trade closed — id={trade_id} pnl=${pnl:.2f}")
        except Exception as e:
            logger.error(f"[forex] db update error: {e}")
            db.rollback()
        finally:
            db.close()
    
    return success
