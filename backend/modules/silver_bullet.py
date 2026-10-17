"""
backend/modules/silver_bullet.py
ICT Silver Bullet + Volume Profile confluence.

Replaces the CRT pullback strategy. Trades institutional liquidity sweeps
during three fixed session windows, confirmed by volume profile levels and
a market structure shift, entering on the fair value gap left behind.

Pipeline per symbol:
  1. Session window filter      — only 08:00-09:00, 15:00-16:00, 19:00-20:00 UTC
  2. Daily H4 bias              — computed once at 07:00 UTC, NEUTRAL = no trade
  3. Session liquidity marks    — swing high/low from the 5m before the window
  4. Liquidity sweep            — wick beyond the swing, close back inside
  5. Market structure shift     — close beyond the opposing swing within 3 candles
  6. Fair value gap             — imbalance formed after the sweep
  7. Volume profile confluence  — FVG graded against POC / VAH / VAL
  8. Entry                      — market order when price returns into the FVG
  9. Confidence score           — must clear 88 to trade

Synchronous only — no asyncio.

This module ORCHESTRATES; it does not implement the strategy. Sessions, sweep,
MSS, FVG, confluence, confidence, the 88 gate, the setup state machine and the
FVG-retest entry all live in `modules.forex_signal_engine`, which is the single
implementation. They are re-exported below so existing callers and the
dashboard keep working, and so a second copy of the rules can never drift out
of step with the first.

What stays here is the day-scoped orchestration the engine has no opinion
about: the H4 daily bias and its cache, the pre-session liquidity marks, the
scan loop, and the pending-setup store the scheduler reads.
"""
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, List, Tuple

import pandas as pd

from modules.volume_profile import (calculate_session_volume_profile,
                                    check_fvg_confluence,
                                    classify_price_position,
                                    gateable,
                                    previous_day_profile,
                                    previous_day_bounds,
                                    slice_utc_window,
                                    utc_date_key,
                                    utc_day_bounds)

# ── The strategy, from its single implementation ──────────────────────────────
from modules.forex_signal_engine import (  # noqa: F401
    CONFIDENCE_BASE,
    ELITE_CONFIDENCE,
    FVG_MAX_AGE,
    MIN_CONFIDENCE,
    MIN_SWEEP_BODY_PCT,
    MSS_MAX_CANDLES,
    NEWS_BLACKOUT_WINDOWS,
    SESSIONS,
    SL_ATR_BUFFER,
    SL_MAX_ATR,
    STATE_EXPIRED,
    STATE_FVG_FOUND,
    STATE_IN_TRADE,
    STATE_INVALID,
    STATE_MSS_CONFIRMED,
    STATE_SWEEP_DETECTED,
    STATE_WAITING,
    STRONG_CONFIDENCE,
    SWING_LOOKBACK,
    TERMINAL_STATES,
    advance_setup,
    build_setup,
    calculate_atr,
    calculate_confidence,
    check_entry_retest,
    closed_candles_only,
    current_session,
    detect_liquidity_sweep,
    detect_mss,
    detect_msss,
    expire_setup,
    find_fvg_after_sweep,
    in_news_blackout,
    invalidate_setup,
    is_executable,
    new_setup,
    session_bounds,
    session_minutes_until_open,
    session_schedule,
    session_time_remaining,
    sessions_opening_within,
    setup_is_expired,
    volume_profile_confluence,
    volume_profile_gateable,
)

logger = logging.getLogger(__name__)

# H4 structure window and the EMA the spec requires the close to clear.
H4_STRUCTURE_BARS   = 50
H4_EMA_PERIOD       = 50

# How far before a window opens its liquidity levels are marked. Levels taken
# from inside the window are not the pre-session pools the strategy sweeps.
PRESESSION_LOOKBACK_MIN = 30

# ── Caches ────────────────────────────────────────────────────────────────────
_daily_bias: Dict[str, Dict] = {}
_session_levels: Dict[str, Dict] = {}      # session -> {symbol: levels}
_session_levels_date: Dict[str, str] = {}  # session -> UTC date key of the marks
_active_setups: Dict[str, Dict] = {}


