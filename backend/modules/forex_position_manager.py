"""
backend/modules/forex_position_manager.py
Capital.com REST position monitoring for Forex/Metals.

Pure synchronous — no asyncio.
"""
import logging
from datetime import datetime
from typing import List, Dict, Tuple

from database import SessionLocal
from models import ForexTrade

logger = logging.getLogger(__name__)


# ── Sync open positions with DB ───────────────────────────────────────────────

def check_forex_positions() -> None:
    """
    Fetch open Capital.com positions and reconcile with the ForexTrade table.

    Also applies the refined-CRT partial take-profit rule: once price reaches
    TP1, close 50% of the position, move the stop to breakeven, and mark the
    trade as partially closed.

    Trades genuinely no longer open on the broker (SL/TP hit) are marked
    CLOSED_EXTERNAL. Reconciliation is skipped entirely when the broker call
    fails, because an empty list is otherwise indistinguishable from "the
    position is gone" and would close live trades in the database.
    """
    try:
        from modules.market_data_forex import get_open_positions, get_session

        # A rate-limit pause or an unreachable API must not be read as
        # "no positions" — that would mark every live trade closed.
        pause = get_session().rate_limit_remaining()
        if pause > 0:
            logger.info(f"[capital] reconciliation skipped — rate-limit pause "
                        f"({pause:.0f}s)")
            return

        positions = get_open_positions()
        if positions is None:
            logger.warning("[capital] reconciliation skipped — position fetch failed")
            return

        live_ids = {str(p["id"]) for p in positions if p.get("id")}

        db = SessionLocal()
        try:
            open_trades = db.query(ForexTrade).filter(ForexTrade.outcome == "OPEN").all()

            for trade in open_trades:
                did = str(trade.metaapi_position_id or "")

                if not did:
                    # Never recorded a broker deal id — cannot reconcile safely.
                    continue

                if did not in live_ids:
                    logger.info(f"[capital] trade {trade.id} ({trade.symbol}) "
                                f"no longer open at broker — marking closed")
                    trade.outcome = "CLOSED_EXTERNAL"
                    trade.closed_at = datetime.utcnow()
                    db.commit()
                    continue

                _check_partial_tp(trade, db)

            for p in positions:
                logger.debug(f"[capital] {p['symbol']} deal {p['id']} "
                             f"uPL=${p['unrealized_pnl']:.2f}")

        except Exception as e:
            logger.error(f"[capital] position sync error: {e}")
            db.rollback()
        finally:
            db.close()

    except Exception as e:
        logger.error(f"[capital] check_forex_positions error: {e}")


def _check_partial_tp(trade: ForexTrade, db) -> None:
    """
    Close 50% of the position and move the stop to breakeven once price
    reaches TP1. Runs at most once per trade (guarded by partial_tp_hit).
    """
    if trade.partial_tp_hit:
        return
    if trade.tp1 is None or trade.lots is None or not trade.lots:
        return

    try:
        from modules.market_data_forex import get_current_price, close_position, place_order

        price = get_current_price(trade.symbol)
        if not price:
            return

        hit = (price >= trade.tp1) if trade.signal == "BUY" else (price <= trade.tp1)
        if not hit:
            return

        half = round(float(trade.lots) / 2.0, 2)
        if half <= 0:
            half = round(float(trade.lots), 2)

        # Reduce the position: close it and reopen the remaining half at
        # breakeven with the same final target.
        close_result = close_position(trade.metaapi_position_id)
        if not close_result.get("success"):
            logger.error(f"[capital] partial close failed {trade.symbol}: "
                         f"{close_result.get('error')}")
            return

        entry = float(trade.entry_price)
        tp2 = float(trade.tp2 or trade.take_profit or trade.tp1)

        reopen = place_order(trade.symbol, trade.signal, half, entry, tp2)
        if not reopen.get("success"):
            logger.error(f"[capital] partial re-open failed {trade.symbol}: "
                         f"{reopen.get('error')}")
            trade.outcome = "CLOSED_EXTERNAL"
            trade.closed_at = datetime.utcnow()
            db.commit()
            return

        trade.lots = half
        trade.stop_loss = entry
        trade.partial_tp_hit = True
        trade.metaapi_position_id = reopen.get("deal_id")
        db.commit()

        logger.info(f"[forex] PARTIAL TP HIT — {trade.symbol} 50% closed @ {price:.5f}, "
                    f"SL moved to breakeven {entry:.5f}")

    except Exception as e:
        logger.error(f"[capital] partial tp error {trade.symbol}: {e}")
        db.rollback()


