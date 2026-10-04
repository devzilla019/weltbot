"""
backend/modules/market_data_forex.py
MetaApi candle fetching for Forex/Metals
"""
import asyncio
import os
import pandas as pd
from datetime import datetime, timedelta
from typing import Optional, List, Dict
import logging

logger = logging.getLogger(__name__)

_metaapi_connection = None
_metaapi_rpc = None
_connection_lock = asyncio.Lock()


async def _get_metaapi_connection():
    """Get or create MetaApi connection"""
    global _metaapi_connection, _metaapi_rpc
    
    from config import METAAPI_TOKEN, METAAPI_ACCOUNT_ID, FOREX_ENABLED
    
    if not FOREX_ENABLED:
        logger.warning("[metaapi] forex disabled")
        return None, None
    
    if not METAAPI_TOKEN or not METAAPI_ACCOUNT_ID:
        logger.error("[metaapi] missing credentials")
        return None, None
    
    async with _connection_lock:
        if _metaapi_connection is not None:
            try:
                if _metaapi_connection.health_status['connected']:
                    return _metaapi_connection, _metaapi_rpc
            except:
                pass
        
        try:
            from metaapi_cloud_sdk import MetaApi
            
            logger.info("[metaapi] connecting...")
            api = MetaApi(METAAPI_TOKEN)
            account = await api.metatrader_account_api.get_account(METAAPI_ACCOUNT_ID)
            
            _metaapi_connection = account.get_streaming_connection()
            await _metaapi_connection.connect()
            await _metaapi_connection.wait_synchronized()
            
            _metaapi_rpc = account.get_rpc_connection()
            await _metaapi_rpc.connect()
            await _metaapi_rpc.wait_synchronized()
            
            logger.info("[metaapi] connected successfully")
            return _metaapi_connection, _metaapi_rpc
            
        except Exception as e:
            logger.error(f"[metaapi] connection failed: {e}")
            return None, None


async def _fetch_candles_async(symbol: str, timeframe: str, start_time: datetime, limit: int = 400) -> Optional[pd.DataFrame]:
    """Fetch historical candles from MetaApi"""
    try:
        _, rpc = await _get_metaapi_connection()
        if rpc is None:
            return None
        
        candles = await rpc.get_historical_candles(
            symbol=symbol,
            timeframe=timeframe,
            start_time=start_time,
            limit=limit
        )
        
        if not candles:
            logger.warning(f"[metaapi] no candles returned for {symbol} {timeframe}")
            return None
        
        df = pd.DataFrame([{
            'timestamp': c['time'],
            'open': c['open'],
            'high': c['high'],
            'low': c['low'],
            'close': c['close'],
            'volume': c.get('tickVolume', 0)
        } for c in candles])
        
        df['timestamp'] = pd.to_datetime(df['timestamp'])
        df = df.sort_values('timestamp').reset_index(drop=True)
        
        return df
        
    except Exception as e:
        logger.error(f"[metaapi] fetch error {symbol} {timeframe}: {e}")
        return None


def get_candles(symbol: str, timeframe: str = '1h', limit: int = 400) -> Optional[pd.DataFrame]:
    """Sync wrapper for fetching candles"""
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    
    if timeframe == '1h':
        start_time = datetime.utcnow() - timedelta(hours=limit + 10)
    elif timeframe == '15m':
        start_time = datetime.utcnow() - timedelta(minutes=15 * limit + 100)
    elif timeframe == '5m':
        start_time = datetime.utcnow() - timedelta(minutes=5 * limit + 50)
    elif timeframe == '1d':
        start_time = datetime.utcnow() - timedelta(days=limit + 5)
    else:
        start_time = datetime.utcnow() - timedelta(hours=limit)
    
    return loop.run_until_complete(_fetch_candles_async(symbol, timeframe, start_time, limit))


async def _get_current_price_async(symbol: str) -> Optional[float]:
    """Get current market price"""
    try:
        conn, _ = await _get_metaapi_connection()
        if conn is None:
            return None
        
        price = await conn.get_symbol_price(symbol)
        return (price['ask'] + price['bid']) / 2
        
    except Exception as e:
        logger.error(f"[metaapi] price error {symbol}: {e}")
        return None


def get_current_price(symbol: str) -> Optional[float]:
    """Sync wrapper for current price"""
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    
    return loop.run_until_complete(_get_current_price_async(symbol))


async def _get_positions_async() -> List[Dict]:
    """Get all open positions"""
    try:
        conn, _ = await _get_metaapi_connection()
        if conn is None:
            return []
        
        state = conn.terminal_state
        positions = state.positions or []
        
        return [{
            'id': p['id'],
            'symbol': p['symbol'],
            'type': p['type'],
            'volume': p['volume'],
            'open_price': p['openPrice'],
            'current_price': p['currentPrice'],
            'profit': p['profit'],
            'swap': p.get('swap', 0),
            'commission': p.get('commission', 0),
            'sl': p.get('stopLoss'),
            'tp': p.get('takeProfit'),
            'open_time': p['time']
        } for p in positions]
        
    except Exception as e:
        logger.error(f"[metaapi] positions error: {e}")
        return []


def get_open_positions() -> List[Dict]:
    """Sync wrapper for positions"""
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    
    return loop.run_until_complete(_get_positions_async())


async def _reconnect_async():
    """Reconnect to MetaApi"""
    global _metaapi_connection, _metaapi_rpc
    
    async with _connection_lock:
        if _metaapi_connection:
            try:
                await _metaapi_connection.close()
            except:
                pass
        if _metaapi_rpc:
            try:
                await _metaapi_rpc.close()
            except:
                pass
        
        _metaapi_connection = None
        _metaapi_rpc = None
    
    await _get_metaapi_connection()


def reconnect():
    """Sync wrapper for reconnect"""
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    
    loop.run_until_complete(_reconnect_async())
    logger.info("[metaapi] reconnected")
