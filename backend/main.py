"""
backend/main.py - COMPLETE CORRECT VERSION
WeltBot v5.0
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from apscheduler.schedulers.background import BackgroundScheduler
from database import engine, Base, SessionLocal, run_light_migrations
from models import SignalCache, BotState, Trade
from routers import signals, trades, analytics, forex, crypto_strategy
# AUTH DISABLED — re-enable later by importing + including auth.router below
# from routers import auth
from config import MAX_OPEN_TRADES, SCAN_INTERVAL_MIN, BINANCE_TESTNET, DAILY_DRAWDOWN_LIMIT
from datetime import datetime
from typing import Dict, Optional
import json, logging, os, sys, threading

# The strategy's session table and the end-of-day clock come from the modules
# that ENFORCE them, so the schedule cannot drift from the rules. A second copy
# of the hours here is how a scanner ends up running outside its window.
from modules.forex_signal_engine import SESSIONS
from modules.forex_position_manager import EOD_HOUR, EOD_MINUTE, EOD_NO_NEW_ENTRIES_HOUR
from modules.forex_executor import (STRATEGY_LEGACY_CRT, STRATEGY_SILVER_BULLET,
                                    legacy_entries_enabled as _legacy_entries_enabled)

# Without this, every logger.info()/logger.warning() call in the modules is
# silently discarded — uvicorn only configures its own loggers, so the CRT
# trend/sweep/entry diagnostics never reached the Railway logs.
# Streams to stdout so Railway tags them [inf] rather than [err].
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
    stream=sys.stdout,
    force=True,
)

Base.metadata.create_all(bind=engine)
run_light_migrations()

app = FastAPI(title="WeltBot", version="5.0.0")

# CORS - restrict to your Vercel domain in production
ALLOWED_ORIGINS = os.getenv("ALLOWED_ORIGINS", "https://weltbot.vercel.app,http://localhost:5173").split(",")

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(signals.router)
app.include_router(trades.router)
app.include_router(analytics.router)
# AUTH DISABLED — app.include_router(auth.router)
app.include_router(forex.router)
app.include_router(crypto_strategy.router)

_last_scan_log  = []
_active_setups: dict = {}
_forex_active_setups: dict = {}

# ── Diagnostics ───────────────────────────────────────────────────────────────
# Bounded ring of the most recent signal evaluations. Populated by the entry
# checks and by execution guards, so the dashboard can show WHY a signal was
# not traded (in either normal or diagnostic mode).
_diag_log: list = []
_diag_lock = threading.Lock()
_DIAG_MAX = 200


def record_diagnostic(market: str, symbol: str, decision: str, reason: str,
                      confidence=None, strategy: str | None = None) -> None:
    """
    Append one signal evaluation to the diagnostic ring.

    `decision` is PASS (signal accepted), REJECT (signal produced but blocked),
    or SKIP (no signal / nothing to do). Kept in memory only — this is an
    observability aid, not trading state, so it is intentionally not persisted.
    """
    try:
        from modules.risk_settings import diagnostic_mode
        entry = {
            "time":       datetime.utcnow().isoformat(),
            "market":     market,
            "symbol":     symbol,
            "decision":   decision,
            "reason":     reason,
            "confidence": round(float(confidence), 1) if confidence is not None else None,
            "strategy":   strategy,
            "simulated":  bool(diagnostic_mode()),
        }
        with _diag_lock:
            _diag_log.append(entry)
            del _diag_log[:-_DIAG_MAX]
    except Exception as e:
        print(f"[diag] record error: {e}")


def get_diagnostics(limit: int = 50) -> list:
    with _diag_lock:
        return list(reversed(_diag_log[-max(1, min(int(limit), _DIAG_MAX)):]))


def clear_diagnostics() -> int:
    with _diag_lock:
        n = len(_diag_log)
        _diag_log.clear()
    return n


def execution_blocked(symbol: str, market: str) -> str | None:
    """
    Central pre-execution guard. Returns a reason when an order must NOT be
    sent, or None when normal trading may proceed.

    Every order-submitting route calls this, so diagnostic mode cannot be
    bypassed by hitting a manual endpoint (the scan loops and the manual
    execute/close routes all funnel through here).
    """
    from modules.risk_settings import get_settings, diagnostic_mode

    if diagnostic_mode():
        return "diagnostic mode — evaluation only, order suppressed"
    if not get_settings().get(f"{market}_enabled", True):
        return f"{market} trading disabled in settings"
    return None


def guard_order(symbol: str, market: str) -> dict | None:
    """
    Convenience wrapper: returns an error payload when execution is blocked,
    and records the attempt in the diagnostic ring.
    """
    reason = execution_blocked(symbol, market)
    if reason:
        record_diagnostic(market, symbol, "REJECT", reason)
        return {"success": False, "error": reason, "simulated": True,
                "diagnostic": True}
    return None

# Re-entrancy guards — prevent overlapping runs of the 60s entry checks
_job_locks = {
    "crypto_entry": threading.Lock(),
    "forex_entry":  threading.Lock(),
    "crypto_crt":   threading.Lock(),
    "forex_crt":    threading.Lock(),
    "level1":       threading.Lock(),
}


def _get_bot_state(db):
    state = db.query(BotState).first()
    if not state:
        state = BotState(is_running=1, paused=0)  # auto-start
        db.add(state)
        db.commit()
    return state


def safe_get_balance() -> float:
    try:
        from modules.market_data import get_balance
        return get_balance()
    except Exception as e:
        print(f"[bot] balance error: {e}")
        return 0.0


def _place_trade(sig: dict, balance: float, db) -> bool:
    global _last_scan_log
    from modules.risk_manager     import calculate_risk
    from modules.executor         import place_order
    from modules.position_manager import can_reenter, cooldown_log_once

    symbol = sig["symbol"]
    signal = sig["signal"]
    strategy = sig.get("strategy")

    # Diagnostic mode / market kill-switch — never reach the exchange.
    blocked = guard_order(symbol, "crypto")
    if blocked:
        print(f"[bot] {symbol} order suppressed: {blocked['error']}")
        return False

    allowed, reason = can_reenter(symbol, db)
    if not allowed:
        if cooldown_log_once(symbol, db):
            print(f"[bot] {symbol} blocked: {reason}")
        record_diagnostic("crypto", symbol, "REJECT", reason,
                          sig.get("confidence"), strategy)
        return False

    atr  = sig["market"].get("atr", 0)
    risk = calculate_risk(sig["market"]["price"], signal, sig["confidence"], atr, balance)

    sl_tp = sig.get("sl_tp")
    sl    = sl_tp["stop_loss"]   if sl_tp else risk["stop_loss"]
    tp    = sl_tp["take_profit"] if sl_tp else risk["take_profit"]

    if not sl or not tp:
        print(f"[bot] {symbol} no SL/TP — skipping")
        return False

    result = place_order(
        symbol=symbol, signal=signal,
        position_units=risk["position_size_units"],
        stop_loss=sl, take_profit=tp,
        confidence=sig["confidence"],
    )

    if result["success"]:
        _last_scan_log = [{"symbol":symbol,"signal":signal,"confidence":sig["confidence"],
                           "entry":result["fill_price"],"sl":sl,"tp":tp,
                           "time":datetime.utcnow().isoformat()}]
        _active_setups.pop(symbol, None)
        record_diagnostic("crypto", symbol, "PASS",
                          f"order placed @ {result['fill_price']}",
                          sig.get("confidence"), strategy)
        print(f"[bot] TRADE PLACED — {signal} {symbol} @ {result['fill_price']}")
        return True
    else:
        record_diagnostic("crypto", symbol, "REJECT",
                          f"order failed: {result.get('error')}",
                          sig.get("confidence"), strategy)
        print(f"[bot] order failed {symbol}: {result.get('error')}")
        return False


def level1_bos_scan():
    global _active_setups
    lock = _job_locks["level1"]
    if not lock.acquire(blocking=False):
        print("[L1] previous scan still active — skipping")
        return
    db = SessionLocal()
    try:
        state = _get_bot_state(db)
        if not state.is_running or state.paused:
            return
        from modules.universe      import get_universe
        from modules.signal_engine import scan_for_bos, ema_momentum_scan, scan_btc_eth_crt
        from modules.risk_settings import get_settings

        rs = get_settings()

        balance    = safe_get_balance()
        open_count = db.query(Trade).filter(Trade.outcome == "OPEN").count()
        max_trades = int(rs.get("crypto_max_trades", MAX_OPEN_TRADES))
        print(f"[L1] scanning — balance=${balance:.2f} open={open_count}/{max_trades}")

        if open_count >= max_trades:
            return

        # Age existing setups
        new_setups = {}
        for sym, setup in list(_active_setups.items()):
            age = setup.get("candle_age", 0) + 1
            if age > 15:
                continue
            setup["candle_age"] = age
            new_setups[sym] = setup

        for symbol in get_universe():
            if symbol in new_setups:
                continue
            try:
                # Every crypto pair uses the refined CRT pullback engine.
                # The SMC path remains as a fallback when CRT finds nothing.
                crt_setup = scan_btc_eth_crt(symbol)
                if crt_setup:
                    new_setups[symbol] = crt_setup
                    continue

                setup = scan_for_bos(symbol)
                if setup:
                    new_setups[symbol] = setup
                    continue
                mom = ema_momentum_scan(symbol)
                if mom:
                    new_setups[symbol] = {
                        "symbol":symbol,"direction":"bullish" if mom["signal"]=="BUY" else "bearish",
                        "timeframe":"5m","bos":mom["bos"],"fib":mom["fib"],"ob":mom["ob"],
                        "candle_age":0,"strategy":"EMA","direct_signal":mom,
                    }
            except Exception as e:
                print(f"[L1] error {symbol}: {e}")

        _active_setups = new_setups
        print(f"[L1] done — {len(new_setups)} active: {list(new_setups.keys())}")
    except Exception as e:
        print(f"[L1] cycle error: {e}")
    finally:
        db.close()
        lock.release()


def level2_entry_check():
    global _active_setups
    if not _active_setups:
        return
    db = SessionLocal()
    try:
        state = _get_bot_state(db)
        if not state.is_running or state.paused:
            return

        open_count = db.query(Trade).filter(Trade.outcome == "OPEN").count()
        if open_count >= MAX_OPEN_TRADES:
            return

        balance = safe_get_balance()
        if balance < 1.0:
            return

        from modules.signal_engine     import check_entry_for_setup, refresh_btc_eth_crt_entry
        from modules.position_manager  import daily_drawdown_check
        from modules.risk_settings     import get_settings

        rs = get_settings()

        # Crypto drawdown must only stop CRYPTO. Pausing the shared bot state
        # here also halted forex, so four crypto losses took the forex engine
        # offline for the rest of the day even though it was unaffected.
        # The dashboard's crypto limit is the value that actually applies —
        # daily_drawdown_check() only ever reads the crypto Trade table.
        # PRE-EXISTING DEFECT, corrected here: this referenced `DAILY_LOSS_LIMIT`,
        # which is not defined in main.py or config (the config name is
        # `DAILY_DRAWDOWN_LIMIT`). It would have raised NameError the first time
        # a crypto setup reached this line. The function is retired and
        # unreachable, so nothing changed in behaviour — but leaving a latent
        # crash in the file is a trap for whoever re-enables it.
        crypto_limit = float(rs.get("crypto_daily_loss_limit", DAILY_DRAWDOWN_LIMIT))
        if rs.get("crypto_daily_limit_enabled", True) and daily_drawdown_check(crypto_limit):
            print(f"[L2] crypto daily drawdown limit hit ({crypto_limit*100:.1f}%) "
                  f"— skipping crypto entries (forex unaffected)")
            return

        slots  = MAX_OPEN_TRADES - open_count
        placed = 0

        for symbol in list(_active_setups.keys()):
            if placed >= slots:
                break
            setup = _active_setups.get(symbol)
            if not setup:
                continue
            try:
                direct = setup.get("direct_signal")
                if direct:
                    if _place_trade(direct, balance, db):
                        placed += 1
                    _active_setups.pop(symbol, None)
                    continue

                # Refined CRT pullback setups (BTC/ETH) use their own entry
                # logic — the legacy SMC path expects 'bos'/'fib'/'ob' keys.
                if setup.get("crt_pullback"):
                    sig = refresh_btc_eth_crt_entry(setup)
                    if sig and _place_trade(sig, balance, db):
                        placed += 1
                    continue

                sig = check_entry_for_setup(setup)
                if sig:
                    if _place_trade(sig, balance, db):
                        placed += 1
                # Always remove after attempt — prevents infinite retry loop
                _active_setups.pop(symbol, None)
            except Exception as e:
                print(f"[L2] error {symbol}: {e}")
                _active_setups.pop(symbol, None)

        if placed > 0:
            print(f"[L2] {placed} trades placed")
    except Exception as e:
        print(f"[L2] cycle error: {e}")
    finally:
        db.close()


def check_positions():
    try:
        from modules.position_manager import check_and_exit_positions
        check_and_exit_positions()
    except Exception as e:
        print(f"[positions] error: {e}")


def refresh_signal_cache():
    db = SessionLocal()
    try:
        balance = safe_get_balance() or 5000.0
        from modules.universe      import get_universe
        from modules.signal_engine import compute_signal
        from modules.risk_manager  import calculate_risk

        for symbol in get_universe():
            try:
                sig  = compute_signal(symbol)
                atr  = sig["market"].get("atr", 0)
                risk = calculate_risk(sig["market"]["price"], sig["signal"], sig["confidence"], atr, balance)
                payload = json.dumps({"signal_data": sig, "risk_plan": risk})
                cached  = db.query(SignalCache).filter(SignalCache.asset == symbol).first()
                if cached: cached.payload = payload
                else:      db.add(SignalCache(asset=symbol, payload=payload))
                db.commit()
                print(f"[cache] refreshed {symbol}")
            except Exception as e:
                print(f"[cache] error {symbol}: {e}")
    finally:
        db.close()


def run_kronos_bias_update():
    """Update Kronos AI bias for all forex pairs"""
    from config import FOREX_ENABLED
    if not FOREX_ENABLED:
        return
    
    try:
        from modules.market_data_forex import get_candles
        from modules.kronos_engine import predict_bias
        from config import FOREX_PAIRS
        
        print(f"[kronos] updating bias for {len(FOREX_PAIRS)} pairs")
        
        for symbol in FOREX_PAIRS:
            try:
                df = get_candles(symbol, timeframe='1h', limit=400)
                if df is not None and len(df) >= 400:
                    predict_bias(symbol, df)
            except Exception as e:
                print(f"[kronos] error {symbol}: {e}")
        
        print("[kronos] bias update complete")
    except Exception as e:
        print(f"[kronos] update cycle error: {e}")


def run_crt_scan():
    """
    Refined CRT scan — H4 trend, H1 pullback range, sweep confirmation.

    DATA-ONLY during the Silver Bullet migration. It still discovers setups and
    still refreshes the CRT levels the dashboard reads, but the setups it finds
    are NOT armed for entry: `run_forex_entry_check` refuses to submit them, and
    `place_forex_order` refuses at the chokepoint. Arming them here would put
    tradeable-looking setups on the dashboard that can never be filled.
    """
    global _forex_active_setups
    from config import FOREX_ENABLED
    if not FOREX_ENABLED:
        return

    from modules.forex_executor import legacy_entries_enabled
    legacy_live = legacy_entries_enabled()

    lock = _job_locks["forex_crt"]
    if not lock.acquire(blocking=False):
        print("[crt] previous scan still active — skipping")
        return

    db = SessionLocal()
    try:
        state = _get_bot_state(db)
        if not state.is_running or state.paused:
            return

        from modules.crt_detector import scan_symbol_refined, validate_with_kronos, store_crt_level
        from modules.kronos_engine import get_cached_bias
        from config import FOREX_PAIRS
        from modules.market_data_forex import get_session

        print(f"[crt] scanning {len(FOREX_PAIRS)} pairs (H4 trend → H1 pullback → sweep)")

        # Capital.com rate-limits hard. If a 429 pause is active, skip the
        # whole cycle rather than hammering the API for every pair.
        pause = get_session().rate_limit_remaining()
        if pause > 0:
            print(f"[crt] Capital.com rate-limit pause active ({pause:.0f}s) — "
                  f"deferring scan")
            return

        for symbol in FOREX_PAIRS:
            try:
                if symbol in _forex_active_setups:
                    continue

                sweep = scan_symbol_refined(symbol)
                if not sweep:
                    continue

                bias = get_cached_bias(symbol)
                if not validate_with_kronos(sweep, bias):
                    continue

                sweep["confirm_timeframe"] = "15m"
                sweep["entry_timeframe"] = "5m"
                sweep["poi"] = None
                sweep["poi_status"] = "waiting"

                store_crt_level(sweep)
                if legacy_live:
                    _forex_active_setups[symbol] = sweep
                    print(f"[crt] {symbol} {sweep['trend_direction']} setup confirmed — "
                          f"{sweep['direction']} target={sweep['target']:.5f}")
                else:
                    # Levels refreshed for the dashboard; setup deliberately not
                    # armed, because nothing will fill it.
                    print(f"[crt] {symbol} {sweep['trend_direction']} setup found "
                          f"(data only — legacy entries disabled)")

            except Exception as e:
                print(f"[crt] error {symbol}: {e}")

        print(f"[crt] scan complete — {len(_forex_active_setups)} active setups")
    except Exception as e:
        print(f"[crt] scan cycle error: {e}")
    finally:
        db.close()
        lock.release()


def run_silver_bullet_cycle():
    """
    Generic Silver Bullet tick — the safety net behind the per-session jobs.

    The scheduled scanners run per session inside their own windows. This one
    exists for the startup thread and as a catch-all: it performs the day
    rollover and the pre-session marking that must happen even when no session
    is open, then delegates to the same scan body the session jobs use.

    It never scans outside a window — `_silver_bullet_scan_once` is only reached
    when `current_session` names a live window.
    """
    from config import FOREX_ENABLED
    if not FOREX_ENABLED:
        return

    try:
        from modules.silver_bullet import (current_session, ensure_current_day,
                                           expire_setups, pre_session_mark_liquidity,
                                           sessions_opening_within)

        now = datetime.utcnow()

        # UTC day rollover. APScheduler's 00:01 cron is skipped entirely when the
        # process slept through it, so the rollover is also detected here on
        # every tick rather than trusted to the cron alone.
        if ensure_current_day(now):
            print("[silver] UTC day rolled — daily state reset")

        # Mark each window's liquidity shortly BEFORE it opens, so the levels are
        # the pre-session pools rather than candles from inside the window.
        for name in sessions_opening_within(5, now):
            try:
                n = pre_session_mark_liquidity(name, now)
                print(f"[silver] {name} pre-session levels marked for {n} symbols")
            except Exception as e:
                print(f"[silver] {name} pre-session marking error: {e}")

        session = current_session(now)
        if session is None:
            expire_setups(now=now)
            return

        _silver_bullet_scan_once(session, now)
    except Exception as e:
        print(f"[silver] cycle error: {e}")


def run_silver_bullet_entry_check(now: Optional[datetime] = None):
    """
    Enter on active Silver Bullet FVG setups once price returns to the gap.

    `now` is injectable so the session and end-of-day guards are testable. They
    used to read the wall clock directly, which meant the guards could only be
    exercised by waiting for the right hour — so the one property that matters
    most (no entry outside a window) was the hardest to prove.
    """
    from config import FOREX_ENABLED, FOREX_MIN_CONF
    if not FOREX_ENABLED:
        return

    ref = now or datetime.utcnow()

    try:
        from modules.risk_settings import get_settings
        from modules.candle_provider import get_candles, get_current_price, is_binance
        from modules.market_data_forex import get_session
        from modules.silver_bullet import (
            check_entry_in_fvg,
            clear_active_setup,
            current_session,
            get_active_setups,
        )
        from modules.forex_executor import place_forex_order
        from modules.forex_position_manager import can_open_forex_trade, forex_block_log_once

        # NOTE: the Kronos confidence boost that used to sit here is REMOVED.
        # `run_kronos_bias_update` is retired, so `get_cached_bias` returns None
        # for every symbol and the boost was dead code — but leaving the call in
        # place would mean a stale cache entry (from a pre-migration process)
        # could still raise a Silver Bullet score, letting a retired engine
        # influence whether a live trade is taken. The score is now the
        # strategy's own.

        if current_session(ref) is None:
            for symbol in list(get_active_setups()):
                clear_active_setup(symbol)
            return

        # End-of-day cutoff. The last window closes at 20:00 UTC; a setup that
        # retests after that would be carried into the illiquid rollover with no
        # session left to develop in. Checked HERE as well as at the session
        # level because this job runs every 30 seconds and must not depend on
        # the scan job having cleaned up.
        if ref.hour >= EOD_NO_NEW_ENTRIES_HOUR:
            print(f"[silver-entry] past the {EOD_NO_NEW_ENTRIES_HOUR}:00 UTC "
                  f"cutoff — no new entries")
            for symbol in list(get_active_setups()):
                clear_active_setup(symbol)
            return

        # Capital.com pacing only applies to the Capital.com symbols; a Binance
        # symbol must not be deferred because the broker we are not calling is
        # throttled.
        pause = get_session().rate_limit_remaining()

        min_conf = float(get_settings().get("forex_min_confidence", FOREX_MIN_CONF))
        for symbol, setup in list(get_active_setups().items()):
            try:
                if setup.get("session") != current_session(ref):
                    continue

                if not is_binance(symbol):
                    # Crypto entries are ordered by the crypto entry path, which
                    # has its own sizing and duplicate handling. This job only
                    # executes the Capital.com side of the strategy.
                    if pause > 0:
                        print(f"[silver-entry] {symbol} rate-limit pause active "
                              f"({pause:.0f}s) — deferring")
                        continue

                    allowed, reason = can_open_forex_trade(symbol)
                    if not allowed:
                        if forex_block_log_once(symbol, reason):
                            print(f"[silver-entry] {symbol} blocked: {reason}")
                        record_diagnostic("forex", symbol, "REJECT", reason)
                        continue

                price = get_current_price(symbol)
                if not price:
                    continue

                df_5m = get_candles(symbol, timeframe="5m", limit=100)
                # `ref` is threaded through so the expiry check inside the entry
                # condition uses the same clock as the guards above. Reading the
                # wall clock here meant a test could not exercise the entry path
                # at a chosen time, and a delayed job could evaluate the setup
                # against a different instant than it was admitted on.
                signal = check_entry_in_fvg(setup, price, df_5m, now=ref)
                if not signal:
                    continue

                if signal["confidence"] < min_conf:
                    print(f"[silver-entry] {symbol} confidence too low: {signal['confidence']:.0f}%")
                    continue

                if is_binance(symbol):
                    # Crypto Silver Bullet entries go through the Binance path
                    # with the same confidence tiers as the FX side, sized in
                    # base-asset units on the exchange's step grid — a crypto
                    # quantity is not a Capital.com "lot" and must not be sized
                    # from the FX contract table.
                    #
                    # This covers EVERY enabled crypto symbol, not just BTC/ETH:
                    # the roster comes from the crypto universe, and the sizing
                    # reads each symbol's own step and minimum notional.
                    from modules.executor import calculate_silver_bullet_crypto_size
                    from modules.market_data import get_balance

                    balance = get_balance()
                    sizing = calculate_silver_bullet_crypto_size(
                        symbol, signal["entry_price"], signal["stop_loss"],
                        signal["confidence"], balance,
                    )
                    if not sizing["ok"]:
                        record_diagnostic("crypto", symbol, "REJECT",
                                          f"sizing: {sizing['reason']}",
                                          signal["confidence"])
                        print(f"[silver-entry] {symbol} crypto size rejected: "
                              f"{sizing['reason']}")
                        continue

                    crypto_result = place_crypto_order(
                        symbol, signal, sizing, balance
                    )
                    if crypto_result["success"]:
                        record_diagnostic(
                            "crypto", symbol, "PASS",
                            f"order placed @ {signal['entry_price']:.2f} "
                            f"qty={sizing['qty']}",
                            signal["confidence"], signal.get("entry_type"))
                        print(f"[crypto] ENTRY {signal['signal']} {symbol} "
                              f"qty={sizing['qty']} | conf={signal['confidence']:.0f}% | "
                              f"SL={signal['stop_loss']:.2f} TP3={signal['tp3']:.2f}")
                        clear_active_setup(symbol)
                    else:
                        record_diagnostic("crypto", symbol, "REJECT",
                                          f"order failed: {crypto_result.get('error')}",
                                          signal["confidence"])
                        print(f"[silver-entry] {symbol} crypto order failed: "
                              f"{crypto_result.get('error')}")
                    continue

                blocked = guard_order(symbol, "forex")
                if blocked:
                    print(f"[silver-entry] {symbol} order suppressed: {blocked['error']}")
                    continue

                # The bias argument is the strategy's own daily record, not the
                # retired Kronos bias — `place_forex_order` records it on the
                # trade row for the audit trail.
                result = place_forex_order(signal, {"h4_bias": setup.get("bias")},
                                           strategy=STRATEGY_SILVER_BULLET)
                if result["success"]:
                    record_diagnostic("forex", symbol, "PASS",
                                      f"order placed @ {signal['entry_price']:.5f}",
                                      signal["confidence"],
                                      signal.get("entry_type"))
                    print(f"[forex] ENTRY {signal['signal']} {symbol} @ {signal['entry_price']:.5f} | "
                          f"{signal['entry_type']} | conf={signal['confidence']:.0f}% | "
                          f"SL={signal['stop_loss']:.5f} | TP1={signal['tp1']:.5f} | TP2={signal['tp2']:.5f}")
                    clear_active_setup(symbol)
                else:
                    record_diagnostic("forex", symbol, "REJECT",
                                      f"order failed: {result.get('error')}",
                                      signal["confidence"])
                    print(f"[silver-entry] {symbol} order failed: {result.get('error')}")
            except Exception as e:
                print(f"[silver-entry] error {symbol}: {e}")
    except Exception as e:
        print(f"[silver-entry] cycle error: {e}")


def run_silver_bullet_bias():
    """
    07:00 UTC — compute the daily H4 bias and the previous-day volume profile.

    Runs before the first session opens so the scan never has to compute a bias
    mid-window, and so a slow or failing venue is discovered an hour before the
    first trade would have been taken.
    """
    from config import FOREX_ENABLED
    if not FOREX_ENABLED:
        return

    try:
        from modules.silver_bullet import calculate_daily_bias_all_pairs

        n = calculate_daily_bias_all_pairs()
        print(f"[silver] daily bias + volume profile computed for {n} symbols")
    except Exception as e:
        print(f"[silver] bias job error: {e}")


def run_silver_bullet_presession():
    """
    Prepare pre-session liquidity levels for whichever window opens next.

    07:55 / 14:55 / 18:55 UTC — five minutes before each window. Marking from
    outside the window is what makes the levels the pools the session sweeps
    rather than the move already in progress.
    """
    from config import FOREX_ENABLED
    if not FOREX_ENABLED:
        return

    try:
        from modules.silver_bullet import (pre_session_mark_liquidity,
                                           sessions_opening_within)

        now = datetime.utcnow()
        upcoming = sessions_opening_within(5, now)
        if not upcoming:
            print(f"[silver] no window opens within 5 minutes of "
                  f"{now:%H:%M} UTC — nothing to mark")
            return

        for name in upcoming:
            n = pre_session_mark_liquidity(name, now)
            print(f"[silver] {name} pre-session levels marked for {n} symbols")
    except Exception as e:
        print(f"[silver] pre-session job error: {e}")


def run_silver_bullet_scanner(session_name: str):
    """
    One session's scanner, run every five minutes inside that window only.

    The session name is bound at registration time and re-validated inside the
    scan, so a misfire, a coalesced run or a clock skew cannot let the London
    job trade the New York window. `run_silver_bullet_cycle` is kept as the
    generic entry point the startup thread calls.
    """
    from config import FOREX_ENABLED
    if not FOREX_ENABLED:
        return

    try:
        from modules.silver_bullet import current_session

        now = datetime.utcnow()
        active = current_session(now)
        if active != session_name:
            # Not an error: this job fires only inside its own window, but a
            # coalesced or delayed run can land outside it.
            print(f"[silver] {session_name} scanner skipped — active session is "
                  f"{active or 'none'} at {now:%H:%M} UTC")
            return

        _silver_bullet_scan_once(session_name, now)
    except Exception as e:
        print(f"[silver] {session_name} scanner error: {e}")


def _silver_bullet_scan_once(session_name: str, now: datetime) -> None:
    """The shared body of a session scan, used by both entry points."""
    from modules.silver_bullet import (calculate_daily_bias_all_pairs,
                                       expire_setups, get_daily_bias,
                                       in_news_blackout, run_silver_bullet_scan)
    from config import SILVER_BULLET_INSTRUMENTS

    # A bias computed at 07:00 can be missing if the process started later, so
    # it is topped up here rather than silently scanning with no direction.
    missing = [s for s in SILVER_BULLET_INSTRUMENTS if get_daily_bias(s, now) is None]
    if missing:
        print(f"[silver] {len(missing)} symbol(s) missing today's bias — computing")
        calculate_daily_bias_all_pairs()

    blocked, label = in_news_blackout(now)
    if blocked:
        print(f"[silver] {session_name} inside news blackout {label} — scan skipped")
        expire_setups(session_name, now)
        return

    run_silver_bullet_scan(session_name, now)
    expire_setups(session_name, now)


def run_end_of_day_policy():
    """
    20:30 UTC — cancel pending setups and report the open book.

    Open positions are deliberately NOT closed here: they keep their stop, their
    target and their trailing rule. See `end_of_day_policy` for why.
    """
    from config import FOREX_ENABLED
    if not FOREX_ENABLED:
        return

    try:
        from modules.forex_position_manager import end_of_day_policy

        result = end_of_day_policy()
        print(f"[forex] end-of-day — {result['cancelled_setups']} setup(s) "
              f"cancelled, {result['held_positions']} position(s) held under "
              f"management, {result['errors']} error(s)")
    except Exception as e:
        print(f"[forex] end-of-day job error: {e}")


def run_daily_report():
    """23:00 UTC — build and log the day's forex report."""
    from config import FOREX_ENABLED
    if not FOREX_ENABLED:
        return

    try:
        from modules.forex_position_manager import build_daily_report

        report = build_daily_report()
        print(f"[forex-report] {report['date']} — opened={report['opened']} "
              f"closed={report['closed']} W/L={report['wins']}/{report['losses']} "
              f"realised=${report['realised_pnl']:+.2f} "
              f"open={report['open_positions']} "
              f"unrealised=${report['unrealised_pnl']:+.2f}")
        for symbol, node in sorted(report["by_symbol"].items()):
            print(f"[forex-report]   {symbol}: {node['trades']} trades "
                  f"({node['wins']}W) ${node['pnl']:+.2f}")
    except Exception as e:
        print(f"[forex-report] job error: {e}")


