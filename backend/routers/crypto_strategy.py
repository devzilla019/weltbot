"""
backend/routers/crypto_strategy.py
Crypto strategy API — Silver Bullet state for the Binance universe.

The crypto tab used to report the retired Kronos/CRT/SMC engine's biases, levels
and setups. Those engines no longer generate trades, so reporting their state
would tell the operator a strategy is running that cannot trade. The endpoints
now serve the SAME Silver Bullet state the forex tab reads, filtered to the
crypto universe, so both screens describe one strategy.
"""
from fastapi import APIRouter, HTTPException
from typing import Dict, List
import logging

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/crypto", tags=["crypto-strategy"])


def _crypto_symbols() -> List[str]:
    from modules.universe import get_universe
    return list(get_universe())


def _silver_state() -> Dict:
    """The shared Silver Bullet state, from the router that owns it."""
    from routers.forex import _silver_bullet_state
    return _silver_bullet_state()


@router.get("/strategy")
def crypto_strategy_status() -> Dict:
    """
    Silver Bullet state for the crypto universe.

    The keys keep their original names (`biases`, `crt_levels`, `active_setups`)
    so an existing frontend build does not break on a missing field, but the
    DATA is now Silver Bullet's. `crt_levels` carries the previous-day volume
    profile rather than the retired CRT ranges, and `strategy` names what is
    actually running so nothing has to infer it from a stale key.
    """
    try:
        from modules.forex_executor import describe_symbol
        from modules.forex_signal_engine import MIN_CONFIDENCE, SESSIONS
        from modules.silver_bullet import get_active_setups

        universe = _crypto_symbols()
        state = _silver_state()

        # Only this venue's symbols.
        biases = {s: state.get("biases", {}).get(s)
                  for s in universe if s in state.get("biases", {})}
        setups = {s: v for s, v in get_active_setups().items() if s in universe}

        # The volume profile stands in for the old CRT range display.
        crt_levels = {}
        for symbol, rec in biases.items():
            vp = (rec or {}).get("vp_levels") or {}
            if vp:
                crt_levels[symbol] = {
                    "poc": vp.get("poc"), "vah": vp.get("vah"),
                    "val": vp.get("val"),
                    "volume_source": vp.get("volume_source"),
                    "source_trusted": vp.get("source_trusted"),
                }

        return {
            "enabled": True,
            "strategy": "SILVER_BULLET",
            "min_confidence": MIN_CONFIDENCE,
            "sessions": list(SESSIONS.keys()),
            "active_session": state.get("active_session"),
            "time_remaining_seconds": state.get("time_remaining_seconds", 0),
            "universe": universe,
            "routing": [describe_symbol(s, check_venue=False) for s in universe],
            "biases": biases,
            "crt_levels": crt_levels,
            "active_setups": setups,
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
    """Silver Bullet state for one crypto symbol."""
    try:
        from modules.forex_executor import describe_symbol
        from modules.market_data import get_ticker_price
        from modules.silver_bullet import get_active_setups, get_daily_bias

        sym = symbol.replace("-", "/")
        if "/" not in sym and sym.upper().endswith("USDT"):
            sym = sym.upper().replace("USDT", "/USDT")

        rec = get_daily_bias(sym) or {}
        vp = rec.get("vp_levels") or {}

        return {
            'symbol': sym,
            'strategy': 'SILVER_BULLET',
            'price': get_ticker_price(sym),
            'routing': describe_symbol(sym, check_venue=False),
            'h4_bias': rec.get("h4_bias"),
            'strength': rec.get("strength"),
            'price_position': rec.get("price_position"),
            'vp_levels': {
                "poc": vp.get("poc"), "vah": vp.get("vah"), "val": vp.get("val"),
                "volume_source": vp.get("volume_source"),
                "source_trusted": vp.get("source_trusted"),
                "valid": vp.get("valid"),
            } if vp else None,
            'vp_gateable': rec.get("vp_gateable"),
            'setup': get_active_setups().get(sym),
        }
    except Exception as e:
        logger.error(f"[crypto-api] pair error {symbol}: {e}")
        raise HTTPException(status_code=500, detail=str(e))
