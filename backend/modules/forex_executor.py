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
    if s.startswith("XAU") or s.startswith("XAG"):
        return 0.01          # metals: 1 pip = $0.01
    if s.endswith("JPY"):
        return 0.01          # JPY pairs: 1 pip = 0.01
    return 0.0001            # standard FX: 1 pip = 0.0001


def _pip_value_per_lot(symbol: str) -> float:
    """
    USD value of 1 pip for 1 standard lot.
    EURUSD = $10, JPY pairs ≈ $7, gold = $1, silver = $50.
    """
    s = symbol.upper().replace("/", "")
    if s.startswith("XAU"):
        return 1.0
    if s.startswith("XAG"):
        return 50.0
    if s.endswith("JPY"):
        return 7.0
    return 10.0


def _contract_size(symbol: str) -> float:
    """
    Units of the instrument in 1 standard lot.

    Capital.com's order `size` field is in UNITS, not lots, so a risk-based
    lot figure must be multiplied by this before it is sent. Sending lots
    directly produces 'error.invalid.size.minvalue'.
    """
    s = symbol.upper().replace("/", "")
    if s.startswith("XAU"):
        return 100.0         # 1 lot = 100 troy oz
    if s.startswith("XAG"):
        return 5000.0        # 1 lot = 5,000 troy oz
    return 100000.0          # standard FX lot = 100,000 units of base


# ── Position sizing ───────────────────────────────────────────────────────────

def calculate_position_size(symbol: str, entry: float, sl: float,
                            confidence: float, balance: float) -> float:
    """
    Return a Capital.com order size in UNITS (not lots).

    risk_pct    = forex_risk_pct(balance)  — scales down for small accounts
    risk_amount = balance * risk_pct
    risk_pips   = |entry - sl| / pip_size
    lots        = risk_amount / (risk_pips * pip_value_per_lot)
    size        = lots * contract_size

    The result is snapped to the instrument's minDealSize / minSizeIncrement
    from Capital.com's dealing rules, because the broker rejects anything
    smaller than its minimum. On tight stops the minimum can imply more risk
    than the configured target — that is logged so it is never silent.
    """
    try:
        from config import (forex_risk_pct, FOREX_MIN_TRADEABLE_BALANCE,
                            FOREX_MAX_IMPLIED_RISK_PCT)
        from modules.market_data_forex import get_dealing_rules

        if balance <= 0:
            logger.warning(f"[capital] {symbol} no balance available — skipping")
            return 0.0

        if balance < FOREX_MIN_TRADEABLE_BALANCE:
            logger.warning(f"[capital] {symbol} balance ${balance:.2f} below the "
                           f"${FOREX_MIN_TRADEABLE_BALANCE:.0f} minimum — skipping")
            return 0.0

        risk_pct = forex_risk_pct(balance)
        risk_amount = balance * risk_pct

        pip = _pip_size(symbol)
        pvpl = _pip_value_per_lot(symbol)
        contract = _contract_size(symbol)

        risk_pips = abs(entry - sl) / pip
        if risk_pips < 1:
            logger.warning(f"[capital] {symbol} stop too tight ({risk_pips:.2f} pips)")
            return 0.0

        lots = risk_amount / (risk_pips * pvpl)

        # Confidence multiplier
        if confidence >= 95:
            lots *= 2.0
        elif confidence >= 90:
            lots *= 1.5
        elif confidence >= 85:
            lots *= 1.0

        size = lots * contract

        # ── Respect the broker's dealing rules ───────────────────────────────
        rules = get_dealing_rules(symbol)
        min_size = rules.get("min_deal_size") or 0.0
        increment = rules.get("min_increment") or 0.0
        max_size = rules.get("max_deal_size") or 0.0

        if increment > 0:
            size = round(size / increment) * increment
            size = round(size, 6)
        else:
            size = round(size, 4)

        if min_size > 0 and size < min_size:
            implied = (min_size / contract) * risk_pips * pvpl
            logger.warning(
                f"[capital] {symbol} risk-based size {size} below broker minimum "
                f"{min_size} — raising to minimum (implied risk ${implied:.2f} vs "
                f"target ${risk_amount:.2f})"
            )
            size = min_size

        if max_size > 0 and size > max_size:
            logger.warning(f"[capital] {symbol} size {size} capped at broker max {max_size}")
            size = max_size

        if size <= 0:
            logger.warning(f"[capital] {symbol} computed size is zero — skipping")
            return 0.0

        # ── Final risk ceiling ───────────────────────────────────────────────
        # The broker minimum can force a position far larger than the target
        # risk. Refuse the trade rather than open something oversized.
        implied_risk = (size / contract) * risk_pips * pvpl
        implied_pct = implied_risk / balance if balance > 0 else 1.0
        if implied_pct > FOREX_MAX_IMPLIED_RISK_PCT:
            logger.warning(
                f"[capital] {symbol} skipped — broker minimum size {size} implies "
                f"${implied_risk:.2f} risk ({implied_pct*100:.1f}% of ${balance:.2f}), "
                f"above the {FOREX_MAX_IMPLIED_RISK_PCT*100:.0f}% ceiling"
            )
            return 0.0

        logger.info(f"[capital] {symbol} size: {size} units "
                    f"(={lots:.4f} lots, risk=${implied_risk:.2f} "
                    f"@{risk_pct*100:.1f}% target, stop={risk_pips:.1f}pips "
                    f"conf={confidence}% min={min_size} inc={increment})")
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
                tp1=signal_data.get("tp1"),
                tp2=signal_data.get("tp2", tp),
                entry_type=signal_data.get("entry_type"),
                partial_tp_hit=False,
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
            if trade.tp1:
                logger.info(f"[forex] ENTRY {signal} {symbol} @ {trade.entry_price:.5f} | "
                            f"{signal_data.get('entry_type', '?')} | conf={confidence:.0f}% | "
                            f"SL={sl:.5f} | TP1={trade.tp1:.5f} | TP2={tp:.5f}")
            else:
                logger.info(f"[capital] trade recorded — {signal} {symbol} id={trade.id} "
                            f"deal={result.get('deal_id')}")
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