def run_forex_entry_check():
    """
    Legacy CRT/SMC forex entry check — DISABLED as an order source.

    The Silver Bullet engine is the unified strategy. This job is kept
    registered only so its diagnostic logging and the `_forex_active_setups`
    bookkeeping continue to run for the dashboard; it does NOT submit orders.

    The lock is enforced in two places on purpose:

      * HERE, so the job returns early and does not waste broker API calls
        evaluating setups whose orders would be refused anyway; and
      * in `place_forex_order`, which is the chokepoint that actually sends the
        order, so any other caller someone adds later is covered too.

    Both fail closed: `legacy_entries_enabled()` returns False when the flag
    cannot be read.
    """
    global _forex_active_setups

    from modules.forex_executor import legacy_entries_enabled
    if not legacy_entries_enabled():
        if _forex_active_setups:
            print(f"[forex-entry] legacy CRT entries disabled during the Silver "
                  f"Bullet migration — {len(_forex_active_setups)} setup(s) held, "
                  f"no orders submitted")
            # The setups are stale by construction: nothing will ever fill them,
            # so keeping them would make the dashboard advertise tradeable
            # setups that cannot trade.
            _forex_active_setups = {}
        return

    if not _forex_active_setups:
        return

    lock = _job_locks["forex_entry"]
    if not lock.acquire(blocking=False):
        print("[forex-entry] previous run still active — skipping")
        return

    db = SessionLocal()
    try:
        state = _get_bot_state(db)
        if not state.is_running or state.paused:
            return

        from modules.market_data_forex import get_candles, get_current_price, get_session
        from modules.forex_signal_engine import check_entry_condition_refined
        from modules.forex_executor import place_forex_order
        from modules.forex_position_manager import can_open_forex_trade, forex_block_log_once
        from modules.kronos_engine import get_cached_bias
        from modules.risk_settings import get_settings

        # Weekend guard — forex liquidity collapses between the Friday close
        # and the Sunday reopen, so new entries are held back. Open positions
        # are still monitored and can still close.
        rs = get_settings()
        if rs.get("weekend_guard", True) and datetime.utcnow().weekday() >= 5:
            print("[forex-entry] weekend guard active — no new forex entries")
            return

        # Respect an active Capital.com rate-limit pause
        pause = get_session().rate_limit_remaining()
        if pause > 0:
            print(f"[forex-entry] rate-limit pause active ({pause:.0f}s) — deferring")
            return

        # Hard time budget so the job never overruns its 60s interval
        import time as _time
        deadline = _time.time() + 50

        for symbol in list(_forex_active_setups.keys()):
            if _time.time() > deadline:
                print("[forex-entry] time budget reached — deferring remaining setups")
                break
            try:
                setup = _forex_active_setups[symbol]
                trend = setup.get('trend_direction')
                if trend not in ('BULLISH', 'BEARISH'):
                    _forex_active_setups.pop(symbol, None)
                    continue

                allowed, reason = can_open_forex_trade(symbol)
                if not allowed:
                    if forex_block_log_once(symbol, reason):
                        print(f"[forex-entry] {symbol} blocked: {reason}")
                    record_diagnostic("forex", symbol, "REJECT", reason)
                    continue
                price = get_current_price(symbol)
                if not price:
                    continue

                # 15m is the primary entry timeframe, 5m is the refinement
                df_15m = get_candles(symbol, timeframe='15m', limit=100)
                df_5m = get_candles(symbol, timeframe='5m', limit=100)
                if df_15m is None and df_5m is None:
                    continue

                # Keep the H1 pullback context available to the entry logic
                if '_df_h1' not in setup:
                    setup['_df_h1'] = get_candles(symbol, timeframe='1h', limit=100)

                signal = check_entry_condition_refined(setup, price, df_15m, df_5m, trend)

                if signal:
                    bias = get_cached_bias(symbol)
                    if bias:
                        signal['confidence'] += bias.get('confidence_boost', 0)
                        signal['confidence'] = min(signal['confidence'], 99)

                    from config import FOREX_MIN_CONF
                    try:
                        from modules.risk_settings import get_settings
                        min_conf = float(get_settings().get("forex_min_confidence", FOREX_MIN_CONF))
                    except Exception:
                        min_conf = FOREX_MIN_CONF

                    if signal['confidence'] >= min_conf:
                        blocked = guard_order(symbol, "forex")
                        if blocked:
                            print(f"[forex-entry] {symbol} order suppressed: "
                                  f"{blocked['error']}")
                            continue
                        result = place_forex_order(signal, bias or {},
                                                   strategy=STRATEGY_LEGACY_CRT)
                        if result['success']:
                            record_diagnostic("forex", symbol, "PASS",
                                              f"order placed @ "
                                              f"{signal['entry_price']:.5f}",
                                              signal['confidence'],
                                              signal.get('entry_type'))
                            print(f"[forex] ENTRY {signal['signal']} {symbol} @ "
                                  f"{signal['entry_price']:.5f} | {signal['entry_type']} | "
                                  f"conf={signal['confidence']:.0f}% | "
                                  f"SL={signal['stop_loss']:.5f} | "
                                  f"TP1={signal['tp1']:.5f} | TP2={signal['tp2']:.5f}")
                            _forex_active_setups.pop(symbol, None)
                        else:
                            record_diagnostic("forex", symbol, "REJECT",
                                              f"order failed: {result.get('error')}",
                                              signal['confidence'])
                    else:
                        print(f"[forex-entry] {symbol} confidence too low: "
                              f"{signal['confidence']:.1f}%")
                        record_diagnostic("forex", symbol, "REJECT",
                                          f"confidence {signal['confidence']:.1f}% "
                                          f"< {min_conf:.0f}%",
                                          signal['confidence'])
                        _forex_active_setups.pop(symbol, None)

            except Exception as e:
                print(f"[forex-entry] error {symbol}: {e}")
                _forex_active_setups.pop(symbol, None)
        
    except Exception as e:
        print(f"[forex-entry] cycle error: {e}")
    finally:
        db.close()
        lock.release()


