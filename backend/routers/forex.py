"""
backend/routers/forex.py
Forex/Metals API endpoints
"""
from fastapi import APIRouter, HTTPException
from typing import Dict, List
import logging
from datetime import datetime

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/forex", tags=["forex"])


def _forex_daily_risk() -> Dict:
    """
    Today's realised forex risk budget, for the dashboard panel.

    Returns the day's realised P&L, the loss limit, how much budget is left
    and whether new entries are currently halted.
    """
    try:
        from config import (FOREX_DAILY_LOSS_LIMIT, FOREX_MIN_TRADEABLE_BALANCE,
                            FOREX_MAX_IMPLIED_RISK_PCT, forex_risk_pct)
        from database import SessionLocal
        from models import ForexTrade
        from modules.market_data_forex import get_capital_balance

        balance = get_capital_balance().get("balance", 0.0) or 0.0

        db = SessionLocal()
        try:
            since = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)

            closed = db.query(ForexTrade).filter(
                ForexTrade.outcome.in_(["WIN", "LOSS"]),
                ForexTrade.closed_at >= since,
            ).all()

            realised = sum(t.pnl or 0.0 for t in closed)
            wins = len([t for t in closed if t.outcome == "WIN"])
            losses = len([t for t in closed if t.outcome == "LOSS"])

            open_count = db.query(ForexTrade).filter(ForexTrade.outcome == "OPEN").count()

            open_unrealised = sum(
                (t.pnl or 0.0) for t in
                db.query(ForexTrade).filter(ForexTrade.outcome == "OPEN").all()
            )
        finally:
            db.close()

        limit_amount = balance * FOREX_DAILY_LOSS_LIMIT
        loss_used = abs(min(0.0, realised))
        remaining = max(0.0, limit_amount - loss_used)
        halted = loss_used >= limit_amount and limit_amount > 0

        return {
            "balance":              round(balance, 2),
            "risk_pct":             round(forex_risk_pct(balance) * 100, 2),
            "risk_per_trade":       round(balance * forex_risk_pct(balance), 2),
            "daily_limit_pct":      round(FOREX_DAILY_LOSS_LIMIT * 100, 2),
            "daily_limit_amount":   round(limit_amount, 2),
            "realised_pnl":         round(realised, 2),
            "loss_used":            round(loss_used, 2),
            "remaining_budget":     round(remaining, 2),
            "remaining_pct":        round((remaining / limit_amount * 100) if limit_amount else 0.0, 1),
            "halted":               halted,
            "trades_today":         wins + losses,
            "wins_today":           wins,
            "losses_today":         losses,
            "open_positions":       open_count,
            "max_implied_risk_pct": round(FOREX_MAX_IMPLIED_RISK_PCT * 100, 2),
            "min_balance":          FOREX_MIN_TRADEABLE_BALANCE,
            "tradeable":            balance >= FOREX_MIN_TRADEABLE_BALANCE,
        }

    except Exception as e:
        logger.error(f"[forex-api] daily risk error: {e}")
        return {}


@router.get("/daily-risk")
def forex_daily_risk() -> Dict:
    """Today's forex risk budget: realised P&L vs the daily loss limit."""
    return _forex_daily_risk()


@router.get("/status")
def forex_status() -> Dict:
    """
    Get forex bot status and overview
    """
    try:
        from config import FOREX_ENABLED, FOREX_PAIRS
        from modules.forex_position_manager import get_forex_position_summary
        
        if not FOREX_ENABLED:
            return {
                'enabled': False,
                'message': 'Forex trading disabled'
            }
        
        position_summary = get_forex_position_summary()
        
        # Capital.com account balance (separate from crypto)
        account = None
        try:
            from modules.market_data_forex import get_capital_balance
            account = get_capital_balance()
        except Exception as e:
            logger.warning(f"[forex-api] account info unavailable: {e}")

        # Strategy state. The Kronos biases and CRT levels this endpoint used to
        # publish belonged to the retired stack; `silver_bullet` carries the H4
        # bias and volume profile that replaced them, for the same symbols.
        silver = _silver_bullet_state()
        biases = {
            symbol: {"h4_bias": rec.get("h4_bias"),
                     "strength": rec.get("strength"),
                     "bias": rec.get("h4_bias"),
                     "price_position": rec.get("price_position"),
                     "vp_bias": rec.get("vp_bias"),
                     "predicted_change_pct": 0}
            for symbol, rec in (silver.get("biases") or {}).items()
        }
        # The legacy key names are kept so an older frontend build keeps working,
        # but they now carry the Silver Bullet volume profile.
        levels = {
            symbol: (rec.get("vp_levels") or {})
            for symbol, rec in (silver.get("biases") or {}).items()
        }

        return {
            'enabled': True,
            'provider': 'capital.com',
            'strategy': 'SILVER_BULLET',
            'kronos_available': False,
            'pairs': FOREX_PAIRS,
            'biases': biases,
            'crt_levels': levels,
            'positions': position_summary,
            'account': account,
            'daily_risk': _forex_daily_risk(),
            'silver_bullet': silver,
            'session': _current_session(),
        }
        
    except Exception as e:
        logger.error(f"[forex-api] status error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/silver-bullet")
