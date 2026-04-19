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
    global _active_setups
    db = SessionLocal()
    try:
        state = _get_bot_state(db)
        if not state.is_running or state.paused:
            return
        from modules.universe      import get_universe
        from modules.signal_engine import scan_for_bos, ema_momentum_scan, rsi_reversal_scan

        balance    = safe_get_balance()
        open_count = db.query(Trade).filter(Trade.outcome == "OPEN").count()
        slots      = MAX_OPEN_TRADES - open_count
        print(f"[L1] scanning — balance=${balance:.2f} open={open_count}/{MAX_OPEN_TRADES}")

        if slots <= 0:
            return

        new_setups = dict(_active_setups)

        for symbol in get_universe():
            if symbol in new_setups:
                age = new_setups[symbol].get("candle_age", 0) + 1
                if age > 15:
                    print(f"[L1] {symbol} fib expired — removing")
                    del new_setups[symbol]
                    continue
                new_setups[symbol]["candle_age"] = age
                continue

            try:
                setup = scan_for_bos(symbol)
                if setup:
                    setup["zone_check"]={
                        "fib_low": setup["fib"]["zone_low"],
                        "fib_high": setup["fib"]["zone_high"],
                        "ob_low": setup["ob"]["zone_low"],
                        "ob_high": setup["ob"]["zone_high"],
                    }
                    new_setups[symbol] = setup
                    continue

                mom = ema_momentum_scan(symbol)
                if mom:
                    new_setups[symbol] = {
                        "symbol":    symbol,
                        "direction": "bullish" if mom["signal"]=="BUY" else "bearish",
                        "timeframe": "5m",
                        "bos":       mom["bos"],
                        "fib":       mom["fib"],
                        "ob":        mom["ob"],
                        "candle_age": 0,
                        "strategy":  "EMA_MOMENTUM",
                        "direct_signal": mom,
                    }
                    continue

                rsi = rsi_reversal_scan(symbol)
                if rsi:
                    new_setups[symbol] = {
                        "symbol":    symbol,
                        "direction": "bullish" if rsi["signal"]=="BUY" else "bearish",
                        "timeframe": "5m",
                        "bos":       rsi["bos"],
                        "fib":       rsi["fib"],
                        "ob":        rsi["ob"],
                        "candle_age": 0,
                        "strategy":  "RSI_REVERSAL",
                        "direct_signal": rsi,
                    }
            except Exception as e:
                print(f"[L1] error {symbol}: {e}")

        _active_setups = new_setups
        print(f"[L1] done — {len(new_setups)} active: {list(new_setups.keys())}")

    except Exception as e:
        print(f"[L1] cycle error: {e}")
    finally:
        db.close()
from modules.market_data import get_ticker_price
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

        from modules.signal_engine import check_entry_for_setup
        from modules.position_manager import daily_drawdown_check

        if daily_drawdown_check():
            state.paused       = 1
            state.pause_reason = "Daily drawdown limit hit"
            db.commit()
            return

        slots         = MAX_OPEN_TRADES - open_count
        placed        = 0
        to_remove     = []

        symbols = list(_active_setups.keys())

        for symbol in symbols:
            if placed >= slots:
                break

            setup = _active_setups.get(symbol)
            if setup is None:
                continue

            try:
                # Quick price check before expensive API calls
                zone = setup.get("zone_check")
                if zone:
                    current = get_ticker_price(symbol)
                    if current > 0:
                        in_zone = (
                            setup["zone_check"]["fib_low"] <= current <= setup["zone_check"]["fib_high"] or
                            setup["zone_check"]["ob_low"]  <= current <= setup["zone_check"]["ob_high"]
                        )
                        if not in_zone:
                            continue # Skip if price is outside zones
                direct = setup.get("direct_signal")
                if direct:
                    success = _place_trade(direct, balance, db)
                    if success:
                        placed += 1
                        to_remove.append(symbol)
                    continue

                sig = check_entry_for_setup(setup)
                if sig:
                    success = _place_trade(sig, balance, db)
                    if success:
                        placed += 1
                        to_remove.append(symbol)
                    continue

                sig = check_entry_for_setup(setup)
                if sig:
                    success = _place_trade(sig, balance, db)
                    if success:
                        placed += 1
                        to_remove.append(symbol)
            except Exception as e:
                print(f"[L2] error {symbol}: {e}")

        for sym in to_remove:
            _active_setups.pop(sym, None)

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
scheduler.add_job(level2_entry_check, "interval", seconds=60,
                  max_instances=3, coalesce=True, misfire_grace_time=30)
scheduler.add_job(level1_bos_scan, "interval", minutes=SCAN_INTERVAL_MIN)
scheduler.add_job(refresh_signal_cache, "interval", minutes=10)
scheduler.start()


@app.on_event("startup")
async def startup():
    print(f"[weltbot] v3.0 starting — testnet={BINANCE_TESTNET}")
    threading.Thread(target=refresh_signal_cache, daemon=True).start()
    threading.Thread(target=level1_bos_scan,      daemon=True).start()
    threading.Thread(target=_keep_alive,          daemon=True).start()

def _keep_alive():
    import time
    import requests as req
    while True:
        time.sleep(600)
        try:
            req.get("https://weltbot-devzilla0196688-6ipwas0e.leapcell.dev/", timeout=10)
            print("[keep-alive] ping sent")
        except Exception:
            pass
        
@app.on_event("shutdown")
async def shutdown():
    scheduler.shutdown()


@app.api_route("/", methods=["GET", "HEAD"])
def root():
    return {"status": "ok", "name": "WeltBot", "version": "4.0.0"}

@app.get("/kaithheathcheck")
@app.get("/kaithhealthcheck")  
def health():
    return {"status": "ok"}

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