def place_crypto_order(symbol: str, signal: Dict, sizing: Dict,
                       balance: float) -> Dict:
    """
    Open a Binance position for a Silver Bullet crypto setup.

    Deliberately separate from `executor.place_order`, which the retired crypto
    strategy used: that function recomputes size from
    `calculate_risk_with_compounding` and applies its own leverage tiers, so
    routing Silver Bullet through it would override the tier the strategy chose.

    The Trade row records the same management state the FX side does, so
    `position_manager` can apply the five rules to it without special-casing.

    Preflight, in order: the shared strategy guard, the adapter check, then the
    exchange rules. Any failure refuses before an order is built.
    """
    db = SessionLocal()
    try:
        from modules.market_data import place_order_raw
        from modules.forex_executor import ADAPTER_BINANCE, execution_adapter_for
        from modules.strategy_guard import STRATEGY_SILVER_BULLET
        from models import Trade

        # Adapter preflight: a symbol whose venue cannot be resolved must never
        # reach the exchange.
        if execution_adapter_for(symbol) != ADAPTER_BINANCE:
            return {"success": False,
                    "error": f"{symbol} is not served by the Binance adapter"}

        side = "BUY" if signal["signal"] == "BUY" else "SELL"
        qty = sizing["qty"]

        result = place_order_raw(symbol, side, qty)
        if not result or not result.get("success"):
            err = (result or {}).get("error", "no response")
            return {"success": False, "error": err}

        fill = float(result.get("fill_price") or signal["entry_price"])
        risk_distance = abs(fill - float(signal["stop_loss"]))

        trade = Trade(
            asset=symbol,
            signal=signal["signal"],
            confidence=signal["confidence"],
            entry_price=fill,
            stop_loss=signal["stop_loss"],
            take_profit=signal["tp3"],
            position_sz=qty,
            risk_usd=round(sizing["risk_quote"], 4),
            risk_reward=round(abs(float(signal["tp3"]) - fill) / risk_distance, 4)
                        if risk_distance else 0.0,
            outcome="OPEN",
            binance_order_id=result.get("order_id", ""),
            created_at=datetime.utcnow(),
        )
        db.add(trade)
        db.commit()
        db.refresh(trade)

        return {"success": True, "trade_id": trade.id, "fill_price": fill,
                "qty": qty, "risk_usd": sizing["risk_quote"]}

    except Exception as e:
        db.rollback()
        print(f"[crypto] place_crypto_order error {symbol}: {e}")
        return {"success": False, "error": str(e)}
    finally:
        db.close()


