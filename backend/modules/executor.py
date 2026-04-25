from datetime import datetime
from database import SessionLocal
from models import Trade


def place_order(symbol, signal, position_units, stop_loss, take_profit, confidence):
    db = SessionLocal()
    try:
        from modules.market_data import place_order_raw, get_ticker_price, set_leverage
        from config import LEVERAGE_TIERS, MIN_CONFIDENCE

        if confidence < MIN_CONFIDENCE:
            print(f"[executor] {symbol} skipped — confidence {confidence}% below minimum {MIN_CONFIDENCE}%")
            return {"success": False, "error": f"Confidence {confidence}% below minimum {MIN_CONFIDENCE}%"}

        # Dynamic leverage based on confidence
        leverage = 10
        if confidence >= 95:
            leverage = 25
        elif confidence >= 90:
            leverage = 20
        elif confidence >= 85:
            leverage = 10

        side  = "BUY" if signal == "BUY" else "SELL"
        price = get_ticker_price(symbol)

        set_leverage(symbol, leverage=leverage)
        print(f"[executor] {symbol} confidence={confidence}% → {leverage}x leverage")

        result = place_order_raw(symbol, side, position_units)
        if not result["success"]:
            print(f"[executor] order failed {symbol}: {result.get('error')}")
            return result

        fill_price = result.get("fill_price", 0) or price

        trade = Trade(
            asset            = symbol,
            signal           = signal,
            confidence       = confidence,
            entry_price      = fill_price,
            stop_loss        = stop_loss,
            take_profit      = take_profit,
            position_sz      = position_units,
            risk_usd         = 0,
            risk_reward      = 2.0,
            outcome          = "OPEN",
            binance_order_id = result.get("order_id", ""),
        )
        db.add(trade)
        db.commit()
        db.refresh(trade)
        print(f"[executor] {signal} {position_units} {symbol} @ {fill_price} ({leverage}x)")
        return {
            "success":    True,
            "trade_id":   trade.id,
            "fill_price": fill_price,
            "leverage":   leverage,
        }
    except Exception as e:
        print(f"[executor] place_order error: {e}")
        return {"success": False, "error": str(e)}
    finally:
        db.close()

def close_position(symbol, position_units, trade_id):
    db = SessionLocal()
    try:
        from modules.market_data import get_ticker_price, place_order_raw

        trade = db.query(Trade).filter(Trade.id == trade_id).first()
        if not trade:
            return {"success": False, "error": "Trade not found"}

        close_side = "SELL" if trade.signal == "BUY" else "BUY"
        result     = place_order_raw(symbol, close_side, position_units)
        fill_price = result.get("fill_price", 0) or get_ticker_price(symbol)

        entry = trade.entry_price or fill_price
        if trade.signal == "BUY":
            pnl = (fill_price - entry) * position_units
        else:
            pnl = (entry - fill_price) * position_units

        trade.pnl       = round(pnl, 6)
        trade.outcome   = "WIN" if pnl > 0 else "LOSS"
        trade.closed_at = datetime.utcnow()
        db.commit()
        print(f"[executor] closed {symbol} @ {fill_price:.6f} pnl=${pnl:.4f} → {trade.outcome}")
        return {"success": True, "fill_price": fill_price, "pnl": pnl}
    except Exception as e:
        print(f"[executor] close_position error: {e}")
        return {"success": False, "error": str(e)}
    finally:
        db.close()