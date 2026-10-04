"""
backend/modules/forex_position_manager.py
Monitor and manage forex positions via MetaApi
"""
import logging
from typing import List, Dict
from database import SessionLocal
from models import ForexTrade
from datetime import datetime

logger = logging.getLogger(__name__)


def check_forex_positions():
    """
    Check all open forex positions and update database
    """
    try:
        from modules.market_data_forex import get_open_positions
        from modules.forex_executor import close_forex_position
        
        positions = get_open_positions()
        
        if not positions:
            return
        
        db = SessionLocal()
        try:
            open_trades = db.query(ForexTrade).filter(ForexTrade.outcome == 'OPEN').all()
            
            position_ids = {p['id'] for p in positions}
            
            for trade in open_trades:
                if trade.metaapi_position_id not in position_ids:
                    logger.info(f"[forex] trade {trade.id} closed externally or hit SL/TP")
                    trade.outcome = 'CLOSED_EXTERNAL'
                    trade.closed_at = datetime.utcnow()
                    db.commit()
            
            for pos in positions:
                trade = db.query(ForexTrade).filter(
                    ForexTrade.metaapi_position_id == pos['id'],
                    ForexTrade.outcome == 'OPEN'
                ).first()
                
                if trade:
                    current_pnl = pos['profit'] + pos.get('swap', 0) + pos.get('commission', 0)
                    logger.debug(f"[forex] {trade.symbol} position {pos['id']} pnl=${current_pnl:.2f}")
        
        except Exception as e:
            logger.error(f"[forex] position check error: {e}")
            db.rollback()
        finally:
            db.close()
            
    except Exception as e:
        logger.error(f"[forex] position monitor error: {e}")


def get_forex_position_summary() -> Dict:
    """
    Get summary of forex positions
    
    Returns:
        dict with open positions, total pnl, win rate
    """
    db = SessionLocal()
    try:
        from modules.market_data_forex import get_open_positions
        
        open_trades = db.query(ForexTrade).filter(ForexTrade.outcome == 'OPEN').all()
        closed_trades = db.query(ForexTrade).filter(ForexTrade.outcome.in_(['WIN', 'LOSS'])).all()
        
        positions = get_open_positions()
        position_map = {p['id']: p for p in positions}
        
        open_positions = []
        for trade in open_trades:
            pos = position_map.get(trade.metaapi_position_id)
            if pos:
                pnl = pos['profit'] + pos.get('swap', 0) + pos.get('commission', 0)
                open_positions.append({
                    'id': trade.id,
                    'symbol': trade.symbol,
                    'signal': trade.signal,
                    'entry': trade.entry_price,
                    'current': pos['current_price'],
                    'sl': trade.stop_loss,
                    'tp': trade.take_profit,
                    'pnl': round(pnl, 2),
                    'lots': trade.lots,
                    'confidence': trade.confidence,
                    'kronos_bias': trade.kronos_bias,
                    'crt_setup': trade.crt_setup,
                    'opened_at': trade.created_at.isoformat() if trade.created_at else None
                })
        
        total_pnl = sum([t.pnl for t in closed_trades if t.pnl is not None])
        wins = len([t for t in closed_trades if t.outcome == 'WIN'])
        losses = len([t for t in closed_trades if t.outcome == 'LOSS'])
        win_rate = (wins / (wins + losses) * 100) if (wins + losses) > 0 else 0
        
        return {
            'open_count': len(open_positions),
            'open_positions': open_positions,
            'total_pnl': round(total_pnl, 2),
            'closed_trades': wins + losses,
            'wins': wins,
            'losses': losses,
            'win_rate': round(win_rate, 1)
        }
        
    except Exception as e:
        logger.error(f"[forex] summary error: {e}")
        return {
            'open_count': 0,
            'open_positions': [],
            'total_pnl': 0,
            'closed_trades': 0,
            'wins': 0,
            'losses': 0,
            'win_rate': 0
        }
    finally:
        db.close()


def can_open_forex_trade(symbol: str) -> tuple[bool, str]:
    """
    Check if we can open a new forex trade
    
    Args:
        symbol: Trading pair
    
    Returns:
        (allowed, reason)
    """
    try:
        from config import FOREX_MAX_TRADES
        
        db = SessionLocal()
        try:
            open_count = db.query(ForexTrade).filter(ForexTrade.outcome == 'OPEN').count()
            
            if open_count >= FOREX_MAX_TRADES:
                return False, f"Max forex trades reached ({open_count}/{FOREX_MAX_TRADES})"
            
            existing = db.query(ForexTrade).filter(
                ForexTrade.symbol == symbol,
                ForexTrade.outcome == 'OPEN'
            ).first()
            
            if existing:
                return False, f"{symbol} already has open position"
            
            return True, "OK"
            
        finally:
            db.close()
            
    except Exception as e:
        logger.error(f"[forex] can_open check error: {e}")
        return False, "Check failed"


def get_forex_trade_history(limit: int = 50) -> List[Dict]:
    """
    Get forex trade history
    
    Args:
        limit: Max trades to return
    
    Returns:
        List of trade dicts
    """
    db = SessionLocal()
    try:
        trades = db.query(ForexTrade).order_by(
            ForexTrade.created_at.desc()
        ).limit(limit).all()
        
        return [{
            'id': t.id,
            'symbol': t.symbol,
            'signal': t.signal,
            'confidence': t.confidence,
            'entry': t.entry_price,
            'sl': t.stop_loss,
            'tp': t.take_profit,
            'lots': t.lots,
            'kronos_bias': t.kronos_bias,
            'crt_setup': t.crt_setup,
            'pdh': t.pdh,
            'pdl': t.pdl,
            'outcome': t.outcome,
            'pnl': t.pnl,
            'opened': t.created_at.isoformat() if t.created_at else None,
            'closed': t.closed_at.isoformat() if t.closed_at else None
        } for t in trades]
        
    except Exception as e:
        logger.error(f"[forex] history error: {e}")
        return []
    finally:
        db.close()