# ── Summary ───────────────────────────────────────────────────────────────────

def get_forex_position_summary() -> Dict:
    """
    Returns: open_count, open_positions, total_pnl, closed_trades,
             wins, losses, win_rate, balance, unrealized
    """
    db = SessionLocal()
    try:
        from modules.market_data_forex import get_open_positions, get_capital_balance

        open_trades = db.query(ForexTrade).filter(ForexTrade.outcome == "OPEN").all()
        closed_trades = db.query(ForexTrade).filter(
            ForexTrade.outcome.in_(["WIN", "LOSS"])
        ).all()

        positions = get_open_positions()
        # None means the broker call failed — the dashboard must show a
        # clear "unavailable" state rather than an empty (but healthy) list.
        if positions is None:
            logger.warning("[capital] position summary — broker fetch failed")
            return {
                "open_count": 0, "open_positions": [], "total_pnl": 0,
                "closed_trades": 0, "wins": 0, "losses": 0, "win_rate": 0,
                "balance": 0.0, "unrealized": 0.0, "connected": False,
                "stale": True,
            }

        pos_map = {str(p["id"]): p for p in positions if p.get("id")}

        open_positions = []
        for trade in open_trades:
            p = pos_map.get(str(trade.metaapi_position_id or ""))
            if p:
                entry = trade.entry_price or 0.0
                current = p.get("current_price") or 0.0
                pnl = round(p.get("unrealized_pnl", 0), 2)

                # Percentage move in the trade's direction, and progress
                # from entry towards the final target.
                if entry:
                    move = (current - entry) / entry * 100
                    pnl_pct = move if trade.signal == "BUY" else -move
                else:
                    pnl_pct = 0.0

                target = trade.tp2 or trade.take_profit or 0.0
                progress = 0.0
                if target and entry and target != entry:
                    progress = (current - entry) / (target - entry) * 100
                    progress = max(0.0, min(100.0, progress))

                open_positions.append({
                    "id":          trade.id,
                    "symbol":      trade.symbol,
                    "signal":      trade.signal,
                    "entry":       entry,
                    "current":     current,
                    "sl":          trade.stop_loss,
                    "tp":          trade.take_profit,
                    "tp1":         trade.tp1,
                    "tp2":         trade.tp2,
                    "entry_type":  trade.entry_type,
                    "partial_tp_hit": bool(trade.partial_tp_hit),
                    "pnl":         pnl,
                    "pnl_pct":     round(pnl_pct, 3),
                    "progress":    round(progress, 1),
                    "risk_reward": round(abs((target - entry) / (entry - trade.stop_loss)), 2)
                                   if trade.stop_loss and entry and entry != trade.stop_loss else 0.0,
                    "size":        p.get("size"),
                    "lots":        trade.lots,
                    "confidence":  trade.confidence,
                    "kronos_bias": trade.kronos_bias,
                    "crt_setup":   trade.crt_setup,
                    "opened_at":   trade.created_at.isoformat() if trade.created_at else None,
                })

        total_pnl = sum(t.pnl for t in closed_trades if t.pnl is not None)
        wins = len([t for t in closed_trades if t.outcome == "WIN"])
        losses = len([t for t in closed_trades if t.outcome == "LOSS"])
        win_rate = (wins / (wins + losses) * 100) if (wins + losses) > 0 else 0

        bal = get_capital_balance()

        return {
            "open_count":     len(open_positions),
            "open_positions": open_positions,
            "total_pnl":      round(total_pnl, 2),
            "closed_trades":  wins + losses,
            "wins":           wins,
            "losses":         losses,
            "win_rate":       round(win_rate, 1),
            "balance":        bal.get("balance", 0.0),
            "unrealized":     bal.get("profit_loss", 0.0),
            "connected":      bal.get("connected", False),
        }

    except Exception as e:
        logger.error(f"[capital] summary error: {e}")
        return {
            "open_count": 0, "open_positions": [], "total_pnl": 0,
            "closed_trades": 0, "wins": 0, "losses": 0, "win_rate": 0,
            "balance": 0.0, "unrealized": 0.0, "connected": False,
            "stale": True,
        }
    finally:
        db.close()