def run_forex_position_monitor():
    """Monitor forex positions via Capital.com"""
    from config import FOREX_ENABLED
    if not FOREX_ENABLED:
        return
    
    try:
        from modules.forex_position_manager import (check_forex_positions,
                                                    manage_open_positions)
        check_forex_positions()
        # The Silver Bullet management rules (breakeven, trailing, partials,
        # session and reversal exits) run on the same cycle as reconciliation,
        # so a position is never left trailing a price the monitor has not seen.
        stats = manage_open_positions()
        if stats.get("closed") or stats.get("partials") or stats.get("stops"):
            print(f"[forex-manage] checked={stats['checked']} "
                  f"partials={stats['partials']} stops={stats['stops']} "
                  f"closed={stats['closed']} errors={stats['errors']}")
    except Exception as e:
        print(f"[forex-positions] error: {e}")


def run_daily_pdh_pdl_reset():
    """Reset ranges at 00:01 UTC daily (all timeframes)."""
    global _forex_active_setups
    from config import FOREX_ENABLED
    if not FOREX_ENABLED:
        return
    
    try:
        from modules.crt_detector import update_all_ranges
        print("[crt] daily range reset (00:01 UTC)")
        _forex_active_setups = {}
        update_all_ranges()
    except Exception as e:
        print(f"[crt] daily reset error: {e}")