# `check_entry_in_fvg` is the name the scheduler already calls; the engine calls
# the same function `check_entry_retest`. `_closed_only` is the same look-ahead
# guard the engine exports as `closed_candles_only`.
check_entry_in_fvg = check_entry_retest
_closed_only = closed_candles_only


# ══════════════════════════════════════════════════════════════════════════════
#  LAYER 2 — DAILY BIAS (H4 structure + volume profile)
# ══════════════════════════════════════════════════════════════════════════════

def _ema(series: pd.Series, period: int = 50) -> float:
    if series is None or len(series) < period:
        return 0.0
    val = series.ewm(span=period, adjust=False).mean().iloc[-1]
    return float(val) if pd.notna(val) else 0.0


def _swings(df: pd.DataFrame, lookback: int = 3):
    """
    Positional indices of confirmed swing highs and lows.

    A swing needs `lookback` bars on BOTH sides, so the newest `lookback` bars
    can never be confirmed. The scan loop already stops short of the end for
    exactly that reason and must keep doing so.
    """
    highs, lows = [], []
    n = len(df)
    h = df["high"].astype(float).values
    l = df["low"].astype(float).values
    for i in range(lookback, n - lookback):
        if all(h[i] > h[i - j] for j in range(1, lookback + 1)) and \
           all(h[i] > h[i + j] for j in range(1, lookback + 1)):
            highs.append(i)
        if all(l[i] < l[i - j] for j in range(1, lookback + 1)) and \
           all(l[i] < l[i + j] for j in range(1, lookback + 1)):
            lows.append(i)
    return highs, lows


def _consecutive_runs(df: pd.DataFrame, sh, sl) -> Tuple[int, int, int, int]:
    """
    (hh, hl, ll, lh) run lengths, walking backwards from the newest swing.

    A run of 1 transition means two swings where the second is the higher (or
    lower) one, i.e. the "at least 2 consecutive Higher Highs" the spec asks
    for. Counting swings rather than transitions would require three swings and
    would silently raise the bar the spec set.
    """
    hh = hl = ll = lh = 0
    for i in range(len(sh) - 1, 0, -1):
        if df["high"].iloc[sh[i]] > df["high"].iloc[sh[i - 1]]:
            hh += 1
        else:
            break
    for i in range(len(sl) - 1, 0, -1):
        if df["low"].iloc[sl[i]] > df["low"].iloc[sl[i - 1]]:
            hl += 1
        else:
            break
    for i in range(len(sl) - 1, 0, -1):
        if df["low"].iloc[sl[i]] < df["low"].iloc[sl[i - 1]]:
            ll += 1
        else:
            break
    for i in range(len(sh) - 1, 0, -1):
        if df["high"].iloc[sh[i]] < df["high"].iloc[sh[i - 1]]:
            lh += 1
        else:
            break
    return hh, hl, ll, lh


def identify_h4_structure(h4_df: pd.DataFrame,
                          structure_bars: int = H4_STRUCTURE_BARS,
                          ema_period: int = H4_EMA_PERIOD
                          ) -> Tuple[str, int]:
    """
    H4 market structure over the most recent `structure_bars` CLOSED candles.

    Returns (bias, strength) where bias is BULLISH / BEARISH / NEUTRAL and
    strength is the number of confirmed HH/HL (or LL/LH) transitions.

    The spec's three conditions, all of which must hold:
      1. at least 2 consecutive Higher Highs AND 2 consecutive Higher Lows
         (the bearish mirror for a short bias), and
      2. close above EMA50 for a long bias, below it for a short bias.

    NEUTRAL is returned whenever any condition fails. That is a deliberate
    outcome, not a failure: NEUTRAL means "no trade today" and is the single
    most effective filter in the strategy, because it removes every symbol
    whose higher timeframe does not agree with the intended direction.
    """
    try:
        if h4_df is None or len(h4_df) < 20:
            return "NEUTRAL", 0

        df = h4_df.reset_index(drop=True).tail(structure_bars).reset_index(drop=True)
        sh, sl = _swings(df)

        if len(sh) < 2 or len(sl) < 2:
            return "NEUTRAL", 0

        price = float(df["close"].iloc[-1])
        ema50 = _ema(df["close"], ema_period)

        hh, hl, ll, lh = _consecutive_runs(df, sh, sl)

        # "2 consecutive Higher Highs" = 1 upward transition = 2 swings.
        hh_count = hh + 1 if hh else 0
        hl_count = hl + 1 if hl else 0
        ll_count = ll + 1 if ll else 0
        lh_count = lh + 1 if lh else 0

        if hh_count >= 2 and hl_count >= 2 and ema50 > 0 and price > ema50:
            return "BULLISH", min(hh_count, hl_count)
        if ll_count >= 2 and lh_count >= 2 and ema50 > 0 and price < ema50:
            return "BEARISH", min(ll_count, lh_count)
        return "NEUTRAL", 0

    except Exception as e:
        logger.error(f"[bias] H4 structure error: {e}")
        return "NEUTRAL", 0