# ── Trade guards ──────────────────────────────────────────────────────────────

def forex_daily_loss_check() -> Tuple[bool, str]:
    """
    True when today's realised forex loss has hit FOREX_DAILY_LOSS_LIMIT.

    Protects the account from a losing streak. Without this the forex side
    would keep opening trades no matter how much the day had already lost.
    """
    try:
        from config import FOREX_DAILY_LOSS_LIMIT

        db = SessionLocal()
        try:
            since = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
            closed = db.query(ForexTrade).filter(
                ForexTrade.outcome.in_(["WIN", "LOSS"]),
                ForexTrade.closed_at >= since,
            ).all()

            if not closed:
                return True, "OK"

            pnl = sum(t.pnl or 0.0 for t in closed)

            from modules.market_data_forex import get_capital_balance
            balance = get_capital_balance().get("balance", 0.0) or 0.0
            if balance <= 0:
                return True, "OK"

            if pnl < 0 and abs(pnl) >= balance * FOREX_DAILY_LOSS_LIMIT:
                return False, (f"daily forex loss limit hit "
                               f"(${pnl:.2f} of ${balance:.2f} balance)")
            return True, "OK"
        finally:
            db.close()

    except Exception as e:
        logger.error(f"[capital] daily loss check error: {e}")
        return True, "OK"


def can_open_forex_trade(symbol: str) -> Tuple[bool, str]:
    """Check max-trades limit and whether this symbol already has an open trade."""
    try:
        from config import FOREX_MAX_TRADES

        allowed, reason = forex_daily_loss_check()
        if not allowed:
            return False, reason

        db = SessionLocal()
        try:
            open_count = db.query(ForexTrade).filter(ForexTrade.outcome == "OPEN").count()
            if open_count >= FOREX_MAX_TRADES:
                return False, f"Max forex trades reached ({open_count}/{FOREX_MAX_TRADES})"

            existing = db.query(ForexTrade).filter(
                ForexTrade.symbol == symbol,
                ForexTrade.outcome == "OPEN",
            ).first()
            if existing:
                return False, f"{symbol} already has an open position"

            return True, "OK"
        finally:
            db.close()

    except Exception as e:
        logger.error(f"[capital] can_open check error: {e}")
        return False, "Check failed"


# Tracks which (symbol, reason) pairs we've already logged, so the 60s entry
# check doesn't spam the same "blocked" line every cycle.
_forex_block_log_cache: dict = {}


def forex_block_log_once(symbol: str, reason: str) -> bool:
    """Return True only the first time we see this symbol+reason combination."""
    key = f"{symbol}:{reason}"
    if _forex_block_log_cache.get(symbol) == key:
        return False
    _forex_block_log_cache[symbol] = key
    return True


# ── History ───────────────────────────────────────────────────────────────────

def get_forex_trade_history(limit: int = 50) -> List[Dict]:
    db = SessionLocal()
    try:
        trades = db.query(ForexTrade).order_by(ForexTrade.created_at.desc()).limit(limit).all()
        return [{
            "id":          t.id,
            "symbol":      t.symbol,
            "signal":      t.signal,
            "confidence":  t.confidence,
            "entry":       t.entry_price,
            "sl":          t.stop_loss,
            "tp":          t.take_profit,
            "tp1":         t.tp1,
            "tp2":         t.tp2,
            "entry_type":  t.entry_type,
            "partial_tp_hit": bool(t.partial_tp_hit),
            "lots":        t.lots,
            "kronos_bias": t.kronos_bias,
            "crt_setup":   t.crt_setup,
            "crt_timeframe":     t.crt_timeframe,
            "confirm_timeframe": t.confirm_timeframe,
            "entry_timeframe":   t.entry_timeframe,
            "poi":               t.poi,
            "pdh":         t.pdh,
            "pdl":         t.pdl,
            "outcome":     t.outcome,
            "pnl":         t.pnl,
            "opened":      t.created_at.isoformat() if t.created_at else None,
            "closed":      t.closed_at.isoformat() if t.closed_at else None,
        } for t in trades]
    except Exception as e:
        logger.error(f"[capital] history error: {e}")
        return []
    finally:
        db.close()
