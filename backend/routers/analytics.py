from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import func
from database import get_db
from models import Trade

router = APIRouter(prefix="/api/analytics", tags=["analytics"])

@router.get("/summary")
def summary(db: Session = Depends(get_db)):
    total   = db.query(Trade).count()
    wins    = db.query(Trade).filter(Trade.outcome == "WIN").count()
    losses  = db.query(Trade).filter(Trade.outcome == "LOSS").count()
    open_ct = db.query(Trade).filter(Trade.outcome == "OPEN").count()
    pnl     = db.query(func.sum(Trade.pnl)).scalar() or 0.0
    return {
        "total":     total,
        "wins":      wins,
        "losses":    losses,
        "open":      open_ct,
        "win_rate":  round(wins / max(wins + losses, 1) * 100, 1),
        "total_pnl": round(pnl, 2),
    }