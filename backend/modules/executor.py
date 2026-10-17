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


# ══════════════════════════════════════════════════════════════════════════════
#  SILVER BULLET CRYPTO SIZING
#
#  BTC/ETH quantity on Binance is in BASE-ASSET units on a step grid — there is
#  no "lot". It therefore does NOT share the Capital.com contract table in
#  modules/forex_executor.py, and this section deliberately reuses the same
#  confidence tiers by importing them rather than restating them, so the two
#  venues cannot drift apart on how much a given score is worth.
#
#  This is additive: the SMC path above still calls calculate_risk_with_compounding
#  exactly as before.
# ══════════════════════════════════════════════════════════════════════════════

# Crypto has no lot, so the size grid is the exchange's step size. These are the
# conservative fallbacks used only when the live rules cannot be fetched.
_CRYPTO_FALLBACK_STEP = {"BTCUSDT": 0.001, "ETHUSDT": 0.001}
_CRYPTO_FALLBACK_MIN_NOTIONAL = 5.0


def crypto_step_and_min(symbol: str) -> tuple:
    """
    (step, min_notional) for a crypto symbol, preferring the exchange's rules.

    Falls back to KNOWN_RULES when the exchange is unreachable, so sizing still
    produces a valid grid-aligned quantity rather than a rejected order.
    """
    sym_clean = (symbol or "").upper().replace("/", "")
    try:
        from modules.market_data import get_lot_size_rules
        live = get_lot_size_rules(symbol)
        step = float(live.get("step_size") or 0) or None
        min_notional = float(live.get("min_notional") or 0) or None
        if step:
            return step, (min_notional or _CRYPTO_FALLBACK_MIN_NOTIONAL)
    except Exception:
        pass

    rule = KNOWN_RULES.get(sym_clean, {})
    return (rule.get("step") or _CRYPTO_FALLBACK_STEP.get(sym_clean, 0.001),
            rule.get("min_notional") or _CRYPTO_FALLBACK_MIN_NOTIONAL)


def calculate_silver_bullet_crypto_size(symbol: str, entry: float, stop_loss: float,
                                        confidence: float, balance: float,
                                        risk_pct: float = None) -> dict:
    """
    Position size in BASE-ASSET units for a Silver Bullet crypto entry.

    risk_quote = balance * risk_pct * tier * drawdown_guard
    qty        = risk_quote / |entry - stop_loss|

    The confidence tier and the drawdown guard come from
    `forex_executor.effective_size_multiplier`, so a 93 scores the same
    fraction of risk on BTC as it does on EURUSD. The result is snapped DOWN to
    the exchange's step grid and refused when it is below the exchange's
    minimum notional, because a sub-minimum order is rejected by Binance and
    silently opening a larger one would exceed the risk the caller asked for.

    Returns {ok, qty, reason, risk_quote, risk_pct, multiplier, notional, step}.
    """
    out = {"ok": False, "qty": 0.0, "reason": None, "risk_quote": 0.0,
           "risk_pct": 0.0, "multiplier": 0.0, "notional": 0.0, "step": 0.0}
    try:
        from modules.forex_executor import effective_size_multiplier
        from config import MAX_RISK_PCT

        entry = float(entry)
        stop_loss = float(stop_loss)
        balance = float(balance)

        if not all(math.isfinite(v) for v in (entry, stop_loss, balance)):
            out["reason"] = "non-finite input"
            return out
        if entry <= 0 or balance <= 0:
            out["reason"] = "non-positive price or balance"
            return out

        risk_distance = abs(entry - stop_loss)
        if risk_distance <= 0:
            out["reason"] = "zero stop distance"
            return out

        base_pct = float(risk_pct) if risk_pct is not None else float(MAX_RISK_PCT)

        mult, detail = effective_size_multiplier(confidence, balance)
        out["multiplier"] = mult
        if mult <= 0:
            out["reason"] = detail.get("reason") or "size multiplier is zero"
            return out

        risk_quote = balance * base_pct * mult
        out["risk_quote"] = round(risk_quote, 4)
        out["risk_pct"] = round(base_pct * mult, 6)

        raw_qty = risk_quote / risk_distance

        step, min_notional = crypto_step_and_min(symbol)
        out["step"] = step
        qty = _round_step(raw_qty, step)

        if qty <= 0:
            out["reason"] = (f"risk ${risk_quote:.2f} over a {risk_distance:g} stop "
                             f"is below the {step} step")
            return out

        notional = qty * entry
        out["notional"] = round(notional, 4)
        if notional < min_notional:
            out["reason"] = (f"notional ${notional:.2f} below the exchange "
                             f"minimum ${min_notional:.2f}")
            return out

        out["qty"] = qty
        out["ok"] = True
        return out

    except Exception as e:
        out["reason"] = f"sizing error: {e}"
        return out


def place_order(symbol: str, signal: str, position_units: float,
                stop_loss: float, take_profit: float, confidence: float,
                strategy: str = None) -> dict:
    """
    Open a Binance position.

    `strategy` identifies the caller and is REQUIRED to be
    `STRATEGY_SILVER_BULLET` for an order to be sent. It defaults to None, which
    is DENIED, so a caller written before the lock existed cannot submit by
    omission — see `modules.strategy_guard`.

    The guard is here, in the function that actually sends the exchange order,
    rather than at each caller: gating the callers would leave the next caller
    someone adds free to submit.
    """
    from modules.strategy_guard import STRATEGY_SILVER_BULLET, order_source_allowed

    allowed, why = order_source_allowed(strategy)
    if not allowed:
        print(f"[executor] order REFUSED for {symbol}: {why}")
        return {"success": False, "error": f"entry blocked: {why}",
                "blocked": True, "strategy": strategy}

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

        # Fix quantity precision — use the exchange's authoritative step size
        sym_clean = symbol.replace("/", "")
        try:
            from modules.market_data import get_lot_size_rules
            live = get_lot_size_rules(symbol)
            step = live.get("step_size", 0.001)
            min_notional = live.get("min_notional", 5.0)
        except Exception:
            step = KNOWN_RULES.get(sym_clean, {"step": 0.001})["step"]
            min_notional = 5.0

        qty = risk["position_size_units"]
        qty = _round_step(qty, step)

        # Ensure minimum notional
        if qty * price < min_notional:
            qty = math.ceil(min_notional / price / step) * step
            qty = _round_step(qty, step)

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
