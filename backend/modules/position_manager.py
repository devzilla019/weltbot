from datetime import datetime, date, timedelta
from database import SessionLocal
from models import Trade
from modules.market_data import get_ticker_price
from config import DAILY_DRAWDOWN_LIMIT, SL_COOLDOWN_HOURS, DEFAULT_PORTFOLIO, MAX_TRADES_PER_ASSET_PER_DAY

_sl_cooldowns = {}


def set_sl_cooldown(symbol):
    _sl_cooldowns[symbol] = datetime.utcnow()
    print(f"[pm] SL cooldown set for {symbol} — {SL_COOLDOWN_HOURS}h")


def is_on_cooldown(symbol):
    if symbol not in _sl_cooldowns:
        return False
    elapsed = datetime.utcnow() - _sl_cooldowns[symbol]
    if elapsed > timedelta(hours=SL_COOLDOWN_HOURS):
        del _sl_cooldowns[symbol]
        return False
    return True


def get_trades_today(db, symbol):
    start = datetime.combine(date.today(), datetime.min.time())
    return db.query(Trade).filter(
        Trade.asset      == symbol,
        Trade.created_at >= start,
    ).count()


def can_reenter(symbol, db):
    if is_on_cooldown(symbol):
        return False, "SL cooldown active"
    if get_trades_today(db, symbol) >= MAX_TRADES_PER_ASSET_PER_DAY:
        return False, "Max daily trades reached"
    open_trade = db.query(Trade).filter(
        Trade.asset   == symbol,
        Trade.outcome == "OPEN"
    ).first()
    if open_trade:
        return False, "Already in open trade"
    return True, "ok"


def check_and_exit_positions():
    from modules.executor import close_position
    db = SessionLocal()
    try:
        open_trades = db.query(Trade).filter(Trade.outcome == "OPEN").all()
        for t in open_trades:
            if not t.stop_loss or not t.take_profit:
                continue
            current = get_ticker_price(t.asset)
            if current <= 0:
                continue
            hit_sl = (t.signal == "BUY"  and current <= t.stop_loss) or \
                     (t.signal == "SELL" and current >= t.stop_loss)
            hit_tp = (t.signal == "BUY"  and current >= t.take_profit) or \
                     (t.signal == "SELL" and current <= t.take_profit)
            if hit_tp:
                print(f"[pm] TP HIT {t.asset} @ {current}")
                close_position(t.asset, t.position_sz, t.id)
            elif hit_sl:
                print(f"[pm] SL HIT {t.asset} @ {current}")
                close_position(t.asset, t.position_sz, t.id)
                set_sl_cooldown(t.asset)
    except Exception as e:
        print(f"[pm] exit error: {e}")
    finally:
        db.close()


def daily_drawdown_check():
    db = SessionLocal()
    try:
        start  = datetime.combine(date.today(), datetime.min.time())
        trades = db.query(Trade).filter(
            Trade.closed_at   >= start,
            Trade.outcome.in_(["WIN", "LOSS"])
        ).all()
        daily_pnl = sum(t.pnl or 0 for t in trades)
        balance   = DEFAULT_PORTFOLIO
        try:
            from modules.market_data import get_balance
            b = get_balance()
            if b > 0:
                balance = b
        except Exception:
            pass
        if daily_pnl < -(balance * DAILY_DRAWDOWN_LIMIT):
            print(f"[pm] DAILY DRAWDOWN HIT — day P&L: ${daily_pnl:.4f}")
            return True
        return False
    except Exception as e:
        print(f"[pm] drawdown error: {e}")
        return False
    finally:
        db.close()