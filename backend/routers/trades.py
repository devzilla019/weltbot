from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import func
from database import get_db
from models import Trade
from datetime import datetime

router = APIRouter(prefix="/api/trades", tags=["trades"])


@router.get("/")
def get_trades(db: Session = Depends(get_db)):
    trades = db.query(Trade).order_by(Trade.id.desc()).limit(200).all()
    return [
        {
            "id":           t.id,
            "asset":        t.asset,
            "signal":       t.signal,
            "confidence":   t.confidence,
            "entry_price":  t.entry_price,
            "stop_loss":    t.stop_loss,
            "take_profit":  t.take_profit,
            "position_sz":  t.position_sz,
            "outcome":      t.outcome,
            "pnl":          t.pnl,
            "created_at":   t.created_at.isoformat() if t.created_at else None,
            "closed_at":    t.closed_at.isoformat()  if t.closed_at  else None,
            "date":         t.created_at.strftime("%d %b %Y") if t.created_at else "—",
            "time":         t.created_at.strftime("%H:%M:%S")  if t.created_at else "—",
            "closed_date":  t.closed_at.strftime("%d %b %Y")  if t.closed_at  else None,
            "closed_time":  t.closed_at.strftime("%H:%M:%S")   if t.closed_at  else None,
        }
        for t in trades
    ]


@router.post("/evaluate")
def evaluate_trades(db: Session = Depends(get_db)):
    from modules.market_data import get_ticker_price
    open_trades = db.query(Trade).filter(Trade.outcome == "OPEN").all()
    evaluated = 0
    for t in open_trades:
        if not t.stop_loss or not t.take_profit:
            continue
        price = get_ticker_price(t.asset)
        if price <= 0:
            continue
        hit_tp = (t.signal == "BUY"  and price >= t.take_profit) or \
                 (t.signal == "SELL" and price <= t.take_profit)
        hit_sl = (t.signal == "BUY"  and price <= t.stop_loss)  or \
                 (t.signal == "SELL" and price >= t.stop_loss)
        if hit_tp or hit_sl:
            from modules.executor import close_position
            close_position(t.asset, t.position_sz, t.id)
            evaluated += 1
    db.commit()
    return {"evaluated": evaluated}


@router.post("/{trade_id}/close")
def manual_close_trade(trade_id: int, db: Session = Depends(get_db)):
    trade = db.query(Trade).filter(
        Trade.id == trade_id, Trade.outcome == "OPEN"
    ).first()
    if not trade:
        return {"success": False, "error": "Trade not found or already closed"}
    try:
        from modules.executor import close_position
        result = close_position(trade.asset, trade.position_sz, trade.id)
        return {"success": True, "message": f"Closed {trade.asset}", "pnl": result.get("pnl", 0)}
    except Exception as e:
        return {"success": False, "error": str(e)}


@router.delete("/clear")
def clear_all_trades(db: Session = Depends(get_db)):
    """Clear all trade history to start fresh."""
    deleted = db.query(Trade).delete()
    db.commit()
    return {"success": True, "deleted": deleted, "message": f"Cleared {deleted} trades"}