def forex_silver_bullet() -> Dict:
    """
    The Silver Bullet strategy state on its own: active session, session clock,
    per-symbol daily bias and volume-profile levels, and the pending setups.

    Split out from /status so the dashboard can poll the strategy state without
    re-fetching balances and CRT levels it already has.
    """
    return _silver_bullet_state()


@router.get("/silver-bullet/setups")
def forex_silver_bullet_setups() -> Dict:
    """Pending Silver Bullet setups with their state, confidence and expiry."""
    state = _silver_bullet_state()
    return {
        "date": state.get("date"),
        "active_session": state.get("active_session"),
        "pending_count": state.get("pending_count", 0),
        "min_confidence": state.get("min_confidence"),
        "setups": state.get("pending_setups", []),
    }


@router.get("/schedule")
def forex_schedule() -> Dict:
    """
    The UTC schedule the scheduler is actually running.

    Served from the modules that enforce it, so the dashboard cannot show a
    schedule that differs from the one in force.
    """
    from modules.forex_position_manager import (EOD_HOUR, EOD_MINUTE,
                                                EOD_NO_NEW_ENTRIES_HOUR,
                                                next_session_times)
    from modules.forex_signal_engine import MIN_CONFIDENCE

    return {
        "timezone": "UTC",
        "sessions": next_session_times(),
        "jobs": [
            {"time": "00:01", "job": "Reset daily strategy cache"},
            {"time": "07:00", "job": "Daily bias + volume profile"},
            {"time": "07:55", "job": "Pre-session liquidity (London)"},
            {"time": "08:00-09:00", "job": "London scanner, every 5 min"},
            {"time": "14:55", "job": "Pre-session liquidity (NY morning)"},
            {"time": "15:00-16:00", "job": "NY morning scanner, every 5 min"},
            {"time": "18:55", "job": "Pre-session liquidity (NY afternoon)"},
            {"time": "19:00-20:00", "job": "NY afternoon scanner, every 5 min"},
            {"time": "every 2 min", "job": "Monitor open forex positions"},
            {"time": f"{EOD_HOUR:02d}:{EOD_MINUTE:02d}", "job": "End-of-day position policy"},
            {"time": "23:00", "job": "Daily report"},
        ],
        "no_new_entries_after_hour": EOD_NO_NEW_ENTRIES_HOUR,
        "min_confidence": MIN_CONFIDENCE,
    }


@router.get("/balance")
def forex_balance() -> Dict:
    """Get Capital.com account balance (separate from crypto balance)."""
    try:
        from config import FOREX_ENABLED
        if not FOREX_ENABLED:
            return {'enabled': False, 'balance': 0.0, 'profit_loss': 0.0}
        from modules.market_data_forex import get_capital_balance
        info = get_capital_balance()
        return {'enabled': True, **info}
    except Exception as e:
        logger.error(f"[forex-api] balance error: {e}")
        return {'enabled': True, 'connected': False, 'balance': 0.0, 'profit_loss': 0.0}


@router.get("/test-connection")
def forex_test_connection() -> Dict:
    """
    Full Capital.com connectivity test for the dashboard button.
    Checks: env vars → session login → account balance → candle fetch.
    """
    try:
        from modules.market_data_forex import test_connection
        return test_connection()
    except Exception as e:
        logger.error(f"[forex-api] test-connection error: {e}")
        return {'connected': False, 'error': str(e)}


