import json
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from database import get_db
from models import SignalAccuracy, SignalCache, Trade
from modules.signal_engine   import compute_signal
from modules.risk_manager    import calculate_risk
from config import MIN_CONFIDENCE

router = APIRouter(prefix="/api/signals", tags=["signals"])


def _get_bias(db, symbol):
    acc = db.query(SignalAccuracy).filter(
        SignalAccuracy.asset == symbol
    ).first()
    return acc.conf_bias if acc else 0.0


def _build_payload(symbol, balance=10.0):
    sig = compute_signal(symbol)
    if "error" in sig:
        return None
    atr  = sig["market"].get("atr", 0)
    risk = calculate_risk(
        sig["market"]["price"],
        sig["signal"],
        sig["confidence"],
        atr,
        balance,
    )
    return {"signal_data": sig, "risk_plan": risk}


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
    symbol  = symbol.replace("-", "/")
    cutoff  = datetime.utcnow() - timedelta(hours=4)
    recent  = db.query(Trade).filter(
        Trade.asset      == symbol,
        Trade.created_at >= cutoff,
        Trade.outcome    == "OPEN",
    ).first()
    if recent:
        return {"message": f"Cooldown active for {symbol}"}
    payload = _build_payload(symbol)
    if not payload:
        return {"error": "Could not compute signal"}
    sig  = payload["signal_data"]
    risk = payload["risk_plan"]
    if sig["signal"] == "HOLD":
        return {"message": "HOLD — no trade"}
    from modules.executor import place_order
    result = place_order(
        symbol         = symbol,
        signal         = sig["signal"],
        position_units = risk["position_size_units"],
        stop_loss      = risk["stop_loss"],
        take_profit    = risk["take_profit"],
        confidence     = sig["confidence"],
    )
    return result