def calculate_daily_bias(symbol: str) -> Optional[Dict]:
    """
    Build today's bias record for one symbol.

    Three inputs, all from CLOSED candles only:
      H4 structure  — bias + strength (see identify_h4_structure)
      prior-day VP  — POC/VAH/VAL from the PREVIOUS UTC DAY's H1 candles
      current price — the last closed H4 close

    The bias record is keyed to the current UTC date so a record computed
    yesterday can never be mistaken for today's.
    """
    try:
        from modules.candle_provider import get_candles

        date_key = utc_date_key()

        h4 = _closed_only(get_candles(symbol, timeframe="4h", limit=60), "4h")
        h4_bias, strength = identify_h4_structure(h4)

        if h4_bias == "NEUTRAL":
            record = {
                "symbol": symbol,
                "h4_bias": "NEUTRAL",
                "strength": 0,
                "vp_levels": None,
                "vp_levels_valid": False,
                "vp_levels_trusted": False,
                "vp_bias": "UNKNOWN",
                "price_position": "UNKNOWN",
                "h4_close": None,
                "ema50": None,
                "session_date": date_key,
                "computed_at": datetime.utcnow().isoformat(),
                "volume_source": None,
            }
            _daily_bias[symbol] = record
            logger.info(f"[bias] {symbol} H4: NEUTRAL — no trade today")
            return record

        # Previous UTC day's profile, bounded explicitly on the UTC boundary.
        h1 = get_candles(symbol, timeframe="1h", limit=72)
        vp = previous_day_profile(h1, num_bins=50) if h1 is not None else None

        price = float(h4["close"].iloc[-1]) if h4 is not None and len(h4) else 0.0
        position = classify_price_position(price, vp) if vp else "UNKNOWN"

        vp_bias = _vp_bias(vp, position, h4_bias)
        gate_ok, gate_reason = gateable(vp)

        record = {
            "symbol": symbol,
            "h4_bias": h4_bias,
            "strength": strength,
            "vp_levels": vp,
            "vp_levels_valid": bool(vp and vp.get("valid")),
            "vp_levels_trusted": bool(vp and vp.get("source_trusted")),
            "vp_bias": vp_bias,
            "price_position": position,
            "h4_close": round(price, 5),
            "ema50": round(_ema(h4["close"], H4_EMA_PERIOD), 5) if h4 is not None else None,
            "session_date": date_key,
            "computed_at": datetime.utcnow().isoformat(),
            "volume_source": vp.get("volume_source") if vp else None,
            "vp_gateable": gate_ok,
            "vp_gate_reason": gate_reason,
        }
        _daily_bias[symbol] = record

        if vp:
            logger.info(f"[vp] {symbol} ({vp['volume_source']}) POC={vp['poc']} "
                        f"VAH={vp['vah']} VAL={vp['val']}")
        else:
            logger.info(f"[bias] {symbol} no previous-day profile — "
                        f"VP confluence unavailable")
        logger.info(f"[bias] {symbol} H4: {h4_bias} — {strength} HH/HL or LL/LH "
                    f"confirmed, EMA50={record['ema50']}")
        return record

    except Exception as e:
        logger.error(f"[bias] {symbol} error: {e}")
        return None


