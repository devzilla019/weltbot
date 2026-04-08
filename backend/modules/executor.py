from datetime import datetime
from database import SessionLocal
from models import Trade
from modules.market_data import place_order_raw, get_ticker_price


def place_order(symbol, signal, position_units, stop_loss, take_profit, confidence):
    db = SessionLocal()
    try:
        side   = "BUY" if signal == "BUY" else "SELL"
        result = place_order_raw(symbol, side, position_units)
        if not result["success"]:
            print(f"[executor] order failed {symbol}: {result.get('error')}")
            return result
        fill_price = result.get("fill_price", 0)
        if fill_price == 0:
            fill_price = get_ticker_price(symbol)
        trade = Trade(
            asset            = symbol,
            signal           = signal,
            confidence       = confidence,
            entry_price      = fill_price,
            stop_loss        = stop_loss,
            take_profit      = take_profit,
            position_sz      = position_units,
            risk_usd         = 0,
            risk_reward      = 2.5,
            outcome          = "OPEN",
            binance_order_id = result.get("order_id", ""),
        )
        db.add(trade)
        db.commit()
        db.refresh(trade)
        print(f"[executor] {signal} {position_units} {symbol} @ {fill_price}")
        return {
            "success":    True,
            "trade_id":   trade.id,
            "fill_price": fill_price,
        }
    except Exception as e:
        print(f"[executor] place_order error: {e}")
        return {"success": False, "error": str(e)}
    finally:
        db.close()


def close_position(symbol, position_units, trade_id):
    db = SessionLocal()
    try:
        result     = place_order_raw(symbol, "SELL", position_units)
        fill_price = result.get("fill_price", 0)
        if fill_price == 0:
            fill_price = get_ticker_price(symbol)
        trade = db.query(Trade).filter(Trade.id == trade_id).first()
        if trade:
            pnl_pct = (fill_price - trade.entry_price) / trade.entry_price
            if trade.signal == "SELL":
                pnl_pct = -pnl_pct
            pnl_usd         = round(pnl_pct * trade.position_sz * trade.entry_price, 6)
            trade.pnl       = pnl_usd
            trade.outcome   = "WIN" if pnl_usd > 0 else "LOSS"
            trade.closed_at = datetime.utcnow()
            db.commit()
            print(f"[executor] closed {symbol} @ {fill_price} pnl=${pnl_usd:.4f}")
        return {"success": True, "fill_price": fill_price}
    except Exception as e:
        print(f"[executor] close_position error: {e}")
        return {"success": False, "error": str(e)}
    finally:
        db.close()