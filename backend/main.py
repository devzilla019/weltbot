from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from apscheduler.schedulers.background import BackgroundScheduler
from database import engine, Base, SessionLocal
from models import SignalCache, BotState, Trade
from routers import signals, trades, analytics
from config import (
    MAX_OPEN_TRADES,
    SCAN_INTERVAL_MIN,
    BINANCE_TESTNET,
)
from datetime import datetime
import json
import os
import threading

Base.metadata.create_all(bind=engine)

app = FastAPI(title="WeltBot", version="5.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "https://weltbot.vercel.app",
    ],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(signals.router)
app.include_router(trades.router)
app.include_router(analytics.router)

_last_scan_log  = []
_active_setups: dict = {}


# ── helpers ───────────────────────────────────────────────────────────────────

def _get_bot_state(db):
    state = db.query(BotState).first()
    if not state:
        state = BotState(is_running=0, paused=0)
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
    """Shared trade placement — returns True if order placed successfully."""
    global _last_scan_log

    from modules.risk_manager      import calculate_risk
    from modules.executor          import place_order
    from modules.position_manager  import can_reenter

    symbol = sig["symbol"]
    signal = sig["signal"]

    allowed, reason = can_reenter(symbol, db)
    if not allowed:
        print(f"[bot] {symbol} blocked: {reason}")
        return False

    atr  = sig["market"].get("atr", 0)
    risk = calculate_risk(
        sig["market"]["price"], signal,
        sig["confidence"], atr, balance,
    )

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
        _last_scan_log = [{
            "symbol":     symbol,
            "signal":     signal,
            "confidence": sig["confidence"],
            "entry":      result["fill_price"],
            "sl":         sl,
            "tp":         tp,
            "time":       datetime.utcnow().isoformat(),
        }]
        _active_setups.pop(symbol, None)
        print(f"[bot] TRADE PLACED — {signal} {symbol} @ {result['fill_price']}")
        return True
    else:
        print(f"[bot] order failed {symbol}: {result.get('error')}")
        return False


# ── L1: BOS scan (every 15 min) ───────────────────────────────────────────────

def level1_bos_scan():
    """
    Scans all symbols for BOS + Fib + OB + MA on 5m/15m.
    Also checks EMA momentum and RSI reversal strategies.
    Stores confirmed setups in _active_setups dict.
    """
    global _active_setups
    db = SessionLocal()
    try:
        state = _get_bot_state(db)
        if not state.is_running or state.paused:
            return

        from modules.universe      import get_universe
        from modules.signal_engine import scan_for_bos, ema_momentum_scan

        balance    = safe_get_balance()
        open_count = db.query(Trade).filter(Trade.outcome == "OPEN").count()
        print(f"[L1] scanning — balance=${balance:.2f} open={open_count}/{MAX_OPEN_TRADES}")

        if open_count >= MAX_OPEN_TRADES:
            print(f"[L1] max open trades — skipping scan")
            return

        # Carry over existing setups, increment age, expire old ones
        new_setups = {}
        for sym, setup in list(_active_setups.items()):
            age = setup.get("candle_age", 0) + 1
            if age > 15:
                print(f"[L1] {sym} fib expired after 15 candles — removing")
                continue
            setup["candle_age"] = age
            new_setups[sym] = setup

        # Scan symbols not already in active setups
        for symbol in get_universe():
            if symbol in new_setups:
                continue
            try:
                # Strategy A: SMC on 5m/15m (highest priority)
                setup = scan_for_bos(symbol)
                if setup:
                    new_setups[symbol] = setup
                    continue

                # Strategy B: EMA momentum
                mom = ema_momentum_scan(symbol)
                if mom:
                    new_setups[symbol] = {
                        "symbol":        symbol,
                        "direction":     "bullish" if mom["signal"] == "BUY" else "bearish",
                        "timeframe":     "5m",
                        "bos":           mom["bos"],
                        "fib":           mom["fib"],
                        "ob":            mom["ob"],
                        "candle_age":    0,
                        "strategy":      "EMA_MOMENTUM",
                        "direct_signal": mom,
                    }

            except Exception as e:
                print(f"[L1] error {symbol}: {e}")

        _active_setups = new_setups
        print(f"[L1] done — {len(new_setups)} active: {list(new_setups.keys())}")

    except Exception as e:
        print(f"[L1] cycle error: {e}")
    finally:
        db.close()


# ── L2: entry watcher (every 60 sec) ─────────────────────────────────────────