@router.get("/kronos-status")
def kronos_status() -> Dict:
    """Kronos model load state (for diagnostics)."""
    try:
        from modules.kronos_engine import get_kronos_status
        return get_kronos_status()
    except Exception as e:
        return {'state': 'error', 'error': str(e), 'available': False}


@router.get("/signals")
def forex_signals() -> List[Dict]:
    """
    Active forex signals — Silver Bullet's daily bias and volume profile.

    This used to read the Kronos bias and the CRT range cache. Both belonged to
    the retired stack, so the endpoint reported a strategy that could not trade.
    The key names are kept for frontend compatibility; the data is now Silver
    Bullet's, and `strategy` names what is actually running.
    """
    try:
        from config import FOREX_PAIRS
        from modules.silver_bullet import get_daily_bias
        from modules.market_data_forex import get_current_price

        signals = []

        for symbol in FOREX_PAIRS:
            try:
                rec = get_daily_bias(symbol) or {}
                vp = rec.get("vp_levels") or {}
                price = get_current_price(symbol)

                if not vp:
                    continue

                signals.append({
                    'symbol': symbol,
                    'strategy': 'SILVER_BULLET',
                    'current_price': price,
                    'h4_bias': rec.get('h4_bias'),
                    'price_position': rec.get('price_position'),
                    'vp_bias': rec.get('vp_bias'),
                    'vp_levels': {
                        'poc': vp.get('poc'), 'vah': vp.get('vah'),
                        'val': vp.get('val'),
                        'volume_source': vp.get('volume_source'),
                        'source_trusted': vp.get('source_trusted'),
                        'valid': vp.get('valid'),
                    },
                    'vp_gateable': rec.get('vp_gateable'),
                    # Legacy key names, now carrying the volume profile so an
                    # existing consumer is not left with empty fields.
                    'pdh': vp.get('vah'),
                    'pdl': vp.get('val'),
                    'timeframe': '1d',
                    'ranges': {'1d': {'high': vp.get('vah'), 'low': vp.get('val')}},
                    'kronos_bias': rec.get('h4_bias') or 'NEUTRAL',
                    'kronos_confidence_boost': 0,
                    'crt_status': 'WAITING',
                    'predicted_change': 0,
                })

            except Exception as e:
                logger.error(f"[forex-api] signal error {symbol}: {e}")
                continue

        return signals

    except Exception as e:
        logger.error(f"[forex-api] signals error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/positions")
def forex_positions() -> Dict:
    """
    Get open forex positions with live P&L
    """
    try:
        from modules.forex_position_manager import get_forex_position_summary

        summary = get_forex_position_summary()

        # Silver Bullet context the positions panel needs: which window is open,
        # how many setups are queued behind it, and today's halt state. These are
        # additive keys, so an existing consumer is unaffected.
        try:
            from modules.forex_position_manager import daily_halt_active
            state = _silver_bullet_state()
            halted, halt_reason = daily_halt_active()
            summary["active_session"] = state.get("active_session")
            summary["pending_setups"] = state.get("pending_count", 0)
            summary["daily_halt"] = halted
            summary["daily_halt_reason"] = halt_reason
        except Exception as e:
            logger.warning(f"[forex-api] position context unavailable: {e}")

        return summary

    except Exception as e:
        logger.error(f"[forex-api] positions error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/daily-report")
def forex_daily_report() -> Dict:
    """
    The day's forex trading summary.

    Read-only and computed on demand, so the dashboard can show it before the
    23:00 job has run.
    """
    from modules.forex_position_manager import build_daily_report
    return build_daily_report()


@router.get("/trades")
def forex_trades(limit: int = 50) -> List[Dict]:
    """
    Get forex trade history
    """
    try:
        from modules.forex_position_manager import get_forex_trade_history
        
        return get_forex_trade_history(limit)
        
    except Exception as e:
        logger.error(f"[forex-api] trades error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/trade/{trade_id}/close")