def close_forex_position(deal_id: str, trade_id: int, pnl: float = None) -> Dict:
    """
    Close a Capital.com position and update the ForexTrade row.

    When `pnl` is not supplied the realised P&L is read from the broker
    before closing, so manual closes are recorded with the real figure
    rather than defaulting to zero.

    Returns {success, pnl, symbol, error}.
    """
    try:
        from modules.market_data_forex import close_position

        result = close_position(deal_id)
        if not result.get("success"):
            logger.error(f"[capital] close failed for {deal_id}: {result.get('error')}")
            return {"success": False, "error": result.get("error", "close failed")}

        realised = result.get("pnl") if pnl is None else pnl
        realised = float(realised or 0.0)

        db = SessionLocal()
        try:
            trade = db.query(ForexTrade).filter(ForexTrade.id == trade_id).first()
            if trade:
                trade.outcome = "WIN" if realised >= 0 else "LOSS"
                trade.pnl = round(realised, 4)
                trade.closed_at = datetime.utcnow()
                db.commit()
                logger.info(f"[forex] CLOSED {trade.symbol} {trade.signal} — "
                            f"P&L ${realised:+.2f} (trade id={trade_id})")
                result["symbol"] = result.get("symbol") or trade.symbol
        except Exception as e:
            logger.error(f"[capital] db update error: {e}")
            db.rollback()
        finally:
            db.close()

        result["pnl"] = round(realised, 2)
        return result

    except Exception as e:
        logger.error(f"[capital] close_forex_position error: {e}")
        return {"success": False, "error": str(e)}


def close_all_forex_positions() -> Dict:
    """
    Close every open Capital.com position and settle the matching rows.

    Returns {success, closed, failed, total_pnl, results}.
    """
    results = []
    total_pnl = 0.0
    failed = 0

    db = SessionLocal()
    try:
        open_trades = db.query(ForexTrade).filter(ForexTrade.outcome == "OPEN").all()
        pending = [
            {"id": t.id, "symbol": t.symbol, "deal_id": t.metaapi_position_id}
            for t in open_trades
        ]
    finally:
        db.close()

    if not pending:
        return {"success": True, "closed": 0, "failed": 0,
                "total_pnl": 0.0, "results": []}

    for item in pending:
        if not item["deal_id"]:
            # Never reached the broker — just settle the row locally
            _settle_local(item["id"], 0.0)
            results.append({"symbol": item["symbol"], "success": True, "pnl": 0.0})
            continue

        res = close_forex_position(item["deal_id"], item["id"])
        if res.get("success"):
            pnl = float(res.get("pnl") or 0.0)
            total_pnl += pnl
            results.append({"symbol": item["symbol"], "success": True, "pnl": pnl})
        else:
            failed += 1
            results.append({"symbol": item["symbol"], "success": False,
                            "error": res.get("error")})

    logger.info(f"[forex] CLOSE ALL — {len(pending) - failed} closed, "
                f"{failed} failed, total P&L ${total_pnl:+.2f}")

    return {
        "success": failed == 0,
        "closed": len(pending) - failed,
        "failed": failed,
        "total_pnl": round(total_pnl, 2),
        "results": results,
    }


def _settle_local(trade_id: int, pnl: float) -> None:
    """Mark a trade closed without a broker call (no deal id recorded)."""
    db = SessionLocal()
    try:
        trade = db.query(ForexTrade).filter(ForexTrade.id == trade_id).first()
        if trade:
            trade.outcome = "WIN" if pnl >= 0 else "LOSS"
            trade.pnl = round(float(pnl), 4)
            trade.closed_at = datetime.utcnow()
            db.commit()
    except Exception as e:
        logger.error(f"[capital] local settle error: {e}")
        db.rollback()
    finally:
        db.close()
