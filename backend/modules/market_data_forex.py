"""
backend/modules/market_data_forex.py
MetaApi candle fetching for Forex/Metals.

IMPORTANT: MetaApi's SDK is fully async and its internal locks/connections are
bound to a single event loop. The bot calls these functions from APScheduler
threads, so we run ONE dedicated background event loop for the whole process
and submit every coroutine to it. This avoids the classic
"<asyncio.Lock> is bound to a different event loop" error.
"""
import asyncio
import os
import threading
import pandas as pd
from datetime import datetime, timedelta
from typing import Optional, List, Dict
import logging

logger = logging.getLogger(__name__)

_metaapi_connection = None
_metaapi_rpc = None
_connection_lock: Optional[asyncio.Lock] = None   # created inside the loop
_last_error: Optional[str] = None

# ── Dedicated background event loop ───────────────────────────────────────────
_loop: Optional[asyncio.AbstractEventLoop] = None
_loop_thread: Optional[threading.Thread] = None
_loop_ready = threading.Event()


def _start_loop():
    """Start the dedicated event loop in a daemon thread (idempotent)."""
    global _loop, _loop_thread
    if _loop is not None and _loop.is_running():
        return
    if _loop_thread is not None and _loop_thread.is_alive():
        _loop_ready.wait(timeout=5)
        return

    def _runner():
        global _loop
        _loop = asyncio.new_event_loop()
        asyncio.set_event_loop(_loop)
        _loop_ready.set()
        _loop.run_forever()

    _loop_thread = threading.Thread(target=_runner, name="metaapi-loop", daemon=True)
    _loop_thread.start()
    _loop_ready.wait(timeout=5)


def _run(coro, timeout: float = 60.0):
    """Submit a coroutine to the dedicated loop and block for the result."""
    _start_loop()
    if _loop is None:
        raise RuntimeError("metaapi event loop unavailable")
    fut = asyncio.run_coroutine_threadsafe(coro, _loop)
    return fut.result(timeout=timeout)


def _get_lock() -> asyncio.Lock:
    """Lazily create the connection lock inside the dedicated loop."""
    global _connection_lock
    if _connection_lock is None:
        _connection_lock = asyncio.Lock()
    return _connection_lock


def get_last_error() -> Optional[str]:
    return _last_error


# ── Connection ────────────────────────────────────────────────────────────────

async def _get_metaapi_connection():
    """Get or create MetaApi connection (runs inside the dedicated loop)."""
    global _metaapi_connection, _metaapi_rpc, _last_error

    from config import METAAPI_TOKEN, METAAPI_ACCOUNT_ID, FOREX_ENABLED

    if not FOREX_ENABLED:
        _last_error = "FOREX_ENABLED is false"
        return None, None

    if not METAAPI_TOKEN or not METAAPI_ACCOUNT_ID:
        _last_error = "METAAPI_TOKEN / METAAPI_ACCOUNT_ID not set"
        logger.error(f"[metaapi] {_last_error}")
        return None, None

    async with _get_lock():
        if _metaapi_connection is not None:
            try:
                if _metaapi_connection.health_status.get('connected'):
                    return _metaapi_connection, _metaapi_rpc
            except Exception:
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

            _last_error = None
            logger.info("[metaapi] connected successfully")
            return _metaapi_connection, _metaapi_rpc

        except Exception as e:
            msg = str(e)
            if "invalid auth-token" in msg or "authorize" in msg.lower():
                _last_error = ("MetaApi rejected the token. Check METAAPI_TOKEN is a valid "
                               "MetaApi token (not your MT5 password) and METAAPI_ACCOUNT_ID "
                               "belongs to that token's account.")
            else:
                _last_error = msg
            logger.error(f"[metaapi] connection failed: {msg}")
            _metaapi_connection = None
            _metaapi_rpc = None
            return None, None


# ── Candles ───────────────────────────────────────────────────────────────────

async def _fetch_candles_async(symbol: str, timeframe: str, start_time: datetime, limit: int = 400) -> Optional[pd.DataFrame]:
    try:
        _, rpc = await _get_metaapi_connection()
        if rpc is None:
            return None

        candles = await rpc.get_historical_candles(
            symbol=symbol, timeframe=timeframe, start_time=start_time, limit=limit,
        )
        if not candles:
            logger.warning(f"[metaapi] no candles returned for {symbol} {timeframe}")
            return None

        df = pd.DataFrame([{
            'timestamp': c['time'],
            'open': c['open'], 'high': c['high'], 'low': c['low'], 'close': c['close'],
            'volume': c.get('tickVolume', 0),
        } for c in candles])

        df['timestamp'] = pd.to_datetime(df['timestamp'])
        df = df.sort_values('timestamp').reset_index(drop=True)
        return df

    except Exception as e:
        logger.error(f"[metaapi] fetch error {symbol} {timeframe}: {e}")
        return None


def get_candles(symbol: str, timeframe: str = '1h', limit: int = 400) -> Optional[pd.DataFrame]:
    """Sync wrapper — submits to the dedicated loop."""
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

    try:
        return _run(_fetch_candles_async(symbol, timeframe, start_time, limit))
    except Exception as e:
        logger.error(f"[metaapi] get_candles error {symbol}: {e}")
        return None


# ── Price ─────────────────────────────────────────────────────────────────────

async def _get_current_price_async(symbol: str) -> Optional[float]:
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
    try:
        return _run(_get_current_price_async(symbol))
    except Exception as e:
        logger.error(f"[metaapi] get_current_price error {symbol}: {e}")
        return None


# ── Account info ──────────────────────────────────────────────────────────────

