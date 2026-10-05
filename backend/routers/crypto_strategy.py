"""
backend/routers/crypto_strategy.py
Crypto 3-layer strategy API (Kronos + CRT + SMC on Binance)
"""
from fastapi import APIRouter, HTTPException
from typing import Dict, List
import logging

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/crypto", tags=["crypto-strategy"])


@router.get("/strategy")
def crypto_strategy_status() -> Dict:
    """
    Get crypto 3-layer strategy state: Kronos biases, CRT levels, active setups.
    """
    try:
        from config import KRONOS_ENABLED
        from modules.crypto_strategy import (
            get_all_crypto_biases, get_crypto_setups, _crypto_levels,
        )
        from modules.kronos_engine import is_kronos_available
        from modules.universe import get_universe

        return {
            'enabled': True,
            'kronos_enabled': KRONOS_ENABLED,
            'kronos_available': is_kronos_available(),
            'universe': get_universe(),
            'biases': get_all_crypto_biases(),
            'crt_levels': _crypto_levels.copy(),
            'active_setups': get_crypto_setups(),
        }
    except Exception as e:
        logger.error(f"[crypto-api] strategy error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/balance")
def crypto_balance() -> Dict:
    """Get Binance futures balance (separate from forex)."""
    try:
        from modules.market_data import get_balance
        bal = get_balance()
        return {'balance': round(float(bal or 0), 2), 'currency': 'USDT'}
    except Exception as e:
        logger.error(f"[crypto-api] balance error: {e}")
        return {'balance': 0.0, 'currency': 'USDT'}


@router.get("/pair/{symbol}")
def crypto_pair_detail(symbol: str) -> Dict:
    """Detailed strategy state for one crypto symbol."""
    try:
        from modules.crypto_strategy import get_crypto_bias, _crypto_levels, get_crypto_setups
        from modules.market_data import get_ticker_price

        sym = symbol.replace("-", "/")
        if "/" not in sym and sym.upper().endswith("USDT"):
            sym = sym.upper().replace("USDT", "/USDT")

        return {
            'symbol': sym,
            'price': get_ticker_price(sym),
            'bias': get_crypto_bias(sym),
            'levels': _crypto_levels.get(sym),
            'setup': get_crypto_setups().get(sym),
        }
    except Exception as e:
        logger.error(f"[crypto-api] pair error {symbol}: {e}")
        raise HTTPException(status_code=500, detail=str(e))
