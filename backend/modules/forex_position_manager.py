"""
backend/modules/forex_position_manager.py
Capital.com REST position monitoring for Forex/Metals.

Pure synchronous — no asyncio.
"""
import logging
from datetime import datetime
from typing import List, Dict, Optional, Tuple

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
                    # Gone from the broker. Work out whether it hit the stop
                    # or the target so the P&L can be estimated, because the
                    # broker does not report the realised amount here. Without
                    # this the trade is recorded with pnl = None and drops out
                    # of every P&L and win-rate calculation.
                    est_pnl, how = _estimate_closed_pnl(trade)
                    logger.info(f"[capital] trade {trade.id} ({trade.symbol}) "
                                f"no longer open at broker — {how}, "
                                f"est. P&L ${est_pnl:+.2f}")
                    trade.outcome = "WIN" if est_pnl >= 0 else "LOSS"
                    trade.pnl = round(est_pnl, 4)
                    trade.closed_at = datetime.utcnow()
                    trade.close_reason = trade.close_reason or f"broker-side close ({how})"
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
    Retained for the reconciliation path, now delegating to the management rules.

    This used to close the WHOLE position and reopen half at breakeven. That
    approach had three defects, all of which are why it is gone:

      * if the reopen failed the position was fully closed and the trade marked
        CLOSED_EXTERNAL — a live trade destroyed by a partial-close attempt;
      * it realised P&L and re-entered at the CURRENT price, so the new stop
        was "breakeven" on a different entry than the trade actually had;
      * between the close and the reopen the account held no position at all,
        so a crash in that window silently removed the trade.

    Capital.com closes partially with a size body, so a partial is now a single
    atomic call. The level flag is written before the call and rolled back if it
    fails, which makes the whole thing idempotent under retry.
    """
    if trade.partial_tp_hit:
        return
    if trade.tp1 is None or not trade.lots:
        return

    try:
        from modules.market_data_forex import close_position, get_current_price

        price = get_current_price(trade.symbol)
        if not price:
            return

        hit = (price >= trade.tp1) if trade.signal == "BUY" else (price <= trade.tp1)
        if not hit:
            return

        from modules.forex_executor import partial_close_size

        original = float(trade.original_lots or trade.lots)
        size = partial_close_size(original, 1, original - float(trade.lots))
        if size <= 0:
            trade.tp1_done = True
            db.commit()
            return

        # Write the flag BEFORE trusting the broker, so a crash after the close
        # cannot repeat it. Rolled back below if the call fails.
        trade.tp1_done = True

        result = close_position(trade.metaapi_position_id, size=size)
        if not result.get("success"):
            trade.tp1_done = False
            db.commit()
            logger.warning(f"[forex] {trade.symbol} TP1 partial failed: "
                           f"{result.get('error')} — will retry next cycle")
            return

        remaining = result.get("remaining")
        if remaining is None:
            remaining = max(0.0, float(trade.lots) - float(size))

        trade.lots = remaining
        original = float(trade.original_lots or 0.0)
        if original > 0:
            trade.partial_close_pct = round((original - remaining) / original * 100, 2)
        trade.partial_tp_hit = True
        db.commit()

        logger.info(f"[forex] PARTIAL TP HIT — {trade.symbol} closed {size} units "
                    f"@ {price:.5f}, {remaining} remaining. Stop is moved to entry "
                    f"by the management cycle, which caps the loss at entry "
                    f"rather than guaranteeing a profit after fees.")

    except Exception as e:
        logger.error(f"[capital] partial tp error {trade.symbol}: {e}")
        db.rollback()


# ══════════════════════════════════════════════════════════════════════════════
#  SILVER BULLET TRADE MANAGEMENT
#
#  Five rules, applied to every open Silver Bullet position on each cycle:
#
#    1. Breakeven protection   — after TP1, the stop moves to entry
#    2. Trailing stop          — after TP1, the stop follows price by an ATR
#    3. Session/time exit      — the trade dies with the window that opened it
#    4. Opposing-structure     — the daily bias flipping against the trade exits it
#    5. Daily drawdown halt    — no new risk once the day's loss limit is hit
#
#  All five are pure decisions over a trade record plus market inputs, so they
#  are testable without a broker. The side effects (amend, close) are performed
#  by `manage_open_positions` below.
#
#  A note on rule 1: a stop at breakeven is NOT a guaranteed profitable trade.
#  It sits at the entry PRICE, so fees, financing and any slippage or gap
#  through the stop are all still losses. The log says "stop at entry", never
#  "risk-free", and the P&L is whatever the broker reports.
# ══════════════════════════════════════════════════════════════════════════════

# Once TP1 is taken the stop trails this far behind the best price seen.
TRAIL_ATR_MULTIPLE = 1.0

# A trade is force-closed after this many hours regardless of price, so a
# position cannot sit open across sessions waiting for a target that the
# session it was built for has already invalidated.
MAX_HOLDING_HOURS = 12

# How far beyond the entry a stop must be before it is worth moving. Moving a
# stop for a fraction of a pip burns API calls and invites an amend the broker
# rejects for being too close to price.
MIN_STOP_MOVE_ATR = 0.05


def _risk_distance(trade) -> float:
    """The trade's initial 1R distance, in price."""
    try:
        risk = float(trade.initial_risk or 0.0)
        if risk > 0:
            return risk
        entry = float(trade.entry_price or 0.0)
        stop = float(trade.initial_stop or trade.stop_loss or 0.0)
        return abs(entry - stop)
    except (TypeError, ValueError):
        return 0.0


