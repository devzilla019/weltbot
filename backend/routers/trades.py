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