# ── CRYPTO: same 3-layer strategy (Kronos + CRT + SMC) ────────────────────────

def run_crypto_kronos_bias():
    """Update Kronos AI bias for all crypto symbols (H1)."""
    from config import KRONOS_ENABLED
    if not KRONOS_ENABLED:
        return
    try:
        from modules.universe import get_universe
        from modules.crypto_strategy import update_all_crypto_bias
        symbols = get_universe()
        n = update_all_crypto_bias(symbols)
        print(f"[crypto-kronos] bias updated for {n}/{len(symbols)} symbols")
    except Exception as e:
        print(f"[crypto-kronos] cycle error: {e}")


def run_crypto_crt_scan():
    """Detect CRT setups on crypto symbols and validate with Kronos."""
    lock = _job_locks["crypto_crt"]
    if not lock.acquire(blocking=False):
        print("[crypto-crt] previous scan still active — skipping")
        return
    db = SessionLocal()
    try:
        state = _get_bot_state(db)
        if not state.is_running or state.paused:
            return
        from modules.universe import get_universe
        from modules.crypto_strategy import update_crypto_levels, scan_crypto_crt, get_crypto_setups
        symbols = get_universe()
        for sym in symbols:
            # Every crypto pair — including BTC/ETH — is scanned here for the
            # SMC/CRT cascade. The refined CRT pullback path runs first in
            # level1_bos_scan and simply finds nothing for pairs it does not
            # sweep, so skipping any symbol here would silently drop the
            # fallback instead of avoiding duplicate work.
            try:
                update_crypto_levels(sym)
                scan_crypto_crt(sym)
            except Exception as e:
                print(f"[crypto-crt] {sym} error: {e}")
        print(f"[crypto-crt] scan complete — {len(get_crypto_setups())} active setups")
    except Exception as e:
        print(f"[crypto-crt] cycle error: {e}")
    finally:
        db.close()
        lock.release()


