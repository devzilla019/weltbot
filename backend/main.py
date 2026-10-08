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
from config import MAX_OPEN_TRADES, SCAN_INTERVAL_MIN, BINANCE_TESTNET
from datetime import datetime
import json, logging, os, threading

# Without this, every logger.info()/logger.warning() call in the modules is
# silently discarded — uvicorn only configures its own loggers, so the CRT
# trend/sweep/entry diagnostics never reached the Railway logs.
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
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

    allowed, reason = can_reenter(symbol, db)
    if not allowed:
        if cooldown_log_once(symbol, db):
            print(f"[bot] {symbol} blocked: {reason}")
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
        print(f"[bot] TRADE PLACED — {signal} {symbol} @ {result['fill_price']}")
        return True
    else:
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
        from modules.signal_engine import scan_for_bos, ema_momentum_scan, scan_btc_eth_crt, CRT_PULLBACK_SYMBOLS

        balance    = safe_get_balance()
        open_count = db.query(Trade).filter(Trade.outcome == "OPEN").count()
        print(f"[L1] scanning — balance=${balance:.2f} open={open_count}/{MAX_OPEN_TRADES}")

        if open_count >= MAX_OPEN_TRADES:
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
                # BTC/ETH: refined CRT pullback strategy first
                if symbol in CRT_PULLBACK_SYMBOLS:
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

        if daily_drawdown_check():
            state.paused = 1; state.pause_reason = "Daily drawdown limit hit"
            db.commit(); return

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
    """Refined CRT scan — H4 trend, H1 pullback range, sweep confirmation."""
    global _forex_active_setups
    from config import FOREX_ENABLED
    if not FOREX_ENABLED:
        return

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

                _forex_active_setups[symbol] = sweep
                store_crt_level(sweep)
                print(f"[crt] {symbol} {sweep['trend_direction']} setup confirmed — "
                      f"{sweep['direction']} target={sweep['target']:.5f}")

            except Exception as e:
                print(f"[crt] error {symbol}: {e}")

        print(f"[crt] scan complete — {len(_forex_active_setups)} active setups")
    except Exception as e:
        print(f"[crt] scan cycle error: {e}")
    finally:
        db.close()
        lock.release()


def run_forex_entry_check():
    """Check for SMC entry on active CRT setups"""
    global _forex_active_setups
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
                    if signal['confidence'] >= FOREX_MIN_CONF:
                        result = place_forex_order(signal, bias or {})
                        if result['success']:
                            print(f"[forex] ENTRY {signal['signal']} {symbol} @ "
                                  f"{signal['entry_price']:.5f} | {signal['entry_type']} | "
                                  f"conf={signal['confidence']:.0f}% | "
                                  f"SL={signal['stop_loss']:.5f} | "
                                  f"TP1={signal['tp1']:.5f} | TP2={signal['tp2']:.5f}")
                            _forex_active_setups.pop(symbol, None)
                    else:
                        print(f"[forex-entry] {symbol} confidence too low: "
                              f"{signal['confidence']:.1f}%")
                        _forex_active_setups.pop(symbol, None)

            except Exception as e:
                print(f"[forex-entry] error {symbol}: {e}")
                _forex_active_setups.pop(symbol, None)
        
    except Exception as e:
        print(f"[forex-entry] cycle error: {e}")
    finally:
        db.close()
        lock.release()


def run_forex_position_monitor():
    """Monitor forex positions via Capital.com"""
    from config import FOREX_ENABLED
    if not FOREX_ENABLED:
        return
    
    try:
        from modules.forex_position_manager import check_forex_positions
        check_forex_positions()
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
        from modules.signal_engine import CRT_PULLBACK_SYMBOLS
        symbols = get_universe()
        for sym in symbols:
            # BTC/ETH use the refined CRT pullback engine (level1_bos_scan)
            if sym in CRT_PULLBACK_SYMBOLS:
                continue
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
        from models import Trade

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
                    continue

                sig = check_crypto_entry(symbol)
                if not sig:
                    continue

                if sig["confidence"] < MIN_CONFIDENCE:
                    print(f"[crypto-entry] {symbol} confidence {sig['confidence']:.1f}% < {MIN_CONFIDENCE}")
                    clear_crypto_setup(symbol)
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
                    clear_crypto_setup(symbol)
                else:
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
    """Forces L1 scan every 16 min if scheduler missed it."""
    import time as _time
    while True:
        _time.sleep(960)
        db = SessionLocal()
        try:
            state = _get_bot_state(db)
            if state.is_running and not state.paused:
                print("[watchdog] forcing L1 scan")
                threading.Thread(target=level1_bos_scan, daemon=True).start()
        except Exception as e:
            print(f"[watchdog] error: {e}")
        finally:
            db.close()