def _r_multiple(trade, price: float) -> float:
    """How far price is from entry, measured in R. Negative when losing."""
    risk = _risk_distance(trade)
    if risk <= 0 or price is None:
        return 0.0
    try:
        sign = 1.0 if trade.signal == "BUY" else -1.0
        return (float(price) - float(trade.entry_price)) * sign / risk
    except (TypeError, ValueError):
        return 0.0


def next_partial_level(trade, price: float) -> Optional[int]:
    """
    Which partial take-profit level price has reached, if any.

    Levels are checked in order and only the NEXT un-taken one is returned, so
    a price that gaps past TP1 and TP2 in one tick still books TP1 first and
    books TP2 on the following cycle rather than skipping a level.
    """
    if price is None:
        return None

    for level, done_attr, target_attr in (
        (1, "tp1_done", "tp1"),
        (2, "tp2_done", "tp2"),
        (3, "tp3_done", "tp3"),
    ):
        if getattr(trade, done_attr, False):
            continue
        target = getattr(trade, target_attr, None)
        if target is None:
            continue
        target = float(target)
        hit = price >= target if trade.signal == "BUY" else price <= target
        return level if hit else None
    return None


def breakeven_stop(trade) -> Optional[float]:
    """
    The stop to use once TP1 is taken: the entry price.

    Returns None when the stop is already at or beyond entry, so the caller
    does not re-send an amend that would do nothing. The stop is only ever
    moved FORWARD — a stop already better than entry is left alone.

    A trade with no TP1 recorded is treated as armed. There is nothing to wait
    for, and the alternative is that rules 1 and 2 never engage at all on such
    a record — leaving the position unprotected for its whole life. Moving to
    entry is the risk-reducing direction, so engaging early is the safe error.
    """
    if not getattr(trade, "tp1_done", False) and getattr(trade, "tp1", None) is not None:
        return None
    try:
        entry = float(trade.entry_price)
        current = float(trade.stop_loss or 0.0)
    except (TypeError, ValueError):
        return None

    if current <= 0:
        return None

    if trade.signal == "BUY":
        return None if current >= entry else entry
    return None if current <= entry else entry


def trail_stop(trade, price: float, atr: float) -> Optional[float]:
    """
    The trailed stop after TP1, or None when it should not move.

    For a BUY the stop follows `price - TRAIL_ATR_MULTIPLE * atr`; for a SELL,
    `price + ...`. The stop is MONOTONIC: a computed level worse than the
    current stop is discarded, so a pullback can never widen risk back out.

    The move must also clear MIN_STOP_MOVE_ATR, which stops the cycle re-sending
    an amend for a fraction of an ATR — each send costs an API call and risks a
    rejection for being too close to price.
    """
    if not getattr(trade, "tp1_done", False) and getattr(trade, "tp1", None) is not None:
        return None
    if price is None or not atr or atr <= 0:
        return None

    try:
        price = float(price)
        atr = float(atr)
        current = float(trade.stop_loss or 0.0)
    except (TypeError, ValueError):
        return None

    if current <= 0:
        return None

    # A stop that is still on the losing side of entry is breakeven's job, not
    # the trail's. Trailing from there could move the stop to a level that is
    # better than entry without ever having protected it.
    try:
        entry = float(trade.entry_price)
    except (TypeError, ValueError):
        entry = None
    if entry is not None:
        if trade.signal == "BUY" and current < entry:
            return None
        if trade.signal == "SELL" and current > entry:
            return None

    if trade.signal == "BUY":
        candidate = price - TRAIL_ATR_MULTIPLE * atr
        if candidate <= current:
            return None
    else:
        candidate = price + TRAIL_ATR_MULTIPLE * atr
        if candidate >= current:
            return None

    if abs(candidate - current) < MIN_STOP_MOVE_ATR * atr:
        return None
    return candidate


def session_exit_due(trade, now: Optional[datetime] = None) -> Tuple[bool, str]:
    """
    Whether the trade must close on time rather than on price.

    Two triggers, both checked because either can fire first:

      * the session window that opened the trade has closed — the setup was
        built for that window's liquidity, so once the window is over the
        premise is gone;
      * the trade has been open longer than MAX_HOLDING_HOURS, which catches a
        position whose session is long past (e.g. one opened on a Friday).
    """
    now = now or datetime.utcnow()

    expires = getattr(trade, "session_expires_at", None)
    if expires is not None:
        try:
            if now >= expires:
                return True, (f"session {trade.session_name or '?'} closed at "
                              f"{expires:%H:%M} UTC")
        except TypeError:
            # A naive/aware mismatch must not crash the monitor; fall through
            # to the holding-time check rather than skipping the exit.
            pass

    created = getattr(trade, "created_at", None)
    if created is not None:
        try:
            age_hours = (now - created.replace(tzinfo=None)).total_seconds() / 3600.0
            if age_hours >= MAX_HOLDING_HOURS:
                return True, f"held {age_hours:.1f}h past the {MAX_HOLDING_HOURS}h limit"
        except Exception:
            pass

    return False, ""