def run_crypto_entry_check():
    """Check SMC entries on active crypto CRT setups and place orders."""
    lock = _job_locks["crypto_entry"]
    if not lock.acquire(blocking=False):
        print("[crypto-entry] previous run still active — skipping")
        return
    db = SessionLocal()
    try:
        state = _get_bot_state(db)
        if not state.is_running or state.paused:
            return

        from modules.crypto_strategy import get_crypto_setups, check_crypto_entry, clear_crypto_setup
        from modules.position_manager import can_reenter, cooldown_log_once
        from modules.risk_manager import calculate_risk_with_compounding
        from modules.executor import place_order
        from modules.market_data import get_balance, get_ticker_price
        from config import MAX_OPEN_TRADES, MIN_CONFIDENCE
        from modules.risk_settings import get_settings
        from models import Trade

        rs = get_settings()
        crypto_min_conf = float(rs.get("crypto_min_confidence", MIN_CONFIDENCE))

        setups = get_crypto_setups()
        if not setups:
            return

        open_count = db.query(Trade).filter(Trade.outcome == "OPEN").count()
        if open_count >= MAX_OPEN_TRADES:
            return

        balance = get_balance()
        if balance < 1.0:
            return

        # Hard time budget — never let this job run past ~50s so the next
        # 60s tick always gets a slot (prevents "maximum instances reached").
        import time as _time
        deadline = _time.time() + 50

        for symbol in list(setups.keys()):
            if _time.time() > deadline:
                print(f"[crypto-entry] time budget reached — deferring remaining setups")
                break
            try:
                allowed, reason = can_reenter(symbol, db)
                if not allowed:
                    if cooldown_log_once(symbol, db):
                        print(f"[crypto-entry] {symbol} blocked: {reason}")
                    record_diagnostic("crypto", symbol, "REJECT", reason)
                    continue

                sig = check_crypto_entry(symbol)
                if not sig:
                    continue

                if sig["confidence"] < crypto_min_conf:
                    print(f"[crypto-entry] {symbol} confidence {sig['confidence']:.1f}% < {crypto_min_conf:.0f}")
                    record_diagnostic("crypto", symbol, "REJECT",
                                      f"confidence {sig['confidence']:.1f}% < {crypto_min_conf:.0f}%",
                                      sig["confidence"])
                    clear_crypto_setup(symbol)
                    continue

                blocked = guard_order(symbol, "crypto")
                if blocked:
                    print(f"[crypto-entry] {symbol} order suppressed: {blocked['error']}")
                    continue

                price = get_ticker_price(symbol)
                risk = calculate_risk_with_compounding(
                    price=price, signal=sig["signal"], confidence=sig["confidence"],
                    atr=0, balance=balance, symbol=symbol,
                )

                result = place_order(
                    symbol=symbol, signal=sig["signal"],
                    position_units=risk["position_size_units"],
                    stop_loss=sig["stop_loss"], take_profit=sig["take_profit"],
                    confidence=sig["confidence"],
                )

                if result.get("success"):
                    print(f"[crypto-entry] TRADE PLACED — {sig['signal']} {symbol} "
                          f"@ {result['fill_price']} conf={sig['confidence']:.0f}%")
                    record_diagnostic("crypto", symbol, "PASS",
                                      f"order placed @ {result['fill_price']}",
                                      sig["confidence"])
                    clear_crypto_setup(symbol)
                else:
                    record_diagnostic("crypto", symbol, "REJECT",
                                      f"order failed: {result.get('error')}",
                                      sig["confidence"])
                    print(f"[crypto-entry] {symbol} order failed: {result.get('error')}")
            except Exception as e:
                print(f"[crypto-entry] {symbol} error: {e}")
                clear_crypto_setup(symbol)
    except Exception as e:
        print(f"[crypto-entry] cycle error: {e}")
    finally:
        db.close()
        lock.release()


def _keep_alive():
    import time, requests as req
    domain = os.getenv("RAILWAY_PUBLIC_DOMAIN", "")
    url    = f"https://{domain}" if domain else "http://localhost:8000"
    while True:
        time.sleep(840)
        try:
            req.get(f"{url}/", timeout=10)
            print("[keep-alive] ping sent")
        except Exception:
            pass


# ── Scheduler ─────────────────────────────────────────────────────

