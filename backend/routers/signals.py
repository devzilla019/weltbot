import json
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from database import get_db
from models import SignalAccuracy, SignalCache, Trade
from modules.signal_engine   import compute_signal
from modules.risk_manager    import calculate_risk
from modules.trade_simulator import log_trade
from config import ALL_ASSETS

router = APIRouter(prefix="/api/signals", tags=["signals"])

def _get_bias(db, symbol):
    acc = db.query(SignalAccuracy).filter(
        SignalAccuracy.asset == symbol
    ).first()
    return acc.conf_bias if acc else 0.0

def _build_payload(symbol, bias):
    sig = compute_signal(symbol, learned_bias=bias)
    if "error" in sig:
        return None
    atr  = sig["market"].get("atr")
    risk = calculate_risk(
        sig["market"]["price"], sig["signal"],
        sig["confidence"], atr=atr
    )
    return {"signal_data": sig, "risk_plan": risk}

@router.get("/")
def get_all_signals(db: Session = Depends(get_db)):
    results = []
    for symbol in ALL_ASSETS:
        cached = db.query(SignalCache).filter(
            SignalCache.asset == symbol
        ).first()
        if cached:
            results.append(json.loads(cached.payload))
        else:
            payload = _build_payload(symbol, _get_bias(db, symbol))
            if payload:
                db.add(SignalCache(
                    asset=symbol, payload=json.dumps(payload)
                ))
                db.commit()
                results.append(payload)
    return results

@router.get("/{symbol}")
def get_signal(symbol: str, db: Session = Depends(get_db)):
    payload = _build_payload(symbol, _get_bias(db, symbol))
    if payload:
        return payload
    return {"error": f"Could not fetch data for {symbol}"}

@router.post("/{symbol}/execute")
def execute_signal(symbol: str, db: Session = Depends(get_db)):
    cutoff = datetime.utcnow() - timedelta(hours=4)
    recent = db.query(Trade).filter(
        Trade.asset      == symbol,
        Trade.created_at >= cutoff,
        Trade.outcome    == "OPEN",
    ).first()
    if recent:
        return {"message": f"Cooldown active — open trade exists for {symbol}"}
    payload = _build_payload(symbol, _get_bias(db, symbol))
    if not payload:
        return {"error": "Could not compute signal"}
    sig  = payload["signal_data"]
    risk = payload["risk_plan"]
    if sig["signal"] == "HOLD":
        return {"message": "HOLD — no trade executed"}
    trade = log_trade(
        db          = db,
        asset       = symbol,
        signal      = sig["signal"],
        confidence  = sig["confidence"],
        entry_price = sig["market"]["price"],
        stop_loss   = risk["stop_loss"],
        take_profit = risk["take_profit"],
        position_sz = risk["position_size"],
        risk_usd    = risk["risk_usd"],
        risk_reward = risk["risk_reward"],
    )
    return {
        "message":  "Trade simulated",
        "trade_id": trade.id,
        "risk_plan": risk,
    }