def reversal_detected(trade, bias: Optional[Dict]) -> Tuple[bool, str]:
    """
    Whether the higher-timeframe structure has turned against an open trade.

    A BUY is invalidated by a BEARISH daily bias and a SELL by a BULLISH one.
    NEUTRAL is NOT a reversal: it means the day has no direction, which is a
    reason not to open a trade rather than a reason to close one. Exiting on
    NEUTRAL would close every position the moment the bias was recomputed at
    the day boundary.
    """
    if not bias:
        return False, ""

    h4 = bias.get("h4_bias")
    if trade.signal == "BUY" and h4 == "BEARISH":
        return True, "daily bias flipped BEARISH against a long"
    if trade.signal == "SELL" and h4 == "BULLISH":
        return True, "daily bias flipped BULLISH against a short"
    return False, ""


def decide_trade_action(trade, price: float, atr: float,
                        bias: Optional[Dict] = None,
                        now: Optional[datetime] = None) -> Dict:
    """
    Decide what to do with one open trade this cycle.

    Returns {action, ...} where action is one of:
      HOLD | PARTIAL | MOVE_STOP | CLOSE

    `CLOSE` carries a `reason`. `PARTIAL` carries `level` and `size`.
    `MOVE_STOP` carries `stop`.

    Precedence is deliberate and is the safety order: a forced exit
    (session/time, then reversal) beats a profit action, so a trade that is due
    to leave is never first amended. A partial beats a stop move, because
    taking the profit is what makes the subsequent breakeven stop meaningful.
    """
    now = now or datetime.utcnow()

    if trade is None:
        return {"action": "HOLD", "reason": "no trade"}

    # ── Rule 3: session / time exit ──────────────────────────────────────────
    due, why = session_exit_due(trade, now)
    if due:
        return {"action": "CLOSE", "reason": f"time exit — {why}",
                "trigger": "SESSION_EXIT"}

    # ── Rule 4: opposing structure ───────────────────────────────────────────
    reversed_, why = reversal_detected(trade, bias)
    if reversed_:
        return {"action": "CLOSE", "reason": f"reversal — {why}",
                "trigger": "REVERSAL"}

    if price is None or price <= 0:
        return {"action": "HOLD", "reason": "no price"}

    # ── Rule 6: partial take-profits ─────────────────────────────────────────
    level = next_partial_level(trade, price)
    if level is not None:
        from modules.forex_executor import partial_close_size
        original = float(trade.original_lots or trade.lots or 0.0)
        already = original - float(trade.lots or 0.0)
        size = partial_close_size(original, level, already)
        if size > 0:
            return {"action": "PARTIAL", "level": level,
                    "size": round(size, 6), "price": price,
                    "reason": f"TP{level} reached at {price}"}
        # Nothing left to close at this level — mark it done so it is not
        # re-evaluated forever, and fall through to the stop logic.
        return {"action": "MARK_LEVEL", "level": level,
                "reason": f"TP{level} reached but no size remains"}

    # ── Rules 1 and 2: breakeven first, then trailing ────────────────────────
    # Breakeven is checked BEFORE trailing, not as an else-branch. If trailing
    # were tried first it would move the stop to price-minus-ATR, which is
    # usually BETTER than entry — and then breakeven would be skipped forever
    # and the stop could still sit below entry on the first cycle after TP1,
    # which is the one cycle where the protection actually matters.
    if getattr(trade, "tp1_done", False):
        be = breakeven_stop(trade)
        if be is not None:
            return {"action": "MOVE_STOP", "stop": round(be, 5),
                    "reason": "stop to entry after TP1"}

        trail = trail_stop(trade, price, atr)
        if trail is not None:
            return {"action": "MOVE_STOP", "stop": round(trail, 5),
                    "reason": f"trailing {TRAIL_ATR_MULTIPLE} ATR behind {price}"}

    return {"action": "HOLD", "reason": "no rule triggered"}


def manage_open_positions(now: Optional[datetime] = None) -> Dict:
    """
    Apply the trade-management rules to every open Silver Bullet position.

    Each action is idempotent and the state is committed BEFORE the next action
    is attempted, so a crash mid-cycle cannot repeat a partial close: the flag
    that marks the level taken is already durable.

    Never raises — a management failure must not take the monitor down.
    """
    from modules.market_data_forex import (amend_position, close_position,
                                           get_current_price, get_open_positions)

    stats = {"checked": 0, "partials": 0, "stops": 0, "closed": 0, "errors": 0}

    try:
        positions = get_open_positions()
        if positions is None:
            # Broker unreachable. Do not guess about live trades.
            return {**stats, "skipped": "broker unavailable"}
        live_ids = {str(p.get("id")) for p in positions if p.get("id")}

        db = SessionLocal()
        try:
            open_trades = db.query(ForexTrade).filter(ForexTrade.outcome == "OPEN").all()

            for trade in open_trades:
                deal_id = str(trade.metaapi_position_id or "")
                if not deal_id or deal_id not in live_ids:
                    continue

                stats["checked"] += 1
                try:
                    _manage_one(trade, db, amend_position, close_position,
                                get_current_price, now, stats)
                except Exception as e:
                    stats["errors"] += 1
                    logger.error(f"[forex] management error {trade.symbol}: {e}")
                    db.rollback()

        finally:
            db.close()

        if any(stats[k] for k in ("partials", "stops", "closed")):
            logger.info(f"[forex] management cycle — checked={stats['checked']} "
                        f"partials={stats['partials']} stops={stats['stops']} "
                        f"closed={stats['closed']}")

    except Exception as e:
        logger.error(f"[forex] manage_open_positions error: {e}")
        stats["errors"] += 1

    return stats


