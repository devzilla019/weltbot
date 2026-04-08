from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import func
from database import get_db
from models import Trade
from modules.market_data import get_balance, get_ticker_price

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