def _vp_bias(vp: Optional[Dict], position: str, h4_bias: str) -> str:
    """Grade the value-area location against the H4 bias."""
    if not vp:
        return "NO_PROFILE"
    if position == "ABOVE_VALUE" and h4_bias == "BULLISH":
        return "STRONG_BUY"
    if position == "BELOW_VALUE" and h4_bias == "BEARISH":
        return "STRONG_SELL"
    if position == "INSIDE_VALUE":
        return "REDUCED"
    if position == "AT_POC":
        return "WAIT_REJECTION"
    return "ALIGNED"


def calculate_daily_bias_all_pairs(force: bool = False) -> int:
    """
    Compute the daily bias for every configured instrument.

    Skips symbols that already have a bias for the current UTC day unless
    `force` is set, so a restart mid-session does not re-poll every symbol and
    burn the venue's rate limit for data that cannot have changed.
    """
    from config import SILVER_BULLET_INSTRUMENTS

    todo = [s for s in SILVER_BULLET_INSTRUMENTS
            if force or get_daily_bias(s) is None]

    if not todo:
        tradeable = len([b for b in _daily_bias.values()
                         if b.get("h4_bias") != "NEUTRAL"])
        logger.info(f"[bias] all {len(SILVER_BULLET_INSTRUMENTS)} symbols already "
                    f"computed for {utc_date_key()} — {tradeable} tradeable")
        return 0

    logger.info(f"[bias] calculating daily bias for {len(todo)} symbols")
    count = 0
    for symbol in todo:
        try:
            if calculate_daily_bias(symbol):
                count += 1
        except Exception as e:
            # One bad symbol must not abort the sweep for the rest.
            logger.error(f"[bias] {symbol} error: {e}")

    tradeable = len([b for b in _daily_bias.values() if b.get("h4_bias") != "NEUTRAL"])
    logger.info(f"[bias] complete — {count} computed, {tradeable} tradeable today")
    return count


def get_daily_bias(symbol: str, now: Optional[datetime] = None) -> Optional[Dict]:
    """
    Today's stored bias for a symbol, or None when there is no bias for the
    current UTC day.

    The UTC date key is the entire staleness check. Anything computed on a
    previous day — or before a redeploy, which loses this in-memory dict — is
    reported as absent rather than as a valid bias, so a stale NEUTRAL cannot
    block trading and a stale BULLISH cannot authorise it.
    """
    rec = _daily_bias.get(symbol)
    if not rec:
        return None
    if rec.get("session_date") != utc_date_key(now):
        return None
    return rec


def get_all_daily_bias(now: Optional[datetime] = None) -> Dict[str, Dict]:
    """Only today's records, keyed by symbol."""
    key = utc_date_key(now)
    return {s: b for s, b in _daily_bias.items() if b.get("session_date") == key}


def reset_daily_cache(reason: str = "scheduled") -> None:
    """
    Clear all day-scoped in-memory state.

    Called at the UTC day boundary, and by the cycle whenever it notices the
    stored date has rolled over. Both routes exist because the boundary job can
    be missed: APScheduler with `coalesce` will skip a 00:01 cron entirely if
    the process was down, and the container may simply be asleep.
    """
    _daily_bias.clear()
    _session_levels.clear()
    _session_levels_date.clear()
    _active_setups.clear()
    logger.info(f"[silver] daily cache reset ({reason}) for {utc_date_key()}")


def ensure_current_day(now: Optional[datetime] = None) -> bool:
    """
    Reset if the day has rolled since the last reset.

    Returns True when a reset happened. Guarded on a stored key rather than on
    the contents of the dicts, so an all-NEUTRAL day (where the dict is
    populated but nothing is tradeable) is not mistaken for "never computed".

    In-memory only: after a redeploy the key is absent, the caches are already
    empty, and this correctly reports no reset was needed.
    """
    key = utc_date_key(now)
    last = _session_levels_date.get("__day__")
    if last == key:
        return False
    if last is not None:
        reset_daily_cache(f"UTC day rolled {last} -> {key}")
    _session_levels_date["__day__"] = key
    return last is not None


