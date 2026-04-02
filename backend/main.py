from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from apscheduler.schedulers.background import BackgroundScheduler
from database import engine, Base, SessionLocal
from models import SignalCache
from modules.signal_engine import compute_signal
from modules.risk_manager  import calculate_risk
from routers import signals, trades, analytics
from config import ALL_ASSETS, CRYPTO_ASSETS, EQUITY_ASSETS
import json

Base.metadata.create_all(bind=engine)

app = FastAPI(title="AI Trading Copilot", version="2.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(signals.router)
app.include_router(trades.router)
app.include_router(analytics.router)

def refresh_cache(assets):
    db = SessionLocal()
    try:
        for symbol in assets:
            try:
                sig = compute_signal(symbol)
                if "error" in sig:
                    continue
                atr  = sig["market"].get("atr")
                risk = calculate_risk(
                    sig["market"]["price"],
                    sig["signal"],
                    sig["confidence"],
                    atr=atr
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
                print(f"[scheduler] refreshed {symbol}")
            except Exception as e:
                print(f"[scheduler] error {symbol}: {e}")
    finally:
        db.close()

scheduler = BackgroundScheduler()
scheduler.add_job(lambda: refresh_cache(CRYPTO_ASSETS), "interval", seconds=60)
scheduler.add_job(lambda: refresh_cache(EQUITY_ASSETS), "interval", seconds=300)
scheduler.start()

@app.on_event("startup")
async def startup():
    refresh_cache(ALL_ASSETS)

@app.on_event("shutdown")
async def shutdown():
    scheduler.shutdown()

@app.get("/")
def root():
    return {"status": "ok", "message": "Trading Copilot running"}
