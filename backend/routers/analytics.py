import os
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import func
from database import get_db
from models import Trade
from modules.market_data import get_balance, get_ticker_price
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from database import get_db

router = APIRouter(prefix="/api/analytics", tags=["analytics"])

@router.get("/summary")
def summary(db: Session = Depends(get_db)):
    total    = db.query(Trade).count()
    wins     = db.query(Trade).filter(Trade.outcome == "WIN").count()
    losses   = db.query(Trade).filter(Trade.outcome == "LOSS").count()
    open_ct  = db.query(Trade).filter(Trade.outcome == "OPEN").count()
    pnl      = db.query(func.sum(Trade.pnl)).scalar() or 0.0
    win_rate = round(wins / max(wins + losses, 1) * 100, 1)
    return {
        "total":     total,
        "wins":      wins,
        "losses":    losses,
        "open":      open_ct,
        "win_rate":  win_rate,
        "total_pnl": round(float(pnl), 4),
    }

@router.get("/portfolio")
def portfolio(db: Session = Depends(get_db)):
    balance    = get_balance()
    open_trades = db.query(Trade).filter(Trade.outcome == "OPEN").all()
    positions  = []
    unrealized = 0.0
    for t in open_trades:
        current = get_ticker_price(t.asset)
        if current > 0 and t.entry_price:
            pnl_pct = (current - t.entry_price) / t.entry_price
            if t.signal == "SELL":
                pnl_pct = -pnl_pct
            unreal  = round(pnl_pct * t.position_sz * t.entry_price, 4)
            unrealized += unreal
            positions.append({
                "asset":       t.asset,
                "signal":      t.signal,
                "entry":       t.entry_price,
                "current":     current,
                "pnl_pct":     round(pnl_pct * 100, 3),
                "unrealized":  unreal,
                "size":        t.position_sz,
                "sl":          t.stop_loss,
                "tp":          t.take_profit,
                "confidence":  t.confidence,
            })
    return {
        "balance_usdt": round(balance, 4),
        "open_count":   len(positions),
        "unrealized_pnl": round(unrealized, 4),
        "positions":    positions,
    }

@router.post("/settings/apikeys")
def update_api_keys(data: dict):
    """Update Binance API keys at runtime."""
    api_key    = data.get("api_key", "").strip()
    api_secret = data.get("api_secret", "").strip()
    if not api_key or not api_secret:
        return {"success": False, "error": "Both API key and secret are required"}
    os.environ["BINANCE_API_KEY"]    = api_key
    os.environ["BINANCE_SECRET_KEY"] = api_secret
    # Clear balance cache so it reconnects immediately
    try:
        from modules.market_data import _cached_balance
        import modules.market_data as md
        md._cached_balance = 0.0
        md._balance_ts     = 0.0
    except Exception:
        pass
    return {"success": True, "message": "API keys updated — bot will reconnect on next scan"}

@router.get("/settings/apikeys")
def get_api_keys_status():
    """Check if API keys are configured (never returns actual keys)."""
    key    = os.environ.get("BINANCE_API_KEY", "")
    secret = os.environ.get("BINANCE_SECRET_KEY", "")
    return {
        "configured": bool(key and secret),
        "key_preview": f"{key[:8]}...{key[-4:]}" if len(key) > 12 else "not set",
    } 