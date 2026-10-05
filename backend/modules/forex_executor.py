"""
backend/modules/forex_executor.py
Capital.com REST order execution for Forex/Metals.

Pure synchronous — no asyncio. Position sizing is in Capital.com "lots".
"""
import logging
from datetime import datetime
from typing import Dict

from database import SessionLocal
from models import ForexTrade

logger = logging.getLogger(__name__)


# ── Pip / lot helpers ─────────────────────────────────────────────────────────

def _pip_size(symbol: str) -> float:
    """Pip size for a symbol."""
    s = symbol.upper().replace("/", "")
    if s.startswith("XAU"):
        return 0.01          # gold: 1 pip = $0.01
    if s.endswith("JPY"):
        return 0.01          # JPY pairs: 1 pip = 0.01
    return 0.0001            # standard FX: 1 pip = 0.0001


def _pip_value_per_lot(symbol: str) -> float:
    """
    USD value of 1 pip for 1 standard lot.
    GOLD = $1, EURUSD = $10, JPY pairs ≈ $7.
    """
    s = symbol.upper().replace("/", "")
    if s.startswith("XAU"):
        return 1.0
    if s.endswith("JPY"):
        return 7.0
    return 10.0


# ── Position sizing ───────────────────────────────────────────────────────────

def calculate_position_size(symbol: str, entry: float, sl: float,
                            confidence: float, balance: float) -> float:
    """
    Return Capital.com lot size (2 dp, min 0.01, max 10.0).

    risk_amount = balance * FOREX_MAX_RISK_PCT
    risk_pips   = |entry - sl| / pip_size
    size        = risk_amount / (risk_pips * pip_value_per_lot)
    """
    try:
        from config import FOREX_MAX_RISK_PCT

        if balance <= 0:
            balance = 10000.0

        risk_amount = balance * FOREX_MAX_RISK_PCT

        pip = _pip_size(symbol)
        pvpl = _pip_value_per_lot(symbol)

        risk_pips = abs(entry - sl) / pip
        if risk_pips < 1:
            logger.warning(f"[capital] {symbol} stop too tight ({risk_pips:.2f} pips)")
            return 0.0

        size = risk_amount / (risk_pips * pvpl)

        # Confidence multiplier
        if confidence >= 95:
            size *= 2.0
        elif confidence >= 90:
            size *= 1.5
        elif confidence >= 85:
            size *= 1.0

        size = round(size, 2)
        size = max(0.01, min(size, 10.0))

        logger.info(f"[capital] {symbol} size: {size} lots "
                    f"(risk=${risk_amount:.2f} stop={risk_pips:.1f}pips conf={confidence}%)")
        return size

    except Exception as e:
        logger.error(f"[capital] position size error {symbol}: {e}")
        return 0.0


# ── Place order ───────────────────────────────────────────────────────────────

def place_forex_order(signal_data: Dict, kronos_bias: Dict) -> Dict:
    """
    Open a Capital.com position and record it in the ForexTrade table.

    signal_data keys: symbol, signal, entry_price, stop_loss, take_profit,
                      confidence, crt_setup, pdh, pdl
    """
    try:
        from modules.market_data_forex import place_order, get_capital_balance

        symbol     = signal_data["symbol"]
        signal     = signal_data["signal"]          # BUY / SELL
        entry      = signal_data["entry_price"]
        sl         = signal_data["stop_loss"]
        tp         = signal_data["take_profit"]
        confidence = signal_data["confidence"]

        bal = get_capital_balance()
        balance = bal.get("balance", 0) or 10000.0

        size = calculate_position_size(symbol, entry, sl, confidence, balance)
        if size <= 0:
            return {"success": False, "error": "Invalid position size"}

        result = place_order(symbol, signal, size, sl, tp)
        if not result.get("success"):
            return {"success": False, "error": result.get("error", "order failed")}

        # Record in DB (metaapi_position_id stores the Capital.com dealId)
        db = SessionLocal()
        try:
            trade = ForexTrade(
                symbol=symbol,
                signal=signal,
                confidence=confidence,
                entry_price=result.get("fill_price", entry),
                stop_loss=sl,
                take_profit=tp,
                lots=size,
                kronos_bias=(kronos_bias or {}).get("bias", "NEUTRAL"),
                crt_setup=signal_data.get("crt_setup", "NONE"),
                pdh=signal_data.get("pdh"),
                pdl=signal_data.get("pdl"),
                crt_timeframe=signal_data.get("crt_timeframe"),
                confirm_timeframe=signal_data.get("confirm_timeframe"),
                entry_timeframe=signal_data.get("entry_timeframe"),
                poi=signal_data.get("poi"),
                metaapi_position_id=result.get("deal_id"),
                outcome="OPEN",
            )
            db.add(trade)
            db.commit()
            db.refresh(trade)
            logger.info(f"[capital] trade recorded — {signal} {symbol} id={trade.id} "
                        f"deal={result.get('deal_id')} "
                        f"[{signal_data.get('crt_timeframe')}→"
                        f"{signal_data.get('confirm_timeframe')}→"
                        f"{signal_data.get('entry_timeframe')}]")
            result["trade_id"] = trade.id
        except Exception as e:
            logger.error(f"[capital] db record error: {e}")
            db.rollback()
        finally:
            db.close()

        return result

    except Exception as e:
        logger.error(f"[capital] place_forex_order error: {e}")
        return {"success": False, "error": str(e)}


# ── Close position ────────────────────────────────────────────────────────────

def close_forex_position(deal_id: str, trade_id: int, pnl: float = 0.0) -> bool:
    """Close a Capital.com position and update the ForexTrade row."""
    try:
        from modules.market_data_forex import close_position

        result = close_position(deal_id)
        if not result.get("success"):
            logger.error(f"[capital] close failed for {deal_id}: {result.get('error')}")
            return False

        db = SessionLocal()
        try:
            trade = db.query(ForexTrade).filter(ForexTrade.id == trade_id).first()
            if trade:
                trade.outcome = "WIN" if pnl >= 0 else "LOSS"
                trade.pnl = round(float(pnl), 4)
                trade.closed_at = datetime.utcnow()
                db.commit()
                logger.info(f"[capital] trade closed — id={trade_id} pnl=${pnl:.2f}")
        except Exception as e:
            logger.error(f"[capital] db update error: {e}")
            db.rollback()
        finally:
            db.close()

        return True

    except Exception as e:
        logger.error(f"[capital] close_forex_position error: {e}")
        return False