# ══════════════════════════════════════════════════════════════════════════════
#  LAYER 3 — SESSION LIQUIDITY MARKS
# ══════════════════════════════════════════════════════════════════════════════

def mark_session_liquidity(symbol: str, session_name: str,
                           now: Optional[datetime] = None) -> Optional[Dict]:
    """
    Record the swing high/low from the candles strictly BEFORE a session opens.

    These are the liquidity pools the session is expected to sweep. The window
    matters: taking the newest `SWING_LOOKBACK` candles instead — which is what
    this used to do — samples the first minutes of the session it is supposed to
    precede, so the "pool" was partly the move already in progress and the sweep
    test became partly circular.

    Every level is stamped with the UTC day it belongs to, so levels marked for
    yesterday cannot be swept against today.

    Returns the level record, or None when the window holds too few candles.
    """
    try:
        from modules.candle_provider import get_candles
        from config import SILVER_BULLET_INSTRUMENTS

        if symbol not in SILVER_BULLET_INSTRUMENTS:
            logger.debug(f"[silver] {symbol} not an instrument of this strategy")

        df = get_candles(symbol, timeframe="5m", limit=100)
        if df is None or len(df) < SWING_LOOKBACK + 1:
            return None

        open_dt, _close_dt = session_bounds(session_name, now)
        ref = now or datetime.utcnow()
        day_key = utc_date_key(ref)

        # Candles in [open - PRESESSION_LOOKBACK_MIN, open).
        if "timestamp" in df.columns:
            window_start = pd.Timestamp(open_dt, tz="UTC") - \
                pd.Timedelta(minutes=PRESESSION_LOOKBACK_MIN)
            window_end = pd.Timestamp(open_dt, tz="UTC")
            pre = slice_utc_window(df, window_start, window_end)
            if pre is None or len(pre) < SWING_LOOKBACK:
                # Before the window opens the 30-minute lookback is entirely in
                # the past; if it is empty the feed is short, so fall back to
                # the newest closed candles rather than marking nothing.
                logger.debug(f"[silver] {symbol} pre-session window empty — "
                             f"falling back to newest {SWING_LOOKBACK} candles")
                pre = df
        else:
            pre = df

        recent = pre.tail(SWING_LOOKBACK)
        if len(recent) < SWING_LOOKBACK:
            return None

        swing_high = float(recent["high"].max())
        swing_low = float(recent["low"].min())
        if not (swing_high > 0) or not (swing_low > 0) or swing_high <= swing_low:
            logger.debug(f"[silver] {symbol} degenerate liquidity range — skipping")
            return None

        levels = {
            "symbol": symbol,
            "session": session_name,
            "swing_high": swing_high,
            "swing_low": swing_low,
            "range": round(swing_high - swing_low, 5),
            "date": day_key,
            "marked_at": ref.isoformat(),
            "source_candles": len(recent),
        }
        _session_levels.setdefault(session_name, {})[symbol] = levels
        _session_levels_date[session_name] = day_key
        return levels

    except Exception as e:
        logger.error(f"[silver] {symbol} liquidity mark error: {e}")
        return None


def pre_session_mark_liquidity(session_name: str,
                               now: Optional[datetime] = None) -> int:
    """
    Mark session liquidity for every instrument ahead of a window opening.

    Intended to run a few minutes before the window opens, so the levels are
    the pre-session pools rather than candles from inside the window. Safe to
    call repeatedly — each call rewrites the levels for that session and day.
    """
    from config import SILVER_BULLET_INSTRUMENTS

    logger.info(f"[silver] {session_name} pre-session liquidity marking")
    count = 0
    for symbol in SILVER_BULLET_INSTRUMENTS:
        try:
            if mark_session_liquidity(symbol, session_name, now):
                count += 1
        except Exception as e:
            logger.error(f"[silver] {symbol} mark error: {e}")
    logger.info(f"[silver] {session_name} marked {count} symbols")
    return count


