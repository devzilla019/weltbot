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
        
        # Capital.com account balance (separate from crypto)
        account = None
        try:
            from modules.market_data_forex import get_capital_balance
            account = get_capital_balance()
        except Exception as e:
            logger.warning(f"[forex-api] account info unavailable: {e}")
        
        return {
            'enabled': True,
            'provider': 'capital.com',
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
    """Get Capital.com account balance (separate from crypto balance)."""
    try:
        from config import FOREX_ENABLED
        if not FOREX_ENABLED:
            return {'enabled': False, 'balance': 0.0, 'profit_loss': 0.0}
        from modules.market_data_forex import get_capital_balance
        info = get_capital_balance()
        return {'enabled': True, **info}
    except Exception as e:
        logger.error(f"[forex-api] balance error: {e}")
        return {'enabled': True, 'connected': False, 'balance': 0.0, 'profit_loss': 0.0}


@router.get("/test-connection")
def forex_test_connection() -> Dict:
    """
    Full Capital.com connectivity test for the dashboard button.
    Checks: env vars → session login → account balance → candle fetch.
    """
    try:
        from modules.market_data_forex import test_connection
        return test_connection()
    except Exception as e:
        logger.error(f"[forex-api] test-connection error: {e}")
        return {'connected': False, 'error': str(e)}


@router.get("/kronos-status")
def kronos_status() -> Dict:
    """Kronos model load state (for diagnostics)."""
    try:
        from modules.kronos_engine import get_kronos_status
        return get_kronos_status()
    except Exception as e:
        return {'state': 'error', 'error': str(e), 'available': False}


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
                levels_by_tf = get_cached_levels(symbol)   # {timeframe: level}
                price = get_current_price(symbol)

                if not levels_by_tf:
                    continue

                # Prefer the daily range for the headline PDH/PDL
                daily = levels_by_tf.get('1d') or next(iter(levels_by_tf.values()))

                signal = {
                    'symbol': symbol,
                    'current_price': price,
                    'pdh': daily.get('range_high'),
                    'pdl': daily.get('range_low'),
                    'timeframe': daily.get('timeframe', '1d'),
                    'ranges': {
                        tf: {'high': lv.get('range_high'), 'low': lv.get('range_low')}
                        for tf, lv in levels_by_tf.items()
                    },
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


@router.get("/cascade-stats")
def cascade_stats() -> Dict:
    """
    Performance grouped by the CRT timeframe chain that produced each trade.
    Lets you see which cascade combos actually win.
    """
    try:
        from database import SessionLocal
        from models import ForexTrade

        db = SessionLocal()
        try:
            trades = db.query(ForexTrade).filter(
                ForexTrade.outcome.in_(["WIN", "LOSS"])
            ).all()

            buckets: Dict[str, Dict] = {}
            for t in trades:
                key = f"{t.crt_timeframe or '?'}→{t.confirm_timeframe or '?'}→{t.entry_timeframe or '?'}"
                b = buckets.setdefault(key, {
                    "chain": key,
                    "crt_timeframe": t.crt_timeframe,
                    "confirm_timeframe": t.confirm_timeframe,
                    "entry_timeframe": t.entry_timeframe,
                    "trades": 0, "wins": 0, "losses": 0, "pnl": 0.0,
                })
                b["trades"] += 1
                if t.outcome == "WIN":
                    b["wins"] += 1
                else:
                    b["losses"] += 1
                b["pnl"] += (t.pnl or 0)

            out = []
            for b in buckets.values():
                b["win_rate"] = round(b["wins"] / max(b["trades"], 1) * 100, 1)
                b["pnl"] = round(b["pnl"], 2)
                out.append(b)

            out.sort(key=lambda x: x["trades"], reverse=True)

            # Also break down by POI type
            poi_buckets: Dict[str, Dict] = {}
            for t in trades:
                k = t.poi or "unknown"
                p = poi_buckets.setdefault(k, {"poi": k, "trades": 0, "wins": 0, "pnl": 0.0})
                p["trades"] += 1
                if t.outcome == "WIN":
                    p["wins"] += 1
                p["pnl"] += (t.pnl or 0)
            poi_out = []
            for p in poi_buckets.values():
                p["win_rate"] = round(p["wins"] / max(p["trades"], 1) * 100, 1)
                p["pnl"] = round(p["pnl"], 2)
                poi_out.append(p)
            poi_out.sort(key=lambda x: x["trades"], reverse=True)

            return {"chains": out, "poi": poi_out, "total_closed": len(trades)}
        finally:
            db.close()

    except Exception as e:
        logger.error(f"[forex-api] cascade-stats error: {e}")
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
    Manually trigger a multi-timeframe CRT range update for a symbol.
    """
    try:
        from modules.market_data_forex import get_candles
        from modules.crt_detector import calculate_range, CRT_TIMEFRAMES

        out = {}
        for tf in CRT_TIMEFRAMES:
            candles = get_candles(symbol, timeframe=tf, limit=60)
            if candles is None or len(candles) < 2:
                continue
            level = calculate_range(symbol, candles, timeframe=tf)
            if level:
                out[tf] = level

        if not out:
            raise HTTPException(status_code=500, detail="CRT range calculation failed")

        return {"symbol": symbol, "ranges": out}

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
        
        # levels is {timeframe: level}; expose the daily one as the headline
        daily = levels.get('1d') if isinstance(levels, dict) else None
        if daily is None and isinstance(levels, dict) and levels:
            daily = next(iter(levels.values()))

        # Active CRT setup (if any) — shows which timeframe triggered the trade
        active_setup = None
        try:
            from main import _forex_active_setups
            s = _forex_active_setups.get(symbol)
            if s:
                poi = s.get('poi')
                if isinstance(poi, dict):
                    poi = poi.get('kind')
                active_setup = {
                    'timeframe': s.get('timeframe'),
                    'sweep_type': s.get('sweep_type'),
                    'direction': s.get('direction'),
                    'target': s.get('target'),
                    'confirm_timeframe': s.get('confirm_timeframe'),
                    'entry_timeframe': s.get('entry_timeframe'),
                    'poi': poi,
                    'poi_status': s.get('poi_status', 'waiting'),
                }
        except Exception:
            pass

        return {
            'symbol': symbol,
            'current_price': price,
            'kronos_bias': bias,
            'crt_levels': daily,
            'crt_ranges': levels,
            'active_setup': active_setup,
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