def _scanner_watchdog():
    """
    Nudges the Silver Bullet scanner if the scheduler missed a window.

    This used to force an L1 BOS scan, which is a retired strategy. A watchdog
    that resurrects a retired strategy is worse than no watchdog, so it now
    drives the surviving one: if a session window is open, run the cycle. The
    cycle is itself gated on the live session, so this cannot trade outside a
    window even if the clock and the schedule disagree.
    """
    import time as _time
    while True:
        _time.sleep(960)
        db = SessionLocal()
        try:
            state = _get_bot_state(db)
            if state.is_running and not state.paused:
                from modules.silver_bullet import current_session
                session = current_session()
                if session:
                    print(f"[watchdog] forcing {session} Silver Bullet scan")
                    threading.Thread(target=run_silver_bullet_cycle,
                                     daemon=True).start()
        except Exception as e:
            print(f"[watchdog] error: {e}")
        finally:
            db.close()

scheduler = BackgroundScheduler()

# Shared job options — never pile up overlapping runs
_JOB_OPTS = dict(max_instances=1, coalesce=True, misfire_grace_time=30)

# ── Crypto POSITION MANAGEMENT (not a strategy) ───────────────────────────────
# `check_positions` reconciles Binance positions and enforces their stop/target.
# It is the crypto counterpart of `run_forex_position_monitor` and is retained:
# existing open positions must keep being managed regardless of which strategy
# opened them.
scheduler.add_job(check_positions, "interval", minutes=2,
                  id="crypto_position_monitor", **_JOB_OPTS)

# ── RETIRED: legacy crypto SMC/CRT strategy jobs ──────────────────────────────
# `level1_bos_scan`, `level2_entry_check`, `refresh_signal_cache`,
# `run_crypto_crt_scan` and `run_crypto_entry_check` are NOT registered.
#
# They generated entries from the BOS/CRT/SMC engines, which are retired —
# Silver Bullet is the only strategy permitted to submit an order. Their
# functions remain defined in this module for historical reference, and the
# shared diagnostic helpers they used still work, but nothing schedules them.
#
# They are unregistered rather than deleted so the migration is reviewable: the
# diff shows a job removed from the schedule rather than a file vanishing.

# ── Silver Bullet + Volume Profile strategy (UTC) ─────────────────────────────
#
# The schedule below is the strategy's own clock. Two things are deliberate:
#
#   * the scanners are per-session CRON jobs bound to a session name, not one
#     free-running interval. A single interval job that internally asks "which
#     session is open?" trades whatever the clock says at the moment it fires,
#     which makes "the London scanner only runs in London" a property of the
#     data rather than of the schedule. Binding the name at registration means a
#     misfire cannot silently scan the wrong window — and the name is re-checked
#     inside the job as well.
#   * the roster is EVERY enabled instrument — forex, metals and crypto alike —
#     because `SILVER_BULLET_INSTRUMENTS` is derived from FOREX_PAIRS plus the
#     crypto universe rather than hand-listed.
#
# Explicit ids on every strategy job, so a test can assert the schedule without
# parsing trigger reprs, and so a duplicate registration is detectable rather
# than silently becoming two jobs.
scheduler.add_job(run_silver_bullet_bias, "cron", hour=7, minute=0,
                  timezone="UTC", id="silver_daily_bias", **_JOB_OPTS)

# Pre-session liquidity: five minutes before each window opens.
for _presession_hour, _presession_minute in ((7, 55), (14, 55), (18, 55)):
    scheduler.add_job(run_silver_bullet_presession, "cron",
                      hour=_presession_hour, minute=_presession_minute,
                      timezone="UTC",
                      id=f"silver_presession_{_presession_hour:02d}{_presession_minute:02d}",
                      **_JOB_OPTS)

# The three session scanners, every five minutes inside their own window.
for _session, (_start_hour, _end_hour, _bonus) in SESSIONS.items():
    scheduler.add_job(run_silver_bullet_scanner, "cron",
                      hour=_start_hour, minute="*/5",
                      timezone="UTC",
                      args=[_session], id=f"silver_scan_{_session}",
                      **_JOB_OPTS)

# Safety net: rollover + pre-session marking even if a cron was missed.
scheduler.add_job(run_silver_bullet_cycle, "interval", minutes=5,
                  id="silver_cycle", **_JOB_OPTS)

# Entry: only ever fills a setup whose session is open right now.
scheduler.add_job(run_silver_bullet_entry_check, "interval", seconds=30,
                  id="silver_entry_check", **_JOB_OPTS)

# ── Forex position lifecycle ──────────────────────────────────────────────────
scheduler.add_job(run_forex_position_monitor, "interval", minutes=2,
                  id="forex_position_monitor", **_JOB_OPTS)
scheduler.add_job(run_end_of_day_policy, "cron", hour=EOD_HOUR,
                  minute=EOD_MINUTE, timezone="UTC",
                  id="forex_end_of_day", **_JOB_OPTS)
scheduler.add_job(run_daily_report, "cron", hour=23, minute=0,
                  timezone="UTC", id="forex_daily_report", **_JOB_OPTS)

# ── RETIRED: legacy CRT/SMC strategy jobs ─────────────────────────────────────
# `run_kronos_bias_update`, `run_crt_scan`, `run_forex_entry_check`,
# `run_daily_pdh_pdl_reset` and the three crypto strategy jobs are NOT
# registered.
#
#   run_crt_scan            discovered CRT setups for the retired entry path
#   run_forex_entry_check   submitted those setups as orders
#   run_daily_pdh_pdl_reset refreshed the CRT range cache those setups used
#   run_kronos_bias_update  produced a Kronos bias only the CRT path consulted
#   run_crypto_crt_scan     the crypto equivalent of run_crt_scan
#   run_crypto_entry_check  submitted those setups as orders
#   run_crypto_kronos_bias  produced a Kronos bias nothing consults any more
#
# With Silver Bullet as the only strategy, none of them has a consumer that can
# trade, and a data-refresh job whose only purpose is to feed a retired strategy
# is the "running merely to populate a UI card" case. The dashboard's levels
# come from the Silver Bullet volume profile instead.
#
# Their functions remain defined above for historical reference; nothing
# schedules them.

scheduler.start()


@app.on_event("startup")
async def startup():
    print(f"[weltbot] v5.0 starting — testnet={BINANCE_TESTNET}")
    db = SessionLocal()
    state = _get_bot_state(db)
    from modules.risk_settings import get_settings as _startup_settings
    # auto_resume controls whether a restart clears a pause. With it off, a
    # pause that was deliberately set survives a redeploy instead of being
    # silently undone by the next boot.
    if _startup_settings().get("auto_resume", True):
        state.is_running = 1; state.paused = 0; state.pause_reason = None
    else:
        state.is_running = 1
    db.commit(); db.close()

    from modules.risk_settings import get_settings
    rs = get_settings(force=True)
    print(f"[settings] forex_daily_limit={rs['forex_daily_limit_enabled']} "
          f"crypto_daily_limit={rs['crypto_daily_limit_enabled']} "
          f"forex_risk={rs['forex_risk_pct']*100:.2f}% "
          f"forex_min_conf={rs['forex_min_confidence']:.0f}% "
          f"diagnostic_mode={rs.get('diagnostic_mode', False)}")
    if rs.get("diagnostic_mode"):
        print("[weltbot] DIAGNOSTIC MODE — signals are evaluated and logged, "
              "but no orders will be submitted, modified, or closed")

    from config import FOREX_ENABLED, KRONOS_ENABLED
    
    if FOREX_ENABLED:
        print("[weltbot] forex enabled — initializing Capital.com...")

        # Verify Capital.com credentials at startup
        def _verify_capital():
            try:
                from modules.market_data_forex import get_capital_balance, get_last_error
                bal = get_capital_balance()
                if bal.get("connected"):
                    env = "demo" if os.getenv("CAPITAL_DEMO", "true").lower() == "true" else "live"
                    print(f"[capital] connected — {env} balance=${bal['balance']:,.2f} "
                          f"{bal.get('currency','USD')}")
                else:
                    print(f"[capital] NOT connected — {get_last_error()}")
            except Exception as e:
                print(f"[capital] startup check error: {e}")
        threading.Thread(target=_verify_capital, daemon=True).start()

        # The Kronos model is NOT loaded. It was the bias layer of the retired
        # Kronos+CRT+SMC stack, and nothing in the Silver Bullet path consults
        # its output — so loading a multi-hundred-megabyte model at startup
        # would cost memory and boot time for a decision that is never made.
        # `KRONOS_ENABLED` is left in config so the flag's history is intact.
        if KRONOS_ENABLED:
            print("[kronos] retired — Silver Bullet does not consult a Kronos bias")

        # The CRT range cache is NOT refreshed: it fed the retired CRT entry
        # path and the dashboard card that displayed it. Both are now served
        # from the Silver Bullet volume profile, so the refresh would be a
        # periodic broker call for data nothing reads.

        threading.Thread(target=run_silver_bullet_cycle, daemon=True).start()

    # The crypto strategy bootstrap is retired: Silver Bullet scans every crypto
    # symbol from the same universe on the same session windows, so there is no
    # separate crypto strategy to warm up.

    threading.Thread(target=_keep_alive,           daemon=True).start()
    threading.Thread(target=_scanner_watchdog,     daemon=True).start()