def level2_entry_check():
    """
    Runs every 60 seconds on active setups only.
    Fires trade when price enters zone and entry candle confirmed.
    Removes setup after attempting (success or failure) to prevent retry loops.
    """
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

        from modules.signal_engine      import check_entry_for_setup
        from modules.position_manager   import daily_drawdown_check

        if daily_drawdown_check():
            state.paused       = 1
            state.pause_reason = "Daily drawdown limit hit"
            db.commit()
            print("[bot] PAUSED — daily drawdown limit hit")
            return

        slots  = MAX_OPEN_TRADES - open_count
        placed = 0

        for symbol in list(_active_setups.keys()):
            if placed >= slots:
                break

            setup = _active_setups.get(symbol)
            if setup is None:
                continue

            try:
                # EMA/RSI strategies have a pre-built direct signal
                direct = setup.get("direct_signal")
                if direct:
                    success = _place_trade(direct, balance, db)
                    if success:
                        placed += 1
                    # Always remove after attempt — prevents infinite retry
                    _active_setups.pop(symbol, None)
                    continue

                # SMC strategy — check if price is now in zone with entry candle
                sig = check_entry_for_setup(setup)
                if sig:
                    success = _place_trade(sig, balance, db)
                    if success:
                        placed += 1
                    # Remove after attempting regardless of success
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


# ── position monitor (every 2 min) ───────────────────────────────────────────

def check_positions():
    try:
        from modules.position_manager import check_and_exit_positions
        check_and_exit_positions()
    except Exception as e:
        print(f"[positions] error: {e}")


# ── signal cache refresh (every 10 min) ──────────────────────────────────────

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
                risk = calculate_risk(
                    sig["market"]["price"], sig["signal"],
                    sig["confidence"], atr, balance,
                )
                payload = json.dumps({"signal_data": sig, "risk_plan": risk})
                cached  = db.query(SignalCache).filter(
                    SignalCache.asset == symbol
                ).first()
                if cached:
                    cached.payload = payload
                else:
                    db.add(SignalCache(asset=symbol, payload=payload))
                db.commit()
                print(f"[cache] refreshed {symbol}")
            except Exception as e:
                print(f"[cache] error {symbol}: {e}")
    finally:
        db.close()


# ── keep-alive ping ───────────────────────────────────────────────────────────

def _keep_alive():
    """Ping self to prevent Railway/Render free tier from sleeping."""
    import time
    import requests as req
    # Read URL from env — set RAILWAY_PUBLIC_DOMAIN on Railway
    domain = os.getenv("RAILWAY_PUBLIC_DOMAIN", "")
    url    = f"https://{domain}" if domain else "http://localhost:8000"
    while True:
        time.sleep(840)   # ping every 14 minutes
        try:
            req.get(f"{url}/", timeout=10)
            print("[keep-alive] ping sent")
        except Exception:
            pass


# ── scheduler ────────────────────────────────────────────────────────────────

scheduler = BackgroundScheduler()
scheduler.add_job(
    check_positions, "interval", minutes=2
)
scheduler.add_job(
    level2_entry_check, "interval", seconds=60,
    max_instances=3, coalesce=True, misfire_grace_time=30,
)
scheduler.add_job(
    level1_bos_scan, "interval", minutes=SCAN_INTERVAL_MIN
)
scheduler.add_job(
    refresh_signal_cache, "interval", minutes=10
)
scheduler.start()


# ── FastAPI lifecycle ─────────────────────────────────────────────────────────

@app.on_event("startup")
async def startup():
    print(f"[weltbot] v5.0 starting — testnet={BINANCE_TESTNET}")
    # Auto-start bot state so it scans immediately on deploy
    db    = SessionLocal()
    state = _get_bot_state(db)
    state.is_running = 1
    state.paused     = 0
    db.commit()
    db.close()
    # Start background threads
    threading.Thread(target=refresh_signal_cache, daemon=True).start()
    threading.Thread(target=level1_bos_scan,      daemon=True).start()
    threading.Thread(target=_keep_alive,           daemon=True).start()


@app.on_event("shutdown")
async def shutdown():
    scheduler.shutdown()


# ── API routes ────────────────────────────────────────────────────────────────

@app.api_route("/", methods=["GET", "HEAD"])
def root():
    return {"status": "ok", "name": "WeltBot", "version": "5.0.0"}


# Leapcell health check (both spellings used by Leapcell)
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
    return {
        "running":       is_run,
        "paused":        paused,
        "pause_reason":  reason,
        "balance_usdt":  round(balance, 2),
        "testnet":       BINANCE_TESTNET,
        "last_scan":     _last_scan_log,
        "active_setups": list(_active_setups.keys()),
    }


@app.post("/api/bot/start")
def start_bot():
    db    = SessionLocal()
    state = _get_bot_state(db)
    state.is_running   = 1
    state.paused       = 0
    state.pause_reason = None
    db.commit()
    db.close()
    threading.Thread(target=level1_bos_scan, daemon=True).start()
    return {"message": "WeltBot v5.0 started — scanning for structure setups"}


@app.post("/api/bot/stop")
def stop_bot():
    db    = SessionLocal()
    state = _get_bot_state(db)
    state.is_running = 0
    db.commit()
    db.close()
    return {"message": "WeltBot stopped"}


@app.post("/api/bot/scan-now")
def scan_now():
    threading.Thread(target=level1_bos_scan,    daemon=True).start()
    threading.Thread(target=level2_entry_check, daemon=True).start()
    return {"message": "Manual scan triggered — L1 BOS + L2 entry check running"}