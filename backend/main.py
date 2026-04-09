from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from apscheduler.schedulers.background import BackgroundScheduler
from database import engine, Base, SessionLocal
from models import SignalCache, BotState, Trade
from routers import signals, trades, analytics
from config import (
    MIN_CONFIDENCE, MAX_OPEN_TRADES,
    SCAN_INTERVAL_MIN, BINANCE_TESTNET,
)
from datetime import datetime
import json
import threading

Base.metadata.create_all(bind=engine)

app = FastAPI(title="WeltBot", version="3.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "https://weltbot.vercel.app"],
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(signals.router)
app.include_router(trades.router)
app.include_router(analytics.router)

_last_scan_log = []
_active_setups: dict = {}


def _get_bot_state(db):
    state = db.query(BotState).first()
    if not state:
        state = BotState(is_running=0, paused=0)
        db.add(state)
        db.commit()
    return state


def safe_get_balance():
    try:
        from modules.market_data import get_balance
        return get_balance()
    except Exception as e:
        print(f"[bot] balance error: {e}")
        return 0.0


def _place_trade(sig, balance, db):
    """Shared trade placement logic."""
    global _last_scan_log
    from modules.risk_manager import calculate_risk
    from modules.executor import place_order
    from modules.position_manager import can_reenter

    symbol = sig["symbol"]
    allowed, reason = can_reenter(symbol, db)
    if not allowed:
        return False

    atr = sig["market"].get("atr", 0)
    risk = calculate_risk(
        sig["market"]["price"], sig["signal"],
        sig["confidence"], atr, balance,
    )
    sl_tp = sig.get("sl_tp")
    sl = sl_tp["stop_loss"] if sl_tp else risk["stop_loss"]
    tp = sl_tp["take_profit"] if sl_tp else risk["take_profit"]

    if not sl or not tp:
        return False

    result = place_order(
        symbol=symbol, signal=sig["signal"],
        position_units=risk["position_size_units"],
        stop_loss=sl, take_profit=tp,
        confidence=sig["confidence"],
    )
    if result["success"]:
        _last_scan_log = [{
            "symbol": symbol,
            "signal": sig["signal"],
            "confidence": sig["confidence"],
            "entry": result["fill_price"],
            "sl": sl,
            "tp": tp,
            "time": datetime.utcnow().isoformat(),
        }]
        if symbol in _active_setups:
            del _active_setups[symbol]
        print(f"[bot] TRADE PLACED — {sig['signal']} {symbol} @ {result['fill_price']}")
        return True
    else:
        print(f"[bot] order failed {symbol}: {result.get('error')}")
        return False


def level1_bos_scan():
    """
    Runs every 15 minutes.
    Scans all symbols for BOS + Fib + OB + MA.
    Stores confirmed setups in _active_setups for fast entry checking.
    """
    global _active_setups
    db = SessionLocal()
    try:
        state = _get_bot_state(db)
        if not state.is_running or state.paused:
            return

        from modules.universe import get_universe
        from modules.signal_engine import scan_for_bos

        balance = safe_get_balance()
        open_count = db.query(Trade).filter(Trade.outcome == "OPEN").count()
        print(f"[L1] BOS scan — balance=${balance:.2f} open={open_count}/{MAX_OPEN_TRADES}")

        new_setups = {}
        for symbol in get_universe():
            try:
                setup = scan_for_bos(symbol)
                if setup:
                    if symbol in _active_setups:
                        setup["candle_age"] = _active_setups[symbol].get("candle_age", 0) + 1
                    else:
                        setup["candle_age"] = 0
                    if setup["candle_age"] > 15:
                        print(f"[L1] {symbol} fib expired after 15 candles — removing")
                        continue
                    new_setups[symbol] = setup
                    print(
                        f"[L1] SETUP FOUND: {symbol} {setup['direction'].upper()} "
                        f"age={setup['candle_age']}/15"
                    )
            except Exception as e:
                print(f"[L1] error {symbol}: {e}")

        _active_setups = new_setups
        print(f"[L1] scan done — {len(new_setups)} active setups: {list(new_setups.keys())}")

    except Exception as e:
        print(f"[L1] cycle error: {e}")
    finally:
        db.close()


def level2_entry_check():
    """
    Runs every 60 seconds.
    Only checks symbols with confirmed BOS + Fib + OB.
    Fires trade when entry candle appears.
    Much faster — only 3-5 API calls instead of 45.
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

        from modules.signal_engine import check_entry_for_setup
        from modules.position_manager import daily_drawdown_check

        if daily_drawdown_check():
            state.paused = 1
            state.pause_reason = "Daily drawdown limit hit"
            db.commit()
            return

        slots = MAX_OPEN_TRADES - open_count
        placed = 0

        for symbol, setup in list(_active_setups.items()):
            if placed >= slots:
                break
            try:
                sig = check_entry_for_setup(setup)
                if sig:
                    success = _place_trade(sig, balance, db)
                    if success:
                        placed += 1
                        del _active_setups[symbol]
            except Exception as e:
                print(f"[L2] error {symbol}: {e}")

        if placed > 0:
            print(f"[L2] entry check done — {placed} trades placed")

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
        balance = safe_get_balance() or 10000.0
        from modules.universe import get_universe
        from modules.signal_engine import compute_signal
        from modules.risk_manager import calculate_risk

        for symbol in get_universe():
            try:
                sig = compute_signal(symbol)
                atr = sig["market"].get("atr", 0)
                risk = calculate_risk(
                    sig["market"]["price"], sig["signal"],
                    sig["confidence"], atr, balance,
                )
                payload = json.dumps({"signal_data": sig, "risk_plan": risk})
                cached = db.query(SignalCache).filter(
                    SignalCache.asset == symbol).first()
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


scheduler = BackgroundScheduler()
scheduler.add_job(check_positions, "interval", minutes=2)
scheduler.add_job(level2_entry_check, "interval", seconds=60)
scheduler.add_job(level1_bos_scan, "interval", minutes=SCAN_INTERVAL_MIN)
scheduler.add_job(refresh_signal_cache, "interval", minutes=10)
scheduler.start()


@app.on_event("startup")
async def startup():
    print(f"[weltbot] v3.0 starting — testnet={BINANCE_TESTNET}")
    threading.Thread(target=refresh_signal_cache, daemon=True).start()
    threading.Thread(target=level1_bos_scan, daemon=True).start()


@app.on_event("shutdown")
async def shutdown():
    scheduler.shutdown()


@app.get("/")
def root():
    return {"status": "ok", "name": "WeltBot", "version": "3.0.0"}


@app.get("/api/bot/status")
def bot_status():
    db = SessionLocal()
    state = _get_bot_state(db)
    is_run = bool(state.is_running)
    paused = bool(state.paused)
    reason = state.pause_reason
    db.close()
    balance = safe_get_balance()
    return {
        "running": is_run,
        "paused": paused,
        "pause_reason": reason,
        "balance_usdt": round(balance, 2),
        "testnet": BINANCE_TESTNET,
        "last_scan": _last_scan_log,
        "active_setups": list(_active_setups.keys()),
    }


@app.post("/api/bot/start")
def start_bot():
    db = SessionLocal()
    state = _get_bot_state(db)
    state.is_running = 1
    state.paused = 0
    state.pause_reason = None
    db.commit()
    db.close()
    threading.Thread(target=level1_bos_scan, daemon=True).start()
    return {"message": "WeltBot v3.0 started — scanning for structure setups"}


@app.post("/api/bot/stop")
def stop_bot():
    db = SessionLocal()
    state = _get_bot_state(db)
    state.is_running = 0
    db.commit()
    db.close()
    return {"message": "WeltBot stopped"}


@app.post("/api/bot/scan-now")
def scan_now():
    threading.Thread(target=level1_bos_scan, daemon=True).start()
    threading.Thread(target=level2_entry_check, daemon=True).start()
    return {"message": "Manual scan triggered — L1 BOS + L2 entry check running"}
    threading.Thread(target=opportunity_scan, daemon=True).start()
    return {"message": "Manual scan triggered"}