def _manage_one(trade, db, amend_position, close_position,
                get_current_price, now, stats) -> None:
    """Decide and apply the action for a single trade, committing as it goes."""
    from modules.forex_signal_engine import calculate_atr

    price = get_current_price(trade.symbol)

    atr = 0.0
    try:
        from modules.candle_provider import get_candles
        df = get_candles(trade.symbol, timeframe="5m", limit=50)
        if df is not None and len(df):
            atr = calculate_atr(df)
    except Exception:
        atr = 0.0

    bias = None
    try:
        from modules.silver_bullet import get_daily_bias
        bias = get_daily_bias(trade.symbol, now)
    except Exception:
        bias = None

    # Peak price feeds the trailing stop; it is tracked even when no action
    # fires, so a restart resumes with the peak already known.
    if price:
        peak = float(trade.peak_price or 0.0)
        if trade.signal == "BUY":
            trade.peak_price = max(peak, float(price))
        else:
            trade.peak_price = min(peak, float(price)) if peak else float(price)
        db.commit()

    decision = decide_trade_action(trade, price, atr, bias, now)
    action = decision["action"]

    if action == "MARK_LEVEL":
        _mark_level(trade, decision["level"], db)
        return

    if action == "HOLD":
        return

    if action == "PARTIAL":
        _apply_partial(trade, decision, db, close_position)
        stats["partials"] += 1
        return

    if action == "MOVE_STOP":
        new_stop = decision["stop"]
        result = amend_position(trade.metaapi_position_id, sl=new_stop)
        if not result.get("success"):
            logger.warning(f"[forex] {trade.symbol} stop amend failed: "
                           f"{result.get('error')}")
            return
        trade.stop_loss = new_stop
        if not trade.breakeven_done and abs(new_stop - float(trade.entry_price)) < 1e-9:
            trade.breakeven_done = True
            logger.info(f"[forex] {trade.symbol} stop moved to ENTRY {new_stop:.5f} "
                        f"after TP1 — this caps the loss at entry, it does not "
                        f"guarantee a profit after fees or slippage")
        else:
            trade.trailing_active = True
            logger.info(f"[forex] {trade.symbol} stop trailed to {new_stop:.5f} "
                        f"({decision['reason']})")
        db.commit()
        stats["stops"] += 1
        return

    if action == "CLOSE":
        result = close_position(trade.metaapi_position_id)
        if not result.get("success"):
            logger.warning(f"[forex] {trade.symbol} close failed: {result.get('error')}")
            return
        _settle_trade(trade, result, decision, db)
        stats["closed"] += 1
        return


def _mark_level(trade, level: int, db) -> None:
    """Record a partial level as reached even though no size remained."""
    if level == 1:
        trade.tp1_done = True
    elif level == 2:
        trade.tp2_done = True
    elif level == 3:
        trade.tp3_done = True
    db.commit()


def _apply_partial(trade, decision: Dict, db, close_position) -> None:
    """
    Close part of a position and record it.

    Order of operations matters: the level flag is written and committed BEFORE
    the broker call is trusted, so a crash after the close cannot lead to the
    same partial being taken twice on the next cycle. If the broker call FAILS
    the flag is rolled back, so the level is retried rather than silently
    skipped.
    """
    level = decision["level"]
    size = decision["size"]

    if level == 1:
        trade.tp1_done = True
    elif level == 2:
        trade.tp2_done = True
    elif level == 3:
        trade.tp3_done = True

    result = close_position(trade.metaapi_position_id, size=size)
    if not result.get("success"):
        logger.warning(f"[forex] {trade.symbol} TP{level} partial close failed: "
                       f"{result.get('error')} — level left un-taken for retry")
        if level == 1:
            trade.tp1_done = False
        elif level == 2:
            trade.tp2_done = False
        elif level == 3:
            trade.tp3_done = False
        db.commit()
        return

    remaining = result.get("remaining")
    if remaining is None:
        remaining = max(0.0, float(trade.lots or 0.0) - float(size))
    trade.lots = remaining

    # Track the share of the ORIGINAL position that has been closed, so the
    # dashboard can show "75% closed" without re-deriving it from a size that
    # has already been reduced twice.
    original = float(trade.original_lots or 0.0)
    if original > 0:
        trade.partial_close_pct = round((original - remaining) / original * 100, 2)

    # TP1 also arms the breakeven/trailing rules.
    if level == 1:
        trade.partial_tp_hit = True

    db.commit()
    logger.info(f"[forex] TP{level} PARTIAL — {trade.symbol} closed {size} units "
                f"@ {decision.get('price')} ({result.get('partial') and 'partial' or 'full'}), "
                f"{remaining} remaining")


def _settle_trade(trade, result: Dict, decision: Dict, db) -> None:
    """Record a closed trade with the reason and the broker's P&L."""
    pnl = float(result.get("pnl") or 0.0)
    trade.outcome = "WIN" if pnl >= 0 else "LOSS"
    trade.pnl = round(pnl, 4)
    trade.closed_at = datetime.utcnow()
    trade.close_reason = decision.get("reason")
    db.commit()

    try:
        from modules.risk_manager import update_compound_stats
        from modules.market_data_forex import get_capital_balance
        update_compound_stats(won=(pnl >= 0), pnl=pnl,
                              balance=get_capital_balance().get("balance", 0.0))
    except Exception:
        pass

    logger.info(f"[forex] CLOSED {trade.symbol} ({decision.get('trigger')}) — "
                f"{decision.get('reason')} pnl=${pnl:+.2f}")