def get_session_levels(symbol: str, session_name: str,
                       now: Optional[datetime] = None) -> Optional[Dict]:
    """
    Today's marked liquidity for a symbol and session, or None.

    A level marked on a previous UTC day is treated as absent, so a stale pool
    cannot be swept against today's candles.
    """
    levels = _session_levels.get(session_name, {}).get(symbol)
    if not levels:
        return None
    if levels.get("date") != utc_date_key(now):
        return None
    return levels


def clear_session_levels(session_name: Optional[str] = None) -> int:
    """Drop marked levels for one session, or all of them."""
    if session_name:
        removed = len(_session_levels.pop(session_name, {}))
        _session_levels_date.pop(session_name, None)
        return removed
    removed = sum(len(v) for v in _session_levels.values())
    _session_levels.clear()
    _session_levels_date.clear()
    return removed


# ══════════════════════════════════════════════════════════════════════════════
#  LAYERS 4 & 5 — SETUP DETECTION AND SCORING
#
#  These live in `modules.forex_signal_engine` and are imported at the top of
#  this module:
#
#      detect_liquidity_sweep   sweep of the pre-session swing, body-filtered
#      detect_mss / detect_msss market structure shift within 3 candles
#      find_fvg_after_sweep     the imbalance left behind, within 10 candles
#      calculate_confidence     the heuristic score (a RANKING, not a probability)
#      is_executable            the hard 88 floor
#      build_setup              the pipeline, returning a stateful setup record
#      check_entry_retest       the FVG-retest entry, idempotent per setup
#
#  They were previously duplicated here. Keeping one copy is the point: two
#  implementations of the same rule drift, and the drift is invisible because
#  both look correct in isolation.
# ══════════════════════════════════════════════════════════════════════════════


# ══════════════════════════════════════════════════════════════════════════════
#  ACTIVE SETUPS
# ══════════════════════════════════════════════════════════════════════════════

def store_active_setup(symbol: str, setup: Dict) -> None:
    _active_setups[symbol] = setup


def get_active_setups() -> Dict[str, Dict]:
    return _active_setups.copy()


def clear_active_setup(symbol: str) -> None:
    _active_setups.pop(symbol, None)


def expire_setups(session_name: Optional[str] = None,
                  now: Optional[datetime] = None) -> int:
    """
    Cancel setups that are past their expiry or have become invalid.

    The expiry rule itself is `forex_signal_engine.setup_is_expired` — the
    session CLOSE, or the UTC day roll. It is not re-derived here, so the store
    and the engine can never disagree about whether a setup is still live.

    A cancelled setup is marked EXPIRED rather than silently deleted, so the
    reason it stopped being tradeable survives in the record.
    """
    ref = now or datetime.utcnow()
    expired = 0
    for symbol, setup in list(_active_setups.items()):
        if session_name and setup.get("session") != session_name:
            continue
        if setup.get("state") in TERMINAL_STATES:
            # Already finished; drop it so the store does not grow all day.
            _active_setups.pop(symbol, None)
            continue
        if setup_is_expired(setup, ref):
            expire_setup(setup, ref)
            _active_setups.pop(symbol, None)
            expired += 1
    if expired:
        logger.info(f"[silver] expired {expired} setups past window close or day roll")
    return expired



# ══════════════════════════════════════════════════════════════════════════════
#  LAYER 10 — MAIN SCAN
# ══════════════════════════════════════════════════════════════════════════════