def close_forex_trade(trade_id: int) -> Dict:
    """
    Manually close one forex position.

    Closes it at Capital.com and records the realised P&L on the trade row.
    """
    try:
        from database import SessionLocal
        from models import ForexTrade
        from modules.forex_executor import close_forex_position

        db = SessionLocal()
        try:
            trade = db.query(ForexTrade).filter(
                ForexTrade.id == trade_id,
                ForexTrade.outcome == "OPEN",
            ).first()

            if not trade:
                return {"success": False, "error": "Trade not found or already closed"}

            symbol = trade.symbol
            deal_id = trade.metaapi_position_id
        finally:
            db.close()

        # Diagnostic mode suppresses order side effects, including closes, so a
        # simulation cannot flatten a real position.
        from main import guard_order
        blocked = guard_order(symbol, "forex")
        if blocked:
            logger.info(f"[forex-api] close suppressed for {symbol}: {blocked['error']}")
            return blocked

        if not deal_id:
            return {"success": False,
                    "error": f"{symbol} has no broker deal id — cannot close"}

        result = close_forex_position(deal_id, trade_id)
        if result.get("success"):
            logger.info(f"[forex-api] manual close {symbol} pnl=${result.get('pnl', 0):+.2f}")
            return {
                "success": True,
                "message": f"Closed {symbol}",
                "pnl": result.get("pnl", 0.0),
                "symbol": symbol,
            }
        return {"success": False, "error": result.get("error", "Close failed")}

    except Exception as e:
        logger.error(f"[forex-api] close trade error: {e}")
        return {"success": False, "error": str(e)}


@router.post("/close-all")
def close_all_forex() -> Dict:
    """Close every open forex position and return the combined P&L."""
    try:
        from modules.forex_executor import close_all_forex_positions
        from main import guard_order

        blocked = guard_order("*", "forex")
        if blocked:
            logger.info(f"[forex-api] close-all suppressed: {blocked['error']}")
            return {**blocked, "closed": 0, "failed": 0, "total_pnl": 0.0,
                    "results": []}

        result = close_all_forex_positions()
        logger.info(f"[forex-api] close-all — {result['closed']} closed, "
                    f"{result['failed']} failed, P&L ${result['total_pnl']:+.2f}")
        return result

    except Exception as e:
        logger.error(f"[forex-api] close-all error: {e}")
        return {"success": False, "error": str(e), "closed": 0, "failed": 0,
                "total_pnl": 0.0, "results": []}


@router.delete("/trades/clear")
def clear_forex_trades() -> Dict:
    """Clear forex trade history (open positions are left untouched)."""
    try:
        from database import SessionLocal
        from models import ForexTrade

        db = SessionLocal()
        try:
            deleted = db.query(ForexTrade).filter(
                ForexTrade.outcome != "OPEN"
            ).delete(synchronize_session=False)
            db.commit()
            logger.info(f"[forex-api] cleared {deleted} closed forex trades")
            return {"success": True, "deleted": deleted}
        finally:
            db.close()

    except Exception as e:
        logger.error(f"[forex-api] clear trades error: {e}")
        return {"success": False, "error": str(e), "deleted": 0}


@router.get("/cascade-stats")
def cascade_stats() -> Dict:
    """
    Performance grouped by the CRT timeframe chain that produced each trade.
    Lets you see which cascade combos actually win.
    """
    try:
        from database import SessionLocal
        from models import ForexTrade

        db = SessionLocal()
        try:
            trades = db.query(ForexTrade).filter(
                ForexTrade.outcome.in_(["WIN", "LOSS"])
            ).all()

            buckets: Dict[str, Dict] = {}
            for t in trades:
                key = f"{t.crt_timeframe or '?'}→{t.confirm_timeframe or '?'}→{t.entry_timeframe or '?'}"
                b = buckets.setdefault(key, {
                    "chain": key,
                    "crt_timeframe": t.crt_timeframe,
                    "confirm_timeframe": t.confirm_timeframe,
                    "entry_timeframe": t.entry_timeframe,
                    "trades": 0, "wins": 0, "losses": 0, "pnl": 0.0,
                })
                b["trades"] += 1
                if t.outcome == "WIN":
                    b["wins"] += 1
                else:
                    b["losses"] += 1
                b["pnl"] += (t.pnl or 0)

            out = []
            for b in buckets.values():
                b["win_rate"] = round(b["wins"] / max(b["trades"], 1) * 100, 1)
                b["pnl"] = round(b["pnl"], 2)
                out.append(b)

            out.sort(key=lambda x: x["trades"], reverse=True)

            # Also break down by POI type
            poi_buckets: Dict[str, Dict] = {}
            for t in trades:
                k = t.poi or "unknown"
                p = poi_buckets.setdefault(k, {"poi": k, "trades": 0, "wins": 0, "pnl": 0.0})
                p["trades"] += 1
                if t.outcome == "WIN":
                    p["wins"] += 1
                p["pnl"] += (t.pnl or 0)
            poi_out = []
            for p in poi_buckets.values():
                p["win_rate"] = round(p["wins"] / max(p["trades"], 1) * 100, 1)
                p["pnl"] = round(p["pnl"], 2)
                poi_out.append(p)
            poi_out.sort(key=lambda x: x["trades"], reverse=True)

            return {"chains": out, "poi": poi_out, "total_closed": len(trades)}
        finally:
            db.close()

    except Exception as e:
        logger.error(f"[forex-api] cascade-stats error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/update-bias/{symbol}")