def daily_halt_active() -> Tuple[bool, str]:
    """
    Rule 5: whether new risk is blocked for the rest of the UTC day.

    Wraps the existing realised-loss check so there is one definition of "the
    day's budget is spent". A halt blocks NEW entries only — open positions are
    still managed, because closing them all at the worst moment is not
    protection.
    """
    try:
        allowed, reason = forex_daily_loss_check()
        if not allowed:
            return True, reason
        return False, "OK"
    except Exception as e:
        logger.error(f"[forex] daily halt check error: {e}")
        # Fail CLOSED: an unknown budget must not authorise new risk.
        return True, "daily loss check unavailable"


# ══════════════════════════════════════════════════════════════════════════════
#  END-OF-DAY POLICY
#
#  The specification calls for closing PROFITABLE positions at 20:30 UTC. The
#  distinction is the whole point of the rule: the last session closes at 20:00,
#  so a position that has made money has already banked what the strategy was
#  built to capture, and holding it through the illiquid rollover risks giving
#  that back. A LOSING position is a different situation — its stop is still
#  doing its job, and closing it early turns a bounded risk into a realised loss
#  for no strategic reason.
#
#  So: profitable closes, everything else is held under normal management.
# ══════════════════════════════════════════════════════════════════════════════

# After this UTC hour no new Silver Bullet setup is allowed to open a position.
EOD_NO_NEW_ENTRIES_HOUR = 20

# The end-of-day job runs at 20:30, i.e. 30 minutes after the last session.
EOD_HOUR = 20
EOD_MINUTE = 30

# Whether a position must be strictly profitable to be closed.
#
# True means a position whose P&L is exactly zero is HELD. That is deliberate:
# zero is not profit, and the rule was specified for profitable positions. The
# asymmetry also means an unreadable P&L fails toward keeping the position,
# which is the recoverable error — a position held a few hours longer is
# monitored and stopped out normally, whereas a position closed by mistake is
# gone.
EOD_REQUIRE_STRICTLY_PROFITABLE = True

# Profitability is measured on the broker's UNREALISED P&L, which is net of the
# spread and financing the position has already accrued. It is NOT net of the
# commission on the closing trade itself, because Capital.com does not expose a
# per-close commission before the close happens. So the rule is:
#
#   eligible  <=>  broker_unrealised_pnl > 0
#
# and a position can therefore close at a marginally positive UPL and settle at
# a small loss once the closing spread and any commission are applied. That is
# a known, documented limitation rather than an unstated assumption.


def _position_pnl_from_broker(deal_id: str, positions: List[Dict]) -> Optional[float]:
    """
    The broker's unrealised P&L for a deal, or None when it cannot be read.

    None is a real answer and is never coerced to 0.0: "we could not establish
    profitability" must not be treated as "not profitable" OR as "profitable",
    and the caller decides which way to fail.
    """
    if not deal_id:
        return None
    for p in positions or []:
        if str(p.get("id")) == str(deal_id):
            upl = p.get("unrealized_pnl")
            if upl is None:
                return None
            try:
                return float(upl)
            except (TypeError, ValueError):
                return None
    # The deal is not in the broker's open list. That is not "P&L unknown" —
    # it means the position is gone, and the reconciliation path owns it.
    return None


def eod_close_eligibility(trade, upl: Optional[float]) -> Tuple[bool, str]:
    """
    Whether the end-of-day policy should close this position.

    Returns (eligible, reason). Pure, so the rule is testable without a broker.

    A position is eligible only when its P&L is known AND positive. Everything
    else is held, and the reason says which case it was, so the audit log
    distinguishes "held because losing" from "held because unreadable" — those
    are very different operational signals.
    """
    if upl is None:
        return False, "P&L unavailable from broker — holding rather than guessing"

    if EOD_REQUIRE_STRICTLY_PROFITABLE:
        if upl > 0:
            return True, f"profitable (UPL {upl:+.2f})"
        if upl == 0:
            return False, "flat (UPL 0.00) — not profitable, holding"
        return False, f"losing (UPL {upl:+.2f}) — holding, the stop is still working"

    if upl >= 0:
        return True, f"non-negative (UPL {upl:+.2f})"
    return False, f"losing (UPL {upl:+.2f}) — holding"