scheduler = BackgroundScheduler()

# Shared job options — never pile up overlapping runs
_JOB_OPTS = dict(max_instances=1, coalesce=True, misfire_grace_time=30)

# Crypto jobs
scheduler.add_job(check_positions,      "interval", minutes=2, **_JOB_OPTS)
scheduler.add_job(level2_entry_check,   "interval", seconds=60, **_JOB_OPTS)
scheduler.add_job(level1_bos_scan,      "interval", minutes=SCAN_INTERVAL_MIN, **_JOB_OPTS)
scheduler.add_job(refresh_signal_cache, "interval", minutes=10, **_JOB_OPTS)

# Forex jobs
scheduler.add_job(run_kronos_bias_update,     "interval", minutes=15, **_JOB_OPTS)
# Refined CRT — NY pre-open + London open are prioritised, 30-min monitor runs continuously
scheduler.add_job(run_crt_scan,               "cron", hour=12, minute=30, timezone="UTC", **_JOB_OPTS)
scheduler.add_job(run_crt_scan,               "cron", hour=8,  minute=0,  timezone="UTC", **_JOB_OPTS)
scheduler.add_job(run_crt_scan,               "interval", minutes=30, **_JOB_OPTS)
scheduler.add_job(run_forex_entry_check,      "interval", seconds=60, **_JOB_OPTS)
scheduler.add_job(run_forex_position_monitor, "interval", minutes=2, **_JOB_OPTS)
scheduler.add_job(run_daily_pdh_pdl_reset,    "cron", hour=0, minute=1, **_JOB_OPTS)

# Crypto jobs — same 3-layer strategy (Kronos + CRT + SMC)
scheduler.add_job(run_crypto_kronos_bias,     "interval", minutes=15, **_JOB_OPTS)
scheduler.add_job(run_crypto_crt_scan,        "interval", minutes=15, **_JOB_OPTS)
scheduler.add_job(run_crypto_entry_check,     "interval", seconds=60, **_JOB_OPTS)

scheduler.start()


@app.on_event("startup")
async def startup():
    print(f"[weltbot] v5.0 starting — testnet={BINANCE_TESTNET}")
    db = SessionLocal()
    state = _get_bot_state(db)
    state.is_running = 1; state.paused = 0
    db.commit(); db.close()
    
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

        if KRONOS_ENABLED:
            print("[weltbot] loading Kronos model...")
            from modules.kronos_engine import _load_kronos_model
            threading.Thread(target=_load_kronos_model, daemon=True).start()
        else:
            print("[kronos] disabled — using neutral bias")

        from modules.crt_detector import update_all_ranges
        threading.Thread(target=update_all_ranges, daemon=True).start()

        threading.Thread(target=run_kronos_bias_update, daemon=True).start()
        threading.Thread(target=run_crt_scan, daemon=True).start()
    
    # Crypto 3-layer strategy bootstrap (Kronos + CRT + SMC)
    if KRONOS_ENABLED:
        threading.Thread(target=run_crypto_kronos_bias, daemon=True).start()
        threading.Thread(target=run_crypto_crt_scan,    daemon=True).start()
    
    threading.Thread(target=refresh_signal_cache, daemon=True).start()
    threading.Thread(target=level1_bos_scan,      daemon=True).start()
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
            "forex_active_setups": list(_forex_active_setups.keys()),
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

    # Crypto strategy state
    crypto_info = {"kronos_enabled": KRONOS_ENABLED, "crypto_active_setups": []}
    try:
        from modules.crypto_strategy import get_crypto_setups
        crypto_info["crypto_active_setups"] = list(get_crypto_setups().keys())
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
    threading.Thread(target=level1_bos_scan, daemon=True).start()
    return {"message": "WeltBot v5.0 started"}


@app.post("/api/bot/stop")
def stop_bot():
    db    = SessionLocal()
    state = _get_bot_state(db)
    state.is_running = 0
    db.commit(); db.close()
    return {"message": "WeltBot stopped"}


@app.post("/api/bot/scan-now")
def scan_now():
    threading.Thread(target=level1_bos_scan,    daemon=True).start()
    threading.Thread(target=level2_entry_check, daemon=True).start()
    return {"message": "Manual scan triggered"}


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