def update_kronos_bias(symbol: str) -> Dict:
    """
    Manually refresh a symbol's Silver Bullet daily bias and volume profile.

    This used to run the Kronos model. Kronos was the bias layer of the retired
    stack and nothing in the live path consults it, so running it would spend
    GPU time producing a number no decision reads. The route and name are kept
    so an existing caller keeps working; the work it does is now the live
    strategy's.
    """
    try:
        from modules.silver_bullet import calculate_daily_bias

        record = calculate_daily_bias(symbol)
        if not record:
            raise HTTPException(status_code=500,
                                detail="Daily bias calculation failed")

        vp = record.get("vp_levels") or {}
        return {
            "symbol": symbol,
            "strategy": "SILVER_BULLET",
            "h4_bias": record.get("h4_bias"),
            "strength": record.get("strength"),
            "price_position": record.get("price_position"),
            "vp_levels": {"poc": vp.get("poc"), "vah": vp.get("vah"),
                          "val": vp.get("val")} if vp else None,
            "vp_gateable": record.get("vp_gateable"),
            "session_date": record.get("session_date"),
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[forex-api] bias update error {symbol}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/update-crt/{symbol}")
def update_crt_levels(symbol: str) -> Dict:
    """
    Manually trigger a strategy refresh for a symbol.

    This used to recompute the retired CRT ranges. It now refreshes the Silver
    Bullet daily bias and previous-day volume profile, which is what the
    dashboard displays. The route and its name are kept so an existing caller
    keeps working, but the data it returns is the live strategy's.
    """
    try:
        from modules.silver_bullet import calculate_daily_bias

        record = calculate_daily_bias(symbol)
        if not record:
            raise HTTPException(status_code=500,
                                detail="Daily bias calculation failed")

        vp = record.get("vp_levels") or {}
        return {
            "symbol": symbol,
            "strategy": "SILVER_BULLET",
            "h4_bias": record.get("h4_bias"),
            "strength": record.get("strength"),
            "vp_levels": {"poc": vp.get("poc"), "vah": vp.get("vah"),
                          "val": vp.get("val")} if vp else None,
            "vp_gateable": record.get("vp_gateable"),
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[forex-api] strategy update error {symbol}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/pair/{symbol}")
def forex_pair_detail(symbol: str) -> Dict:
    """
    Detailed Silver Bullet state for one pair.
    """
    try:
        from modules.market_data_forex import get_current_price
        from database import SessionLocal
        from models import ForexTrade
        
        price = get_current_price(symbol)
        
        db = SessionLocal()
        try:
            open_trade = db.query(ForexTrade).filter(
                ForexTrade.symbol == symbol,
                ForexTrade.outcome == 'OPEN'
            ).first()
            
            recent_trades = db.query(ForexTrade).filter(
                ForexTrade.symbol == symbol
            ).order_by(ForexTrade.created_at.desc()).limit(10).all()
            
        finally:
            db.close()
        
        # ── Silver Bullet state for this pair ────────────────────────────────
        # The CRT `active_setup` block that used to sit above this read the
        # retired CRT range cache and labelled the card "ENTRY TRIGGERED". Both
        # are gone: the only setup the application can act on is a Silver
        # Bullet one, and `silver_bullet.setup` below is it.
        silver = None
        try:
            from modules.silver_bullet import (get_active_setups, get_daily_bias,
                                               get_session_levels)
            from modules.forex_signal_engine import MIN_CONFIDENCE, current_session

            rec = get_daily_bias(symbol) or {}
            vp = rec.get("vp_levels") or {}
            setup = get_active_setups().get(symbol)
            levels_sb = None
            active = current_session()
            if active:
                levels_sb = get_session_levels(symbol, active)

            silver = {
                "h4_bias": rec.get("h4_bias"),
                "strength": rec.get("strength"),
                "price_position": rec.get("price_position"),
                "vp_bias": rec.get("vp_bias"),
                "ema50": rec.get("ema50"),
                "vp_levels": {
                    "poc": vp.get("poc"), "vah": vp.get("vah"), "val": vp.get("val"),
                    "volume_source": vp.get("volume_source"),
                    "source_trusted": vp.get("source_trusted"),
                    "valid": vp.get("valid"), "warning": vp.get("warning"),
                } if vp else None,
                "vp_gateable": rec.get("vp_gateable"),
                "vp_gate_reason": rec.get("vp_gate_reason"),
                "min_confidence": MIN_CONFIDENCE,
                "session_levels": levels_sb,
                "setup": {
                    "state": setup.get("state"),
                    "direction": setup.get("direction"),
                    "session": setup.get("session"),
                    "confidence": setup.get("confidence"),
                    "executable": bool(setup.get("executable")),
                    "entry_taken": bool(setup.get("entry_taken")),
                    "reject_reason": setup.get("reject_reason"),
                    "fvg_low": (setup.get("fvg") or {}).get("fvg_low"),
                    "fvg_high": (setup.get("fvg") or {}).get("fvg_high"),
                    "sweep_wick": (setup.get("sweep") or {}).get("sweep_wick"),
                    "vp_confluence": setup.get("vp_confluence"),
                    "expires_at": setup.get("expires_at"),
                } if setup else None,
            }
        except Exception as e:
            logger.warning(f"[forex-api] silver bullet detail unavailable {symbol}: {e}")

        return {
            'symbol': symbol,
            'current_price': price,
            'strategy': 'SILVER_BULLET',
            # Legacy key names, now carrying the Silver Bullet volume profile so
            # an older frontend build still finds its fields.
            'kronos_bias': (silver or {}).get('h4_bias'),
            'crt_levels': (silver or {}).get('vp_levels'),
            'crt_ranges': {},
            'active_setup': (silver or {}).get('setup'),
            'session': _current_session(),
            'silver_bullet': silver,
            'open_trade': {
                'id': open_trade.id,
                'signal': open_trade.signal,
                'entry': open_trade.entry_price,
                'sl': open_trade.stop_loss,
                'tp': open_trade.take_profit,
                'tp1': open_trade.tp1,
                'tp2': open_trade.tp2,
                'tp3': open_trade.tp3,
                'entry_type': open_trade.entry_type,
                'partial_tp_hit': bool(open_trade.partial_tp_hit),
                'partial_close_pct': open_trade.partial_close_pct,
                'tp1_done': bool(open_trade.tp1_done),
                'tp2_done': bool(open_trade.tp2_done),
                'tp3_done': bool(open_trade.tp3_done),
                'breakeven_done': bool(open_trade.breakeven_done),
                'trailing_active': bool(open_trade.trailing_active),
                'session': open_trade.session_name,
                'vp_confluence': open_trade.vp_confluence,
                'lots': open_trade.lots,
                'original_lots': open_trade.original_lots,
                'confidence': open_trade.confidence
            } if open_trade else None,
            'recent_trades_count': len(recent_trades),
            'recent_wins': len([t for t in recent_trades if t.outcome == 'WIN']),
            'recent_losses': len([t for t in recent_trades if t.outcome == 'LOSS'])
        }
        
    except Exception as e:
        logger.error(f"[forex-api] pair detail error {symbol}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


def _current_session() -> str:
    """
    Trading session label for the current UTC hour.

    Delegates to the engine's own session table. This used to hold a SECOND,
    different definition ('NY' for 12-15, 'LONDON' for 7-12, else 'ASIA'), which
    disagreed with the windows the scanner actually enforces: the API could
    report 'LONDON' while the engine reported no session, or 'ASIA' during the
    19:00-20:00 window the engine calls NY_AFTERNOON. A dashboard that
    contradicts the scanner is worse than no dashboard.

    Returns the engine's session name, or 'CLOSED' when no window is open.
    """
    from modules.forex_signal_engine import current_session
    return current_session() or "CLOSED"


def _legacy_entries_enabled() -> bool:
    """
    Whether the legacy CRT/SMC path may submit orders. Fails closed.

    Exposed so the API can tell the dashboard that a CRT setup is data-only
    rather than tradeable.
    """
    try:
        from modules.forex_executor import legacy_entries_enabled
        return legacy_entries_enabled()
    except Exception:
        return False


def _silver_bullet_state() -> Dict:
    """
    Today's Silver Bullet state for the dashboard: session clock, daily bias with
    its volume-profile levels, and the pending setups.

    Every value comes from the modules that enforce the strategy. Nothing is
    recomputed here, so what the dashboard shows is what the scanner decided.
    """
    try:
        from modules.forex_signal_engine import (MIN_CONFIDENCE, current_session,
                                                 session_bounds,
                                                 session_time_remaining)
        from modules.silver_bullet import (get_active_setups, get_all_daily_bias,
                                           get_session_levels, utc_date_key)

        now = datetime.utcnow()
        active = current_session(now)
        biases = get_all_daily_bias(now)

        # ── Bias + volume profile per symbol ─────────────────────────────────
        bias_rows = {}
        for symbol, rec in biases.items():
            vp = rec.get("vp_levels") or {}
            bias_rows[symbol] = {
                "h4_bias": rec.get("h4_bias"),
                "strength": rec.get("strength"),
                "price_position": rec.get("price_position"),
                "vp_bias": rec.get("vp_bias"),
                "h4_close": rec.get("h4_close"),
                "ema50": rec.get("ema50"),
                "session_date": rec.get("session_date"),
                "vp_levels": {
                    "poc": vp.get("poc"), "vah": vp.get("vah"),
                    "val": vp.get("val"),
                    "volume_source": vp.get("volume_source"),
                    "source_trusted": vp.get("source_trusted"),
                    "valid": vp.get("valid"),
                    "warning": vp.get("warning"),
                } if vp else None,
                "vp_gateable": rec.get("vp_gateable"),
                "vp_gate_reason": rec.get("vp_gate_reason"),
            }

        # ── Pending setups ───────────────────────────────────────────────────
        pending = []
        for symbol, setup in get_active_setups().items():
            pending.append({
                "symbol": symbol,
                "state": setup.get("state"),
                "direction": setup.get("direction"),
                "session": setup.get("session"),
                "confidence": setup.get("confidence"),
                "executable": bool(setup.get("executable")),
                "entry_taken": bool(setup.get("entry_taken")),
                "fvg_low": (setup.get("fvg") or {}).get("fvg_low"),
                "fvg_high": (setup.get("fvg") or {}).get("fvg_high"),
                "sweep_wick": (setup.get("sweep") or {}).get("sweep_wick"),
                "vp_confluence": setup.get("vp_confluence"),
                "vp_source": setup.get("vp_source"),
                "vp_gateable": setup.get("vp_gateable"),
                "bias": setup.get("bias"),
                "expires_at": setup.get("expires_at"),
                "created_at": setup.get("created_at"),
            })
        pending.sort(key=lambda s: -(s.get("confidence") or 0))

        # ── Session clock ────────────────────────────────────────────────────
        windows = {}
        for name in ("LONDON", "NY_MORNING", "NY_AFTERNOON"):
            open_dt, close_dt = session_bounds(name, now)
            windows[name] = {
                "open_utc": open_dt.strftime("%H:%M"),
                "close_utc": close_dt.strftime("%H:%M"),
                "is_open": name == active,
                "opens_in_minutes": round((open_dt - now).total_seconds() / 60.0, 1),
            }

        return {
            "date": utc_date_key(now),
            "active_session": active or "CLOSED",
            "time_remaining_seconds": session_time_remaining(active, now) if active else 0,
            "sessions": windows,
            "min_confidence": MIN_CONFIDENCE,
            "biases": bias_rows,
            "pending_setups": pending,
            "pending_count": len(pending),
            "symbols_with_bias": len(bias_rows),
        }

    except Exception as e:
        logger.error(f"[forex-api] silver bullet state error: {e}")
        return {"error": str(e), "active_session": "UNKNOWN",
                "pending_setups": [], "biases": {}, "pending_count": 0}
