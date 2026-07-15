"""
backend/main.py - COMPLETE CORRECT VERSION
WeltBot v5.0
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from apscheduler.schedulers.background import BackgroundScheduler
from database import engine, Base, SessionLocal
from models import SignalCache, BotState, Trade
from routers import signals, trades, analytics, auth
from config import MAX_OPEN_TRADES, SCAN_INTERVAL_MIN, BINANCE_TESTNET
from datetime import datetime
import json, os, threading

Base.metadata.create_all(bind=engine)

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
app.include_router(auth.router)

_last_scan_log  = []
_active_setups: dict = {}


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
    from modules.position_manager import can_reenter

    symbol = sig["symbol"]
    signal = sig["signal"]

    allowed, reason = can_reenter(symbol, db)
    if not allowed:
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

        from modules.signal_engine     import check_entry_for_setup
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
scheduler.add_job(check_positions,      "interval", minutes=2)
scheduler.add_job(level2_entry_check,   "interval", seconds=60,
                  max_instances=3, coalesce=True, misfire_grace_time=30)
scheduler.add_job(level1_bos_scan,      "interval", minutes=SCAN_INTERVAL_MIN)
scheduler.add_job(refresh_signal_cache, "interval", minutes=10)
scheduler.start()


@app.on_event("startup")
async def startup():
    print(f"[weltbot] v5.0 starting — testnet={BINANCE_TESTNET}")
    db = SessionLocal()
    state = _get_bot_state(db)
    state.is_running = 1; state.paused = 0
    db.commit(); db.close()
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