def run_silver_bullet_scan(session_name: str,
                           now: Optional[datetime] = None) -> int:
    """
    Scan every instrument for a Silver Bullet setup during an open session.

    Returns the number of new setups stored. Candles come from the provider
    seam so the same detector works on Capital.com FX/metals and on Binance
    crypto.
    """
    from config import SILVER_BULLET_INSTRUMENTS
    from modules.candle_provider import get_candles

    if current_session(now) != session_name:
        return 0

    blocked, label = in_news_blackout(now)
    if blocked:
        logger.info(f"[silver] {session_name} inside news blackout {label} — "
                    f"no new setups")
        return 0

    logger.info(f"[silver] {session_name} window OPEN — scanning "
                f"{len(SILVER_BULLET_INSTRUMENTS)} symbols")
    stored = 0

    for symbol in SILVER_BULLET_INSTRUMENTS:
        try:
            if symbol in _active_setups:
                continue

            # An instrument the venue cannot actually trade is skipped rather
            # than scanned: a setup on it could never be filled, and putting one
            # on the dashboard would advertise a trade that cannot happen.
            from modules.forex_executor import execution_adapter_for
            adapter = execution_adapter_for(symbol)
            if adapter is None:
                logger.warning(f"[silver] {symbol} has no execution adapter — "
                               f"skipping (unsupported instrument)")
                continue

            bias_data = get_daily_bias(symbol, now)
            if not bias_data or bias_data.get("h4_bias") == "NEUTRAL":
                continue

            # Duplicate/limit guards are per venue. Capital.com positions go
            # through the broker-side check; crypto uses its own open-trade and
            # daily-drawdown limits, which are the same controls the crypto
            # strategy already enforced.
            if adapter == "capital":
                from modules.forex_position_manager import can_open_forex_trade
                allowed, _reason = can_open_forex_trade(symbol)
                if not allowed:
                    continue
            else:
                from modules.position_manager import (can_reenter,
                                                      daily_drawdown_check)
                if not daily_drawdown_check():
                    logger.info(f"[silver] {symbol} crypto daily drawdown limit "
                                f"reached — skipping")
                    continue
                # `can_reenter` reads the cooldown table, so it needs a session.
                # A failure to open one must skip the symbol rather than trade
                # without the cooldown check.
                from database import SessionLocal
                db = SessionLocal()
                try:
                    allowed, _reason = can_reenter(symbol, db)
                finally:
                    db.close()
                if not allowed:
                    continue

            session_levels = get_session_levels(symbol, session_name, now)
            if not session_levels:
                mark_session_liquidity(symbol, session_name, now)
                session_levels = get_session_levels(symbol, session_name, now)
                if not session_levels:
                    continue

            df_5m = get_candles(symbol, timeframe="5m", limit=50)
            if df_5m is None or len(df_5m) < 20:
                continue

            # The engine runs the whole pipeline and always returns a record,
            # so a rejection comes back naming the stage that refused it rather
            # than as an unexplained None.
            setup = build_setup(symbol, df_5m, session_levels, bias_data,
                                session_name, now)

            if not setup.get("executable"):
                logger.debug(f"[silver] {symbol} {session_name} rejected at "
                             f"{setup.get('state')}: {setup.get('reject_reason')}")
                continue

            # Carry the bias context the entry path and the dashboard read.
            setup["bias"] = bias_data["h4_bias"]
            setup["bias_strength"] = bias_data.get("strength", 0)
            setup["vp_gateable"] = bool(bias_data.get("vp_gateable"))
            setup["vp_gate_reason"] = bias_data.get("vp_gate_reason")

            store_active_setup(symbol, setup)
            stored += 1

            vp = bias_data.get("vp_levels") or {}
            logger.info(f"[silver] {symbol} {session_name} "
                        f"conf={setup['confidence']}% — SETUP STORED "
                        f"(state={setup['state']}, vp={setup['vp_confluence']}, "
                        f"source={vp.get('volume_source')}) waiting for FVG entry")

        except Exception as e:
            logger.error(f"[silver] {symbol} error: {e}")

    logger.info(f"[silver] {session_name} scan complete — {stored} new setups")
    return stored



# LAYER 6/7 — ENTRY, STOPS AND TARGETS
#
# The entry, its stop and its three targets live in `forex_signal_engine`
# (`check_entry_retest`, exported here as `check_entry_in_fvg`) together with
# the ATR it is sized from. There is no second copy here.
