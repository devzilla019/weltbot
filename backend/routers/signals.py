"""
backend/routers/signals.py
Cached signal payloads.

The signal CACHE is retained (the dashboard reads it), but nothing computes new
entries from it any more. `compute_signal` belonged to the retired SMC engine,
so the read endpoints now serve whatever is already cached and the execute
endpoint refuses — see `execute_signal`.
"""
import json
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from database import get_db
from models import SignalAccuracy, SignalCache, Trade

router = APIRouter(prefix="/api/signals", tags=["signals"])


def _get_bias(db, symbol):
    acc = db.query(SignalAccuracy).filter(
        SignalAccuracy.asset == symbol
    ).first()
    return acc.conf_bias if acc else 0.0


def _build_payload(symbol, balance=10.0):
    """
    The cached payload for `symbol`, or None.

    This used to CALL the retired SMC engine to compute a fresh signal, which
    meant a read-only endpoint could produce a tradeable recommendation from an
    engine that can no longer trade. It now returns only what is already cached;
    the Silver Bullet state is served from /api/forex/silver-bullet and
    /api/crypto/strategy.
    """
    try:
        from database import SessionLocal
        from models import SignalCache

        db = SessionLocal()
        try:
            row = db.query(SignalCache).filter(SignalCache.symbol == symbol).first()
            if not row:
                return None
            return json.loads(row.payload)
        finally:
            db.close()
    except Exception:
        return None


@router.get("/")
def get_all_signals(db: Session = Depends(get_db)):
    results = []
    cached_all = db.query(SignalCache).all()
    for row in cached_all:
        try:
            results.append(json.loads(row.payload))
        except Exception:
            pass
    return results


@router.get("/{symbol:path}")
def get_signal(symbol: str, db: Session = Depends(get_db)):
    symbol  = symbol.replace("-", "/")
    payload = _build_payload(symbol)
    if payload:
        return payload
    return {"error": f"Could not fetch data for {symbol}"}


@router.post("/{symbol:path}/execute")
def execute_signal(symbol: str, db: Session = Depends(get_db)):
    """
    Execute a cached crypto signal — RETIRED as an order source.

    This endpoint used the SMC signal engine to place a Binance order, which is
    no longer the strategy. It is kept as a route so an existing caller gets an
    explicit, logged refusal instead of a 404 that looks like a bug, but it
    never reaches the exchange.

    `place_order` would refuse anyway (the shared strategy guard denies an
    unidentifiable source), so this is defence in depth rather than the only
    barrier.
    """
    from modules.strategy_guard import STRATEGY_LEGACY_SMC, refuse_order
    return refuse_order(STRATEGY_LEGACY_SMC, symbol=symbol, venue="signals-api")