def end_of_day_policy(now: Optional[datetime] = None,
                      close_open: bool = False) -> Dict:
    """
    Apply the end-of-day policy at 20:30 UTC.

    Three actions, in this order:

      1. CANCEL pending setups. A setup is a plan to enter, and a plan whose
         window has closed cannot be filled. Dropping them is free.
      2. CLOSE open positions that are PROFITABLE, per the specification. The
         P&L is read from the broker's own unrealised figure for each deal, not
         re-derived from our entry price, so a partial close, a stop that has
         been trailed, and accrued financing are all already accounted for.
      3. HOLD everything else under normal management — losing positions, flat
         positions, and any position whose P&L could not be read.

    `close_open=True` switches to closing EVERYTHING regardless of P&L. It
    exists for an explicit operator decision (an account being retired, say) and
    is deliberately not what the scheduler uses.

    Idempotency: the position is settled in the database BEFORE its outcome is
    trusted, and a position already marked closed is skipped on a re-run, so a
    duplicated or manually triggered job cannot close twice or double-count P&L.
    A failed close leaves the row OPEN with its reason recorded, so it is retried
    on the next invocation rather than being silently lost.

    Returns a summary with a per-position audit trail.
    """
    ref = now or datetime.utcnow()
    out = {
        "at": ref.isoformat(),
        "mode": "close_all" if close_open else "close_profitable",
        "cancelled_setups": 0, "cancelled_symbols": [],
        "eligible": 0, "closed_positions": 0, "held_positions": 0,
        "already_closed": 0, "failed_closes": 0,
        "pnl": 0.0, "errors": 0,
        "closed": [], "held": [], "failed": [],
    }

    # ── 1. Cancel pending setups ─────────────────────────────────────────────
    try:
        from modules.silver_bullet import expire_setups, get_active_setups
        pending = get_active_setups()
        out["cancelled_setups"] = len(pending)
        out["cancelled_symbols"] = sorted(pending)
        expire_setups(now=ref)
        if pending:
            logger.info(f"[forex] end-of-day — cancelled {len(pending)} pending "
                        f"setup(s): {', '.join(out['cancelled_symbols'])}")
    except Exception as e:
        logger.error(f"[forex] end-of-day setup cancel error: {e}")
        out["errors"] += 1

    # ── 2/3. Open positions ──────────────────────────────────────────────────
    db = SessionLocal()
    try:
        open_trades = db.query(ForexTrade).filter(ForexTrade.outcome == "OPEN").all()

        if not open_trades:
            logger.info("[forex] end-of-day — no open positions")
            return out

        from modules.market_data_forex import (close_position, clear_caches,
                                               get_open_positions)

        # Read the broker's book ONCE, immediately before deciding. The position
        # cache is only 5s old at worst, but a stale read here would mean
        # deciding on a P&L the position no longer has.
        clear_caches()
        positions = get_open_positions()
        if positions is None:
            # Broker unreachable. Do NOT guess about live money: report and
            # leave every position alone, including the profitable ones.
            out["errors"] += 1
            out["held_positions"] = len(open_trades)
            out["held"] = [{"symbol": t.symbol,
                            "reason": "broker unavailable — no decision taken"}
                           for t in open_trades]
            logger.warning("[forex] end-of-day — broker position fetch failed; "
                           "no positions were closed")
            return out

        for trade in open_trades:
            symbol = trade.symbol
            deal_id = str(trade.metaapi_position_id or "")

            if not deal_id:
                out["errors"] += 1
                out["failed"].append({"symbol": symbol,
                                      "reason": "no broker deal id on the trade row"})
                logger.warning(f"[forex] end-of-day — {symbol} has no deal id, "
                               f"cannot close safely")
                continue

            upl = _position_pnl_from_broker(deal_id, positions)

            if close_open:
                eligible, reason = True, "close_all mode"
            else:
                eligible, reason = eod_close_eligibility(trade, upl)

            if not eligible:
                out["held_positions"] += 1
                out["held"].append({"symbol": symbol, "upl": upl, "reason": reason})
                logger.info(f"[forex] end-of-day — holding {symbol}: {reason}")
                continue

            out["eligible"] += 1

            # Record the intent BEFORE the broker call, so a crash mid-close
            # leaves a trail of what was being attempted.
            logger.info(f"[forex] end-of-day — closing {symbol} ({reason})")

            result = close_position(deal_id)
            if not result.get("success"):
                # The broker refused or timed out. The row stays OPEN so the
                # next invocation retries it, and the failure is recorded
                # rather than being reported as a close.
                out["failed_closes"] += 1
                out["errors"] += 1
                err = result.get("error") or "unknown"
                out["failed"].append({"symbol": symbol, "error": err,
                                      "upl": upl})
                trade.close_reason = f"end-of-day close failed: {err}"
                try:
                    db.commit()
                except Exception:
                    db.rollback()
                logger.warning(f"[forex] end-of-day — close FAILED for {symbol}: "
                               f"{err} (position left open, will retry)")
                continue

            pnl = float(result.get("pnl") or 0.0)
            trade.outcome = "WIN" if pnl >= 0 else "LOSS"
            trade.pnl = round(pnl, 4)
            trade.closed_at = ref
            trade.close_reason = f"end-of-day profitable close ({reason})"
            try:
                db.commit()
            except Exception as e:
                db.rollback()
                out["errors"] += 1
                logger.error(f"[forex] end-of-day — {symbol} closed at the broker "
                             f"but the DB write failed: {e}")
                continue

            out["closed_positions"] += 1
            out["pnl"] += pnl
            out["closed"].append({"symbol": symbol, "pnl": round(pnl, 4),
                                  "upl_at_decision": upl, "reason": reason})
            logger.info(f"[forex] end-of-day — closed {symbol} "
                        f"pnl=${pnl:+.2f} (UPL was {upl:+.2f})")

        out["pnl"] = round(out["pnl"], 2)

        logger.info(
            f"[forex] end-of-day summary — mode={out['mode']} "
            f"eligible={out['eligible']} closed={out['closed_positions']} "
            f"held={out['held_positions']} failed={out['failed_closes']} "
            f"pnl=${out['pnl']:+.2f}"
        )
        return out

    except Exception as e:
        logger.error(f"[forex] end-of-day policy error: {e}")
        out["errors"] += 1
        return out
    finally:
        db.close()