async def _get_account_info_async() -> Optional[Dict]:
    try:
        conn, _ = await _get_metaapi_connection()
        if conn is None:
            return None
        info = conn.terminal_state.account_information
        if not info:
            return None
        return {
            'balance':  float(info.get('balance', 0) or 0),
            'equity':   float(info.get('equity', 0) or 0),
            'margin':   float(info.get('margin', 0) or 0),
            'free_margin': float(info.get('freeMargin', 0) or 0),
            'currency': info.get('currency', 'USD'),
            'leverage': info.get('leverage', 0),
            'profit':   float(info.get('profit', 0) or 0),
        }
    except Exception as e:
        logger.error(f"[metaapi] account info error: {e}")
        return None


def get_account_info() -> Optional[Dict]:
    try:
        return _run(_get_account_info_async())
    except Exception as e:
        logger.error(f"[metaapi] get_account_info error: {e}")
        return None


# ── Positions ─────────────────────────────────────────────────────────────────

async def _get_positions_async() -> List[Dict]:
    try:
        conn, _ = await _get_metaapi_connection()
        if conn is None:
            return []
        positions = conn.terminal_state.positions or []
        return [{
            'id': p['id'], 'symbol': p['symbol'], 'type': p['type'],
            'volume': p['volume'], 'open_price': p['openPrice'],
            'current_price': p['currentPrice'], 'profit': p['profit'],
            'swap': p.get('swap', 0), 'commission': p.get('commission', 0),
            'sl': p.get('stopLoss'), 'tp': p.get('takeProfit'), 'open_time': p['time'],
        } for p in positions]
    except Exception as e:
        logger.error(f"[metaapi] positions error: {e}")
        return []


def get_open_positions() -> List[Dict]:
    try:
        return _run(_get_positions_async())
    except Exception as e:
        logger.error(f"[metaapi] get_open_positions error: {e}")
        return []


# ── Order placement (used by forex_executor) ──────────────────────────────────

async def _place_order_async(symbol: str, signal: str, lots: float, sl: float, tp: float) -> Dict:
    try:
        conn, _ = await _get_metaapi_connection()
        if conn is None:
            return {'success': False, 'error': _last_error or 'MetaApi connection failed'}

        if signal == 'BUY':
            result = await conn.create_market_buy_order(symbol=symbol, volume=lots, stop_loss=sl, take_profit=tp)
        else:
            result = await conn.create_market_sell_order(symbol=symbol, volume=lots, stop_loss=sl, take_profit=tp)

        if result.get('orderId'):
            logger.info(f"[metaapi] order placed — {signal} {symbol} {lots} lots")
            return {
                'success': True,
                'position_id': result.get('positionId', result['orderId']),
                'fill_price': result.get('price', 0),
                'order_id': result['orderId'],
            }
        return {'success': False, 'error': result.get('message', 'Unknown error')}
    except Exception as e:
        logger.error(f"[metaapi] place order error {symbol}: {e}")
        return {'success': False, 'error': str(e)}


def place_order(symbol: str, signal: str, lots: float, sl: float, tp: float) -> Dict:
    try:
        return _run(_place_order_async(symbol, signal, lots, sl, tp))
    except Exception as e:
        return {'success': False, 'error': str(e)}


async def _close_position_async(position_id: str) -> bool:
    try:
        conn, _ = await _get_metaapi_connection()
        if conn is None:
            return False
        await conn.close_position(position_id)
        logger.info(f"[metaapi] position closed — id={position_id}")
        return True
    except Exception as e:
        logger.error(f"[metaapi] close position error {position_id}: {e}")
        return False


def close_position(position_id: str) -> bool:
    try:
        return _run(_close_position_async(position_id))
    except Exception as e:
        logger.error(f"[metaapi] close_position error: {e}")
        return False


# ── Reconnect ─────────────────────────────────────────────────────────────────

async def _reconnect_async():
    global _metaapi_connection, _metaapi_rpc
    async with _get_lock():
        for c in (_metaapi_connection, _metaapi_rpc):
            if c:
                try:
                    await c.close()
                except Exception:
                    pass
        _metaapi_connection = None
        _metaapi_rpc = None
    await _get_metaapi_connection()


def reconnect():
    try:
        _run(_reconnect_async())
        logger.info("[metaapi] reconnected")
    except Exception as e:
        logger.error(f"[metaapi] reconnect error: {e}")


# ── Health check (for the Test Connection button) ─────────────────────────────

def test_connection() -> Dict:
    """
    Full connectivity test used by /api/forex/test-connection.
    Returns a structured report the UI can render.
    """
    from config import METAAPI_TOKEN, METAAPI_ACCOUNT_ID, FOREX_ENABLED

    report = {
        'forex_enabled': FOREX_ENABLED,
        'token_set': bool(METAAPI_TOKEN),
        'account_id_set': bool(METAAPI_ACCOUNT_ID),
        'connected': False,
        'account': None,
        'symbols_ok': [],
        'symbols_failed': [],
        'error': None,
    }

    if not FOREX_ENABLED:
        report['error'] = "FOREX_ENABLED is false — set it to true on Railway"
        return report
    if not METAAPI_TOKEN or not METAAPI_ACCOUNT_ID:
        report['error'] = "METAAPI_TOKEN or METAAPI_ACCOUNT_ID missing"
        return report

    try:
        acct = get_account_info()
        if acct:
            report['connected'] = True
            report['account'] = acct
        else:
            report['error'] = _last_error or "Could not read account information"
            return report

        # Probe a couple of symbols
        for sym in ("EURUSD", "XAUUSD"):
            df = get_candles(sym, timeframe='1h', limit=5)
            if df is not None and len(df) > 0:
                report['symbols_ok'].append(sym)
            else:
                report['symbols_failed'].append(sym)

    except Exception as e:
        report['error'] = str(e)

    return report
