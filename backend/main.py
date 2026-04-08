from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from apscheduler.schedulers.background import BackgroundScheduler
from database import engine, Base, SessionLocal
from models import SignalCache, BotState, Trade
from routers import signals, trades, analytics
from config import (
    MIN_CONFIDENCE, MAX_OPEN_TRADES,
    SCAN_INTERVAL_MIN, REENTRY_MIN_SCORE,
    BINANCE_TESTNET,
)
from datetime import datetime
import json
import threading

Base.metadata.create_all(bind=engine)

app = FastAPI(title="WeltBot", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(signals.router)
app.include_router(trades.router)
app.include_router(analytics.router)

_last_scan_log = []


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


def opportunity_scan():
    global _last_scan_log
    db = SessionLocal()
    try:
        state = _get_bot_state(db)
        if not state.is_running or state.paused:
            return

        from modules.position_manager import daily_drawdown_check, can_reenter
        if daily_drawdown_check():
            state.paused       = 1
            state.pause_reason = "Daily drawdown limit hit"
            db.commit()
            print("[bot] PAUSED — daily drawdown limit")
            return

        balance = safe_get_balance()
        if balance < 1.0:
            print(f"[bot] balance too low: ${balance:.4f}")
            return

        open_count = db.query(Trade).filter(Trade.outcome == "OPEN").count()
        if open_count >= MAX_OPEN_TRADES:
            print(f"[bot] max open trades ({open_count}/{MAX_OPEN_TRADES}) — waiting")
            return

        slots = MAX_OPEN_TRADES - open_count
        print(f"[bot] scanning — balance=${balance:.2f} slots={slots}")

        from modules.universe      import get_universe
        from modules.signal_engine import compute_signal
        from modules.risk_manager  import calculate_risk
        from modules.executor      import place_order

        opportunities = []
        for symbol in get_universe():
            try:
                allowed, reason = can_reenter(symbol, db)
                if not allowed:
                    continue
                sig = compute_signal(symbol)
                if "error" in sig or sig["signal"] == "HOLD":
                    continue
                if sig["confidence"] < MIN_CONFIDENCE:
                    continue
                if abs(sig["raw_score"]) < REENTRY_MIN_SCORE:
                    continue
                if not sig["market"].get("atr_ok", True):
                    continue
                atr  = sig["market"].get("atr", 0)
                risk = calculate_risk(
                    entry_price     = sig["market"]["price"],
                    signal          = sig["signal"],
                    confidence      = sig["confidence"],
                    atr             = atr,
                    portfolio_value = balance,
                )
                if risk["position_size_usdt"] < 0.001:
                    continue
                opportunities.append({"sig": sig, "risk": risk})
            except Exception as e:
                print(f"[bot] scan error {symbol}: {e}")
                continue

        opportunities.sort(key=lambda x: x["sig"]["confidence"], reverse=True)
        scan_log      = []
        trades_placed = 0

        for opp in opportunities[:slots]:
            sig  = opp["sig"]
            risk = opp["risk"]
            print(f"[bot] OPPORTUNITY {sig['signal']} {sig['symbol']} conf={sig['confidence']}%")
            
            sl_tp = sig.get("sl_tp")
            if sl_tp:
                stop_loss   = sl_tp["stop_loss"]
                take_profit = sl_tp["take_profit"]
            else:
                stop_loss   = risk["stop_loss"]
                take_profit = risk["take_profit"]

            result = place_order(
                symbol         = sig["symbol"],
                signal         = sig["signal"],
                position_units = risk["position_size_units"],
                stop_loss      = stop_loss,
                take_profit    = take_profit,
                confidence     = sig["confidence"],
            )
            if result["success"]:
                trades_placed += 1
                scan_log.append({
                    "symbol":     sig["symbol"],
                    "signal":     sig["signal"],
                    "confidence": sig["confidence"],
                    "entry":      result["fill_price"],
                    "sl":         risk["stop_loss"],
                    "tp":         risk["take_profit"],
                    "time":       datetime.utcnow().isoformat(),
                })
                print(f"[bot] PLACED {sig['signal']} {sig['symbol']} @ {result['fill_price']}")
            else:
                print(f"[bot] FAILED {sig['symbol']}: {result.get('error')}")

        _last_scan_log = scan_log
        print(f"[bot] scan done — {trades_placed} trades placed")

    except Exception as e:
        print(f"[bot] cycle error: {e}")
    finally:
        db.close()


def refresh_signal_cache():
    db = SessionLocal()
    try:
        balance = safe_get_balance() or 10000.0
        from modules.universe      import get_universe
        from modules.signal_engine import compute_signal
        from modules.risk_manager  import calculate_risk
        for symbol in get_universe()[:20]:
            try:
                sig = compute_signal(symbol)
                if "error" in sig:
                    continue
                atr  = sig["market"].get("atr", 0)
                risk = calculate_risk(
                    sig["market"]["price"],
                    sig["signal"],
                    sig["confidence"],
                    atr,
                    balance,
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


def check_positions():
    try:
        from modules.position_manager import check_and_exit_positions
        check_and_exit_positions()
    except Exception as e:
        print(f"[positions] error: {e}")

def entry_watch():
    """
    Runs every 2 minutes. Only checks assets where BOS+Fib+OB
    are confirmed but entry candle has not triggered yet.
    Much faster than full scan — only re-checks entry confirmation.
    """
    db = SessionLocal()
    try:
        state = _get_bot_state(db)
        if not state.is_running or state.paused:
            return
        open_count = db.query(Trade).filter(Trade.outcome == "OPEN").count()
        if open_count >= MAX_OPEN_TRADES:
            return
        from modules.universe      import get_universe
        from modules.signal_engine import compute_signal
        from modules.risk_manager  import calculate_risk
        from modules.executor      import place_order
        from modules.position_manager import can_reenter
        balance = safe_get_balance()
        if balance < 1.0:
            return
        for symbol in get_universe():
            try:
                allowed, _ = can_reenter(symbol, db)
                if not allowed:
                    continue
                sig = compute_signal(symbol)
                if sig.get("signal") in ("BUY", "SELL"):
                    atr  = sig["market"].get("atr", 0)
                    risk = calculate_risk(
                        sig["market"]["price"], sig["signal"],
                        sig["confidence"], atr, balance,
                    )
                    sl_tp = sig.get("sl_tp")
                    sl    = sl_tp["stop_loss"]   if sl_tp else risk["stop_loss"]
                    tp    = sl_tp["take_profit"] if sl_tp else risk["take_profit"]
                    result = place_order(
                        symbol=sig["symbol"], signal=sig["signal"],
                        position_units=risk["position_size_units"],
                        stop_loss=sl, take_profit=tp,
                        confidence=sig["confidence"],
                    )
                    if result["success"]:
                        print(f"[entry_watch] PLACED {sig['signal']} {symbol}")
                        break
            except Exception as e:
                print(f"[entry_watch] error {symbol}: {e}")
    except Exception as e:
        print(f"[entry_watch] cycle error: {e}")
    finally:
        db.close()
        
scheduler = BackgroundScheduler()
scheduler.add_job(check_positions,      "interval", minutes=2)
scheduler.add_job(opportunity_scan,     "interval", minutes=SCAN_INTERVAL_MIN)
scheduler.add_job(entry_watch,          "interval", minutes=2)
scheduler.add_job(refresh_signal_cache, "interval", minutes=10)
scheduler.start()


@app.on_event("startup")
async def startup():
    print("[weltbot] starting up")
    print(f"[weltbot] testnet mode: {BINANCE_TESTNET}")
    threading.Thread(target=refresh_signal_cache, daemon=True).start()
    threading.Thread(target=opportunity_scan,     daemon=True).start()


@app.on_event("shutdown")
async def shutdown():
    scheduler.shutdown()


@app.get("/")
def root():
    return {"status": "ok", "name": "WeltBot", "version": "1.0.0"}


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
        "running":      is_run,
        "paused":       paused,
        "pause_reason": reason,
        "balance_usdt": round(balance, 2),
        "testnet":      BINANCE_TESTNET,
        "last_scan":    _last_scan_log,
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
    threading.Thread(target=opportunity_scan, daemon=True).start()
    return {"message": "WeltBot started — scanning for opportunities"}


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
    threading.Thread(target=opportunity_scan, daemon=True).start()
    return {"message": "Manual scan triggered"}