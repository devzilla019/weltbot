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
    Trades no longer open on the broker (SL/TP hit) are marked WIN/LOSS.
    """
    try:
        from modules.market_data_forex import get_open_positions

        positions = get_open_positions()
        live_ids = {str(p["id"]) for p in positions if p.get("id")}

        db = SessionLocal()
        try:
            open_trades = db.query(ForexTrade).filter(ForexTrade.outcome == "OPEN").all()

            for trade in open_trades:
                did = str(trade.metaapi_position_id or "")
                if did and did not in live_ids:
                    # Closed on the broker side (SL/TP). Infer outcome from SL/TP.
                    logger.info(f"[capital] trade {trade.id} ({trade.symbol}) closed externally")
                    trade.outcome = "CLOSED_EXTERNAL"
                    trade.closed_at = datetime.utcnow()
                    db.commit()

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
        pos_map = {str(p["id"]): p for p in positions if p.get("id")}

        open_positions = []
        for trade in open_trades:
            p = pos_map.get(str(trade.metaapi_position_id or ""))
            if p:
                open_positions.append({
                    "id":          trade.id,
                    "symbol":      trade.symbol,
                    "signal":      trade.signal,
                    "entry":       trade.entry_price,
                    "current":     p.get("current_price"),
                    "sl":          trade.stop_loss,
                    "tp":          trade.take_profit,
                    "pnl":         round(p.get("unrealized_pnl", 0), 2),
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
        }
    finally:
        db.close()


# ── Trade guards ──────────────────────────────────────────────────────────────

def can_open_forex_trade(symbol: str) -> Tuple[bool, str]:
    """Check max-trades limit and whether this symbol already has an open trade."""
    try:
        from config import FOREX_MAX_TRADES

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