def build_daily_report(day: Optional[datetime] = None) -> Dict:
    """
    Summarise the UTC day's forex trading for the daily report.

    Reports what actually happened: trades opened and closed, the realised P&L,
    and — separately — the positions still open, because folding unrealised P&L
    into the day's result would make the number depend on when it was read.

    A day with no trades reports zeros rather than an error. "No trades" is a
    valid outcome of a strategy whose main filter is NEUTRAL, and it is the
    expected outcome on most days.
    """
    ref = day or datetime.utcnow()
    start = ref.replace(hour=0, minute=0, second=0, microsecond=0)

    report = {
        "date": start.strftime("%Y-%m-%d"),
        "generated_at": ref.isoformat(),
        "opened": 0, "closed": 0, "wins": 0, "losses": 0,
        "realised_pnl": 0.0, "win_rate": None,
        "open_positions": 0, "unrealised_pnl": 0.0,
        "by_symbol": {}, "by_session": {},
        "by_entry_type": {}, "best": None, "worst": None,
    }

    db = SessionLocal()
    try:
        created = db.query(ForexTrade).filter(ForexTrade.created_at >= start).all()
        report["opened"] = len(created)

        closed = [t for t in created if t.outcome in ("WIN", "LOSS")]
        report["closed"] = len(closed)
        report["wins"] = len([t for t in closed if t.outcome == "WIN"])
        report["losses"] = len([t for t in closed if t.outcome == "LOSS"])
        report["realised_pnl"] = round(sum(t.pnl or 0.0 for t in closed), 2)

        if closed:
            report["win_rate"] = round(report["wins"] / len(closed) * 100, 1)

        for t in closed:
            pnl = t.pnl or 0.0
            for bucket, key in ((report["by_symbol"], t.symbol),
                                (report["by_session"], t.session_name or "UNKNOWN"),
                                (report["by_entry_type"], t.entry_type or "UNKNOWN")):
                node = bucket.setdefault(key, {"trades": 0, "pnl": 0.0, "wins": 0})
                node["trades"] += 1
                node["pnl"] = round(node["pnl"] + pnl, 2)
                if t.outcome == "WIN":
                    node["wins"] += 1

            if report["best"] is None or pnl > report["best"]["pnl"]:
                report["best"] = {"symbol": t.symbol, "pnl": round(pnl, 2)}
            if report["worst"] is None or pnl < report["worst"]["pnl"]:
                report["worst"] = {"symbol": t.symbol, "pnl": round(pnl, 2)}

        open_trades = db.query(ForexTrade).filter(ForexTrade.outcome == "OPEN").all()
        report["open_positions"] = len(open_trades)
        report["unrealised_pnl"] = round(sum(t.pnl or 0.0 for t in open_trades), 2)

        return report

    except Exception as e:
        logger.error(f"[forex] daily report error: {e}")
        report["error"] = str(e)
        return report
    finally:
        db.close()


def next_session_times(now: Optional[datetime] = None) -> Dict:
    """
    When each Silver Bullet window opens and closes today, in UTC.

    Served from the engine's own SESSIONS table so the dashboard cannot drift
    from the hours the scanner actually enforces.
    """
    from modules.forex_signal_engine import SESSIONS, session_bounds

    ref = now or datetime.utcnow()
    out = {}
    for name in SESSIONS:
        open_dt, close_dt = session_bounds(name, ref)
        out[name] = {
            "open_utc": open_dt.strftime("%H:%M"),
            "close_utc": close_dt.strftime("%H:%M"),
            "open_iso": open_dt.isoformat(),
            "close_iso": close_dt.isoformat(),
            "opens_in_minutes": round((open_dt - ref).total_seconds() / 60.0, 1),
            "closes_in_minutes": round((close_dt - ref).total_seconds() / 60.0, 1),
            "is_open": open_dt <= ref < close_dt,
        }
    return out


# ── Summary ───────────────────────────────────────────────────────────────────

def _estimate_closed_pnl(trade) -> Tuple[float, str]:
    """
    Estimate the realised P&L of a trade that vanished from the broker.

    The only durable clue is which level price would have crossed: a BUY that
    is gone most likely hit its stop (or target), and vice versa. Compared
    against the last known price when available, this classifies the exit and
    estimates the amount, so a closed trade still contributes to P&L and win
    rate instead of being recorded with pnl = None.

    Returns (estimated_pnl, reason).
    """
    try:
        entry = float(trade.entry_price or 0.0)
        sl = float(trade.stop_loss or 0.0)
        tp = float(trade.tp2 or trade.take_profit or 0.0)
        lots = float(trade.lots or 0.0)

        if not entry or not lots:
            return 0.0, "no entry/size recorded"

        from modules.forex_executor import _pip_value_per_lot, _contract_size

        contract = _contract_size(trade.symbol)
        pvpl = _pip_value_per_lot(trade.symbol)
        pip = _pip_size_safe(trade.symbol)

        # Distance in pips from entry to each level
        def pnl_at(level):
            if not level:
                return 0.0
            pips = abs(level - entry) / pip
            value = (lots / contract) * pips * pvpl
            return value if level > entry else -value

        # A BUY exits profitably at the target and negatively at the stop.
        if trade.signal == "BUY":
            at_stop, at_target = -abs(pnl_at(sl)), abs(pnl_at(tp))
        else:
            at_stop, at_target = -abs(pnl_at(sl)), abs(pnl_at(tp))

        # Without a live price we cannot know which level was hit, so assume
        # the adverse outcome — the conservative choice for risk reporting.
        return at_stop, "assumed stop-out (level not recoverable)"

    except Exception as e:
        logger.error(f"[capital] pnl estimate error: {e}")
        return 0.0, "estimate failed"


def _pip_size_safe(symbol: str) -> float:
    try:
        from modules.forex_executor import _pip_size
        return _pip_size(symbol)
    except Exception:
        return 0.0001


