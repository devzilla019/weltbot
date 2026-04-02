from datetime import datetime
from models import Trade, SignalAccuracy
from modules.market_data import get_market_snapshot

def log_trade(db, asset, signal, confidence, entry_price,
              stop_loss, take_profit, position_sz, risk_usd, risk_reward):
    trade = Trade(
        asset       = asset,
        signal      = signal,
        confidence  = confidence,
        entry_price = entry_price,
        stop_loss   = stop_loss,
        take_profit = take_profit,
        position_sz = position_sz,
        risk_usd    = risk_usd,
        risk_reward = risk_reward,
        outcome     = "OPEN",
    )
    db.add(trade)
    db.commit()
    db.refresh(trade)
    return trade

def evaluate_open_trades(db):
    open_trades = db.query(Trade).filter(Trade.outcome == "OPEN").all()
    closed = []
    for t in open_trades:
        snap = get_market_snapshot(t.asset)
        if "error" in snap:
            continue
        current = snap["price"]
        hit_sl  = (t.signal == "BUY"  and current <= t.stop_loss) or \
                  (t.signal == "SELL" and current >= t.stop_loss)
        hit_tp  = (t.signal == "BUY"  and current >= t.take_profit) or \
                  (t.signal == "SELL" and current <= t.take_profit)
        if not (hit_sl or hit_tp):
            continue
        outcome = "WIN" if hit_tp else "LOSS"
        pnl_pct = (current - t.entry_price) / t.entry_price
        if t.signal == "SELL":
            pnl_pct = -pnl_pct
        pnl_usd     = round(pnl_pct * t.position_sz, 2)
        t.outcome   = outcome
        t.pnl       = pnl_usd
        t.closed_at = datetime.utcnow()
        db.commit()
        _update_accuracy(db, t.asset, outcome, t.confidence)
        closed.append({
            "id": t.id, "asset": t.asset,
            "outcome": outcome, "pnl": pnl_usd
        })
    return closed

def _update_accuracy(db, asset, outcome, confidence):
    rec = db.query(SignalAccuracy).filter(SignalAccuracy.asset == asset).first()
    if not rec:
        rec = SignalAccuracy(asset=asset)
        db.add(rec)
    rec.total += 1
    if outcome == "WIN":
        rec.wins += 1
    else:
        rec.losses += 1
    current_avg  = rec.avg_conf or 0.0
    rec.avg_conf = round(
        (current_avg * (rec.total - 1) + confidence) / rec.total, 2
    )
    win_rate      = rec.wins / rec.total
    rec.conf_bias = round((win_rate - 0.5) * 20, 3)
    db.commit()