@app.on_event("shutdown")
async def shutdown():
    scheduler.shutdown()


@app.api_route("/", methods=["GET", "HEAD"])
def root():
    return {"status": "ok", "name": "WeltBot", "version": "5.0.0"}


@app.get("/kaithheathcheck")
@app.get("/kaithhealthcheck")
def health():
    return {"status": "ok"}


@app.get("/api/bot/status")
def bot_status():
    db     = SessionLocal()
    state  = _get_bot_state(db)
    is_run = bool(state.is_running)
    paused = bool(state.paused)
    reason = state.pause_reason
    db.close()
    balance = safe_get_balance()
    
    from config import FOREX_ENABLED, KRONOS_ENABLED
    forex_info = {}
    if FOREX_ENABLED:
        from modules.kronos_engine import is_kronos_available
        forex_balance     = 0.0
        forex_profit_loss = 0.0
        forex_connected   = False
        try:
            from modules.market_data_forex import get_capital_balance
            fb = get_capital_balance()
            forex_balance     = fb.get("balance", 0.0)
            forex_profit_loss = fb.get("profit_loss", 0.0)
            forex_connected   = fb.get("connected", False)
        except Exception as e:
            print(f"[bot] forex balance error: {e}")
        forex_info = {
            "forex_enabled": True,
            "forex_provider": "capital.com",
            "kronos_available": is_kronos_available(),
            # The legacy CRT entry queue. Empty during the migration by design;
            # the tradeable setups are the Silver Bullet ones in
            # /api/forex/silver-bullet. Kept so an existing consumer does not
            # break on a missing key.
            "forex_active_setups": list(_forex_active_setups.keys()),
            "forex_legacy_entries_enabled": _legacy_entries_enabled(),
            "forex_balance": round(forex_balance, 2),
            "forex_equity":  round(forex_balance + forex_profit_loss, 2),
            "forex_unrealized": round(forex_profit_loss, 2),
            "forex_connected": forex_connected,
            "total_balance": round(balance + forex_balance, 2),
        }
    else:
        forex_info = {"forex_enabled": False, "forex_balance": 0.0, "forex_equity": 0.0,
                      "forex_unrealized": 0.0, "forex_connected": False,
                      "total_balance": round(balance, 2)}

    # Crypto strategy state — Silver Bullet's pending setups for this venue.
    crypto_info = {"strategy": "SILVER_BULLET", "crypto_active_setups": []}
    try:
        from modules.silver_bullet import get_active_setups
        from modules.universe import get_universe
        universe = set(get_universe())
        crypto_info["crypto_active_setups"] = [
            s for s in get_active_setups() if s in universe
        ]
    except Exception:
        pass

    return {
        "running":       is_run,
        "paused":        paused,
        "pause_reason":  reason,
        "balance_usdt":  round(balance, 2),   # crypto / Binance
        "testnet":       BINANCE_TESTNET,
        "last_scan":     _last_scan_log,
        "active_setups": list(_active_setups.keys()),
        **forex_info,
        **crypto_info
    }


@app.post("/api/bot/start")
def start_bot():
    db    = SessionLocal()
    state = _get_bot_state(db)
    state.is_running = 1; state.paused = 0; state.pause_reason = None
    db.commit(); db.close()
    threading.Thread(target=run_silver_bullet_cycle, daemon=True).start()
    return {"message": "WeltBot v5.0 started"}


@app.post("/api/bot/resume")
def resume_bot():
    """
    Clear a pause without restarting the bot.

    Needed because a tripped drawdown limit used to require waiting until the
    next day, which made the strategy impossible to evaluate in one sitting.
    """
    db    = SessionLocal()
    state = _get_bot_state(db)
    was   = state.pause_reason
    state.is_running = 1
    state.paused = 0
    state.pause_reason = None
    db.commit(); db.close()
    threading.Thread(target=run_silver_bullet_cycle, daemon=True).start()
    return {"message": "Bot resumed", "cleared_pause": was}


@app.post("/api/bot/stop")
def stop_bot():
    db    = SessionLocal()
    state = _get_bot_state(db)
    state.is_running = 0
    db.commit(); db.close()
    return {"message": "WeltBot stopped"}


@app.post("/api/bot/scan-now")
def scan_now():
    """
    Manual scan trigger.

    Runs the Silver Bullet cycle, which is gated on the live session — so a
    manual invocation outside a permitted window does nothing rather than
    trading. The retired BOS/entry pair is deliberately not reachable here.
    """
    threading.Thread(target=run_silver_bullet_cycle, daemon=True).start()
    return {"message": "Manual Silver Bullet scan triggered"}


@app.post("/api/bot/close-all")
def close_all_positions():
    """Emergency: close ALL open positions on exchange and in DB."""
    from modules.position_manager import close_all_exchange_positions
    from models import Trade
    db = SessionLocal()
    try:
        results = close_all_exchange_positions()
        # Mark all open trades as closed in DB
        open_trades = db.query(Trade).filter(Trade.outcome == "OPEN").all()
        from modules.market_data import get_ticker_price
        closed = 0
        for t in open_trades:
            price = get_ticker_price(t.asset)
            if price > 0:
                pnl = (price - t.entry_price) * (t.position_sz or 0) if t.signal == "BUY"                       else (t.entry_price - price) * (t.position_sz or 0)
                t.outcome   = "WIN" if pnl >= 0 else "LOSS"
                t.pnl       = round(pnl, 4)
                t.closed_at = datetime.utcnow()
                closed += 1
        db.commit()
        return {"success": True, "exchange_closed": len(results), "db_closed": closed, "results": results}
    except Exception as e:
        return {"success": False, "error": str(e)}
    finally:
        db.close()


@app.get("/api/bot/exchange-positions")
def get_exchange_positions_api():
    """Get all open positions directly from Binance exchange."""
    from modules.position_manager import get_exchange_positions, sync_exchange_positions
    sync_exchange_positions()
    positions = get_exchange_positions()
    return {"count": len(positions), "positions": positions}


@app.post("/api/bot/cleanup-duplicates")
def cleanup_duplicate_trades():
    """Remove duplicate OPEN trades for same asset — keep only the latest one."""
    db = SessionLocal()
    try:
        from sqlalchemy import func
        open_trades = db.query(Trade).filter(Trade.outcome=="OPEN").order_by(Trade.id.desc()).all()
        seen = set()
        to_delete = []
        for t in open_trades:
            if t.asset in seen:
                to_delete.append(t.id)
            else:
                seen.add(t.asset)
        if to_delete:
            db.query(Trade).filter(Trade.id.in_(to_delete)).delete(synchronize_session=False)
            db.commit()
        return {"success": True, "deleted_duplicates": len(to_delete), "kept": len(seen)}
    except Exception as e:
        return {"success": False, "error": str(e)}
    finally:
        db.close()
