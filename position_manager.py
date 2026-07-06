"""
backend/modules/position_manager.py
Updated to call update_compound_stats after every close
so the Kelly calculator learns from live results.
"""
import os
from datetime import datetime, timedelta
from database import SessionLocal
from models import Trade
from modules.market_data import get_ticker_price

SL_COOLDOWN_HOURS = int(os.getenv("SL_COOLDOWN_HOURS", "6"))
DAILY_LOSS_LIMIT  = float(os.getenv("DAILY_DRAWDOWN_LIMIT", "0.05"))


def can_reenter(symbol: str, db) -> tuple[bool, str]:
    cutoff = datetime.utcnow() - timedelta(hours=SL_COOLDOWN_HOURS)
    recent_sl = db.query(Trade).filter(
        Trade.asset      == symbol,
        Trade.outcome    == "LOSS",
        Trade.closed_at  >= cutoff,
    ).first()
    if recent_sl:
        return False, f"SL cooldown active for {symbol} ({SL_COOLDOWN_HOURS}h)"
    return True, "ok"


def daily_drawdown_check() -> bool:
    db = SessionLocal()
    try:
        from modules.market_data import get_balance
        balance  = get_balance()
        today    = datetime.utcnow().date()
        start_of_day = datetime.combine(today, datetime.min.time())
        day_losses = db.query(Trade).filter(
            Trade.outcome   == "LOSS",
            Trade.closed_at >= start_of_day,
        ).all()
        total_loss = sum(abs(t.pnl or 0) for t in day_losses)
        if balance > 0 and total_loss / balance >= DAILY_LOSS_LIMIT:
            print(f"[positions] daily drawdown hit: lost ${total_loss:.2f} today")
            return True
        return False
    except Exception as e:
        print(f"[positions] drawdown check error: {e}")
        return False
    finally:
        db.close()


def check_and_exit_positions():
    db = SessionLocal()
    try:
        open_trades = db.query(Trade).filter(Trade.outcome == "OPEN").all()
        for t in open_trades:
            if not t.stop_loss or not t.take_profit or not t.entry_price:
                continue
            current = get_ticker_price(t.asset)
            if current <= 0:
                continue

            hit_tp = (t.signal=="BUY"  and current >= t.take_profit) or \
                     (t.signal=="SELL" and current <= t.take_profit)
            hit_sl = (t.signal=="BUY"  and current <= t.stop_loss)  or \
                     (t.signal=="SELL" and current >= t.stop_loss)

            if hit_tp or hit_sl:
                outcome = "WIN" if hit_tp else "LOSS"
                if t.signal == "BUY":
                    pnl = (current - t.entry_price) * (t.position_sz or 0)
                else:
                    pnl = (t.entry_price - current) * (t.position_sz or 0)

                t.outcome   = outcome
                t.pnl       = round(pnl, 4)
                t.closed_at = datetime.utcnow()
                db.commit()

                # Update Kelly compound stats
                try:
                    from modules.risk_manager import update_compound_stats
                    from modules.market_data  import get_balance
                    bal = get_balance()
                    update_compound_stats(won=(outcome=="WIN"), pnl=pnl, balance=bal)
                except Exception as e:
                    print(f"[positions] kelly update error: {e}")

                print(f"[positions] {outcome} {t.asset} pnl=${pnl:.4f} @ {current}")
    except Exception as e:
        print(f"[positions] check error: {e}")
    finally:
        db.close()


def close_position_manually(trade_id: int) -> dict:
    db = SessionLocal()
    try:
        t = db.query(Trade).filter(Trade.id==trade_id, Trade.outcome=="OPEN").first()
        if not t:
            return {"success": False, "error": "Trade not found"}
        current = get_ticker_price(t.asset)
        if current <= 0:
            return {"success": False, "error": "Could not get price"}
        if t.signal == "BUY":
            pnl = (current - t.entry_price) * (t.position_sz or 0)
        else:
            pnl = (t.entry_price - current) * (t.position_sz or 0)
        t.outcome   = "WIN" if pnl >= 0 else "LOSS"
        t.pnl       = round(pnl, 4)
        t.closed_at = datetime.utcnow()
        db.commit()
        try:
            from modules.risk_manager import update_compound_stats
            from modules.market_data  import get_balance
            update_compound_stats(won=(pnl>=0), pnl=pnl, balance=get_balance())
        except Exception:
            pass
        return {"success": True, "pnl": round(pnl, 4), "outcome": t.outcome}
    except Exception as e:
        return {"success": False, "error": str(e)}
    finally:
        db.close()
