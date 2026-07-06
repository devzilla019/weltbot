"""
backend/modules/executor.py
Updated to use calculate_risk_with_compounding
and pass live balance to every trade calculation.
"""
import os
import math
from database import SessionLocal
from models import Trade
from datetime import datetime

KNOWN_RULES = {
    "BTCUSDT":  {"step": 0.001,  "min_notional": 5.0},
    "ETHUSDT":  {"step": 0.001,  "min_notional": 5.0},
    "BNBUSDT":  {"step": 0.01,   "min_notional": 5.0},
    "SOLUSDT":  {"step": 0.1,    "min_notional": 5.0},
    "XRPUSDT":  {"step": 1.0,    "min_notional": 5.0},
    "ADAUSDT":  {"step": 1.0,    "min_notional": 5.0},
    "DOGEUSDT": {"step": 1.0,    "min_notional": 5.0},
    "AVAXUSDT": {"step": 0.1,    "min_notional": 5.0},
    "LINKUSDT": {"step": 0.01,   "min_notional": 5.0},
    "UNIUSDT":  {"step": 0.1,    "min_notional": 5.0},
    "LTCUSDT":  {"step": 0.01,   "min_notional": 5.0},
    "ATOMUSDT": {"step": 0.01,   "min_notional": 5.0},
    "NEARUSDT": {"step": 0.1,    "min_notional": 5.0},
    "DOTUSDT":  {"step": 0.1,    "min_notional": 5.0},
    "AAVEUSDT": {"step": 0.01,   "min_notional": 5.0},
}

def _round_step(qty: float, step: float) -> float:
    if step <= 0:
        return qty
    decimals = max(0, int(round(-math.log10(step))))
    return round(math.floor(qty / step) * step, decimals)


def place_order(symbol: str, signal: str, position_units: float,
                stop_loss: float, take_profit: float, confidence: float) -> dict:
    db = SessionLocal()
    try:
        from modules.market_data  import get_ticker_price, place_order_raw, set_leverage, get_balance
        from modules.risk_manager import calculate_risk_with_compounding, get_drawdown_guard
        from modules.news_monitor import check_news_blackout
        from config               import MIN_CONFIDENCE, HIGH_LEV_ASSETS

        # News blackout check
        try:
            blackout = check_news_blackout()
            if blackout.get("blackout"):
                return {"success": False, "error": f"News blackout: {blackout.get('reason')}"}
        except Exception:
            pass

        if confidence < MIN_CONFIDENCE:
            return {"success": False, "error": f"Confidence {confidence}% below minimum"}

        # Get LIVE balance for compounding
        balance = get_balance()
        if balance <= 0:
            balance = float(os.getenv("DEFAULT_PORTFOLIO", "5000"))

        price = get_ticker_price(symbol)
        if price <= 0:
            return {"success": False, "error": "Could not get price"}

        # Recalculate with live balance and Kelly
        from modules.signal_engine import compute_atr
        risk = calculate_risk_with_compounding(
            price=price, signal=signal, confidence=confidence,
            atr=0, balance=balance, symbol=symbol,
        )

        leverage = risk["leverage"]

        # Cap leverage for non-whitelisted assets
        if leverage == 100 and symbol not in HIGH_LEV_ASSETS:
            leverage = 50

        # Drawdown guard check
        guard = get_drawdown_guard(balance)
        if guard < 0.5:
            print(f"[executor] {symbol} — drawdown guard active ({guard*100:.0f}% size)")

        # Set leverage on exchange
        try:
            set_leverage(symbol, leverage)
            print(f"[executor] {symbol} conf={confidence}% → {leverage}x | risk={risk['risk_pct']:.1f}% of ${balance:.2f}")
        except Exception as e:
            print(f"[executor] leverage set error: {e}")

        # Fix quantity precision
        sym_clean = symbol.replace("/", "")
        rules     = KNOWN_RULES.get(sym_clean, {"step": 0.001, "min_notional": 5.0})
        qty       = risk["position_size_units"]
        qty       = _round_step(qty, rules["step"])

        # Ensure minimum notional
        if qty * price < rules["min_notional"]:
            qty = math.ceil(rules["min_notional"] / price / rules["step"]) * rules["step"]
            qty = _round_step(qty, rules["step"])

        if qty <= 0:
            return {"success": False, "error": f"Quantity too small: {qty}"}

        side = "BUY" if signal == "BUY" else "SELL"
        print(f"[executor] placing {side} {qty} {sym_clean} @ ${price} ({leverage}x)")

        result = place_order_raw(symbol, side, qty)
        if not result or not result.get("success"):
            err = result.get("error", "Unknown") if result else "No response"
            print(f"[executor] order failed {symbol}: {err}")
            return {"success": False, "error": err}

        fill_price = result.get("fill_price", price)

        # Store trade with risk info
        trade = Trade(
            asset            = symbol,
            signal           = signal,
            confidence       = confidence,
            entry_price      = fill_price,
            stop_loss        = stop_loss,
            take_profit      = take_profit,
            position_sz      = qty,
            risk_usd         = risk["risk_usd"],
            risk_reward      = risk["risk_reward"],
            outcome          = "OPEN",
            binance_order_id = result.get("order_id", ""),
            created_at       = datetime.utcnow(),
        )
        db.add(trade)
        db.commit()
        db.refresh(trade)

        print(f"[executor] ✓ {side} {qty} {symbol} @ ${fill_price} | "
              f"SL=${stop_loss} TP=${take_profit} | "
              f"risk=${risk['risk_usd']:.2f} ({risk['risk_pct']:.1f}%) | "
              f"balance=${balance:.2f}")

        return {
            "success":    True,
            "trade_id":   trade.id,
            "fill_price": fill_price,
            "leverage":   leverage,
            "qty":        qty,
            "risk_usd":   risk["risk_usd"],
        }

    except Exception as e:
        print(f"[executor] exception: {e}")
        return {"success": False, "error": str(e)}
    finally:
        db.close()


def close_position(asset: str, position_sz: float, trade_id: int) -> dict:
    """Close a position on exchange and mark in DB."""
    db = SessionLocal()
    try:
        from modules.market_data import get_ticker_price, place_order_raw
        trade = db.query(Trade).filter(Trade.id == trade_id).first()
        if not trade:
            return {"success": False, "error": "Trade not found"}

        current = get_ticker_price(asset)
        side    = "SELL" if trade.signal == "BUY" else "BUY"

        sym_clean = asset.replace("/", "")
        rules     = KNOWN_RULES.get(sym_clean, {"step": 0.001, "min_notional": 5.0})
        qty       = _round_step(position_sz, rules["step"])

        place_order_raw(asset, side, qty)

        if trade.signal == "BUY":
            pnl = (current - trade.entry_price) * position_sz
        else:
            pnl = (trade.entry_price - current) * position_sz

        trade.outcome   = "WIN" if pnl >= 0 else "LOSS"
        trade.pnl       = round(pnl, 4)
        trade.closed_at = datetime.utcnow()
        db.commit()

        try:
            from modules.risk_manager import update_compound_stats
            from modules.market_data  import get_balance
            update_compound_stats(won=(pnl >= 0), pnl=pnl, balance=get_balance())
        except Exception:
            pass

        return {"success": True, "pnl": round(pnl, 4)}
    except Exception as e:
        return {"success": False, "error": str(e)}
    finally:
        db.close()