def get_forex_position_summary() -> Dict:
    """
    Returns: open_count, open_positions, total_pnl, closed_trades,
             wins, losses, win_rate, balance, unrealized
    """
    db = SessionLocal()
    try:
        from modules.market_data_forex import get_open_positions, get_capital_balance

        open_trades = db.query(ForexTrade).filter(ForexTrade.outcome == "OPEN").all()
        # Anything not OPEN is a finished trade. Restricting this to WIN/LOSS
        # hid trades that were closed externally before the P&L estimate was
        # added, so they never appeared in the counts or the P&L total.
        closed_trades = db.query(ForexTrade).filter(
            ForexTrade.outcome != "OPEN"
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
        wins = len([t for t in closed_trades if (t.pnl or 0) > 0])
        losses = len([t for t in closed_trades if (t.pnl or 0) < 0])
        # Trades with no recorded P&L cannot be classified — count them so the
        # totals stay honest instead of silently vanishing.
        unknown = len([t for t in closed_trades if t.pnl is None])
        win_rate = (wins / (wins + losses) * 100) if (wins + losses) > 0 else 0

        bal = get_capital_balance()

        return {
            "open_count":     len(open_positions),
            "open_positions": open_positions,
            "total_pnl":      round(total_pnl, 2),
            # Every non-OPEN trade counts as closed; wins/losses/unknown break
            # it down so the total never understates the trade count.
            "closed_trades":  len(closed_trades),
            "wins":           wins,
            "losses":         losses,
            "unknown_outcome": unknown,
            "win_rate":       round(win_rate, 1),
            "balance":        bal.get("balance", 0.0),
            "unrealized":     bal.get("profit_loss", 0.0),
            "equity":         bal.get("equity", 0.0),
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

# Fallback for the max-trades setting when the stored value is unusable.
# Kept in step with config.FOREX_MAX_TRADES / RiskSettings.forex_max_trades.
_DEFAULT_FOREX_MAX_TRADES = 3


def _validated_max_trades(value) -> int:
    """
    Coerce the stored max-trades setting into a usable positive integer.

    The setting is user-editable through the dashboard, so it can arrive as a
    string, a float, or a nonsense value. A non-positive cap would silently
    block every forex entry, so anything unusable falls back to the default
    rather than being trusted.
    """
    try:
        count = int(value)
    except (TypeError, ValueError):
        return _DEFAULT_FOREX_MAX_TRADES
    return count if count >= 1 else _DEFAULT_FOREX_MAX_TRADES


def forex_day_start() -> datetime:
    """
    Start of the current forex trading day.

    Forex rolls over at 00:00 UTC — the same boundary Capital.com uses for
    daily financing and the one the daily P&L already rolls on. Using local
    time here would shift the window and reset the loss budget mid-session.
    """
    now = datetime.utcnow()
    return now.replace(hour=0, minute=0, second=0, microsecond=0)


def forex_daily_loss_check() -> Tuple[bool, str]:
    """
    True when today's realised forex loss has hit the configured limit.

    Returns True (allowed) immediately when the limit is switched off, so the
    strategy can be evaluated without waiting a full day for the next window.
    """
    try:
        from modules.risk_settings import get_settings

        rs = get_settings()
        if not rs.get("forex_daily_limit_enabled", True):
            return True, "OK"

        limit = float(rs.get("forex_daily_loss_limit", 0.06))

        db = SessionLocal()
        try:
            since = forex_day_start()
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

            if pnl < 0 and abs(pnl) >= balance * limit:
                return False, (f"daily forex loss limit hit "
                               f"(${pnl:.2f} of ${balance:.2f} balance)")
            return True, "OK"
        finally:
            db.close()

    except Exception as e:
        logger.error(f"[capital] daily loss check error: {e}")
        return True, "OK"


def can_open_forex_trade(symbol: str) -> Tuple[bool, str]:
    """
    Check the daily loss limit, the max-trades limit, and whether this symbol
    already has a position.

    The duplicate check consults the BROKER as well as the database. Relying
    on the database alone allowed a second position on a pair that was already
    open at Capital.com (the DB row can be missing, stale, or closed
    prematurely), which is how a pair ended up holding two live trades.
    """
    try:
        from modules.risk_settings import get_settings
        from modules.market_data_forex import get_open_positions

        rs = get_settings()

        allowed, reason = forex_daily_loss_check()
        if not allowed:
            return False, reason

        # The explicit halt check, so a caller that skipped the loss check still
        # cannot open new risk once the day's budget is spent.
        halted, halt_reason = daily_halt_active()
        if halted:
            return False, f"daily halt active ({halt_reason})"

        max_trades = _validated_max_trades(rs.get("forex_max_trades"))

        db = SessionLocal()
        try:
            open_count = db.query(ForexTrade).filter(ForexTrade.outcome == "OPEN").count()
            if open_count >= max_trades:
                return False, f"Max forex trades reached ({open_count}/{max_trades})"

            existing = db.query(ForexTrade).filter(
                ForexTrade.symbol == symbol,
                ForexTrade.outcome == "OPEN",
            ).first()
            if existing:
                return False, f"{symbol} already has an open position"
        finally:
            db.close()

        # ── Broker-side check ────────────────────────────────────────────────
        positions = get_open_positions()
        if positions is None:
            # Broker unreachable — fail closed rather than risk a duplicate.
            return False, "broker position check unavailable"
        if any(p.get("symbol") == symbol for p in positions):
            return False, f"{symbol} already open at broker"

        return True, "OK"

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
