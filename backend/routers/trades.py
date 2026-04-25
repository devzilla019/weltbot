from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from database import get_db
from models import Trade, SignalAccuracy, SignalCache
from modules.trade_simulator import evaluate_open_trades

router = APIRouter(prefix="/api/trades", tags=["trades"])

@router.get("/")
def list_trades(db: Session = Depends(get_db), limit: int = 50):
    return db.query(Trade).order_by(
        Trade.created_at.desc()
    ).limit(limit).all()

@router.post("/evaluate")
def evaluate(db: Session = Depends(get_db)):
    closed   = evaluate_open_trades(db)
    affected = {t["asset"] for t in closed}
    for asset in affected:
        db.query(SignalCache).filter(
            SignalCache.asset == asset
        ).delete()
    db.commit()
    return {"evaluated": len(closed), "closed": closed}

@router.get("/accuracy")
def accuracy(db: Session = Depends(get_db)):
    return db.query(SignalAccuracy).all()

@router.post("/{trade_id}/close")
def manual_close_trade(trade_id: int, db: Session = Depends(get_db)):
    """Allow user to manually close an open trade."""
    trade = db.query(Trade).filter(Trade.id == trade_id, Trade.outcome == "OPEN").first()
    if not trade:
        return {"success": False, "error": "Trade not found or already closed"}
    try:
        from modules.executor import close_position
        result = close_position(trade.asset, trade.position_sz, trade.id)
        return {"success": True, "message": f"Closed {trade.asset}", "pnl": result.get("pnl", 0)}
    except Exception as e:
        return {"success": False, "error": str(e)}