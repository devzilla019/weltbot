from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session
from sqlalchemy import func
from database import get_db
from models import Trade
import os

router = APIRouter(prefix="/api/analytics", tags=["analytics"])

# Runtime config store — these override env vars while server is running
_runtime_config = {
    "binance_key":    os.getenv("BINANCE_API_KEY",    ""),
    "binance_secret": os.getenv("BINANCE_SECRET_KEY", ""),
    "testnet":        os.getenv("BINANCE_TESTNET",    "true").lower() == "true",
    "risk_pct":       float(os.getenv("MAX_RISK_PCT",         "0.01")),
    "max_trades":     int(os.getenv("MAX_OPEN_TRADES",        "3")),
    "min_conf":       float(os.getenv("MIN_CONFIDENCE",       "85.0")),
    "daily_limit":    float(os.getenv("DAILY_DRAWDOWN_LIMIT", "0.05")),
    "scan_interval":  int(os.getenv("SCAN_INTERVAL_MIN",      "15")),
    "leverage_100":   98,
    "leverage_50":    95,
    "leverage_20":    90,
    "leverage_10":    85,
}


@router.get("/summary")
def summary(db: Session = Depends(get_db)):
    total   = db.query(Trade).count()
    wins    = db.query(Trade).filter(Trade.outcome == "WIN").count()
    losses  = db.query(Trade).filter(Trade.outcome == "LOSS").count()
    open_ct = db.query(Trade).filter(Trade.outcome == "OPEN").count()
    pnl     = db.query(func.sum(Trade.pnl)).scalar() or 0.0
    win_rate = round(wins / max(wins + losses, 1) * 100, 1)
    return {
        "total":     total,
        "wins":      wins,
        "losses":    losses,
        "open":      open_ct,
        "win_rate":  win_rate,
        "total_pnl": round(float(pnl), 4),
    }


@router.get("/portfolio")
def portfolio(db: Session = Depends(get_db)):
    from modules.market_data import get_balance, get_ticker_price
    balance     = get_balance()
    open_trades = db.query(Trade).filter(Trade.outcome == "OPEN").all()
    positions   = []
    unrealized  = 0.0
    for t in open_trades:
        current = get_ticker_price(t.asset)
        if current > 0 and t.entry_price:
            pnl_pct = (current - t.entry_price) / t.entry_price
            if t.signal == "SELL":
                pnl_pct = -pnl_pct
            unreal = round(pnl_pct * (t.position_sz or 0) * (t.entry_price or 1), 4)
            unrealized += unreal
            positions.append({
                "trade_id":   t.id,
                "asset":      t.asset,
                "signal":     t.signal,
                "confidence": t.confidence,
                "entry":      t.entry_price,
                "current":    current,
                "sl":         t.stop_loss,
                "tp":         t.take_profit,
                "pnl_pct":    round(pnl_pct * 100, 3),
                "unrealized": unreal,
                "size":       t.position_sz,
            })
    return {
        "balance_usdt":   round(balance, 4),
        "open_count":     len(positions),
        "unrealized_pnl": round(unrealized, 4),
        "positions":      positions,
    }


@router.get("/news")
def news_status():
    try:
        from modules.news_monitor import get_news_summary
        return get_news_summary()
    except Exception:
        return {"blackout": False, "reason": None}


# ── API KEY MANAGEMENT ─────────────────────────────────────────────────────────

@router.post("/settings/apikeys")
async def update_api_keys(request: Request):
    """
    Update Binance API keys at runtime.
    Keys are applied immediately — bot reconnects on next scan.
    """
    body = await request.json()
    key    = body.get("api_key",    "").strip()
    secret = body.get("api_secret", "").strip()

    if not key or not secret:
        return {"success": False, "error": "Both API key and secret key are required"}

    # Store in runtime config
    _runtime_config["binance_key"]    = key
    _runtime_config["binance_secret"] = secret

    # Apply to os.environ so all modules pick them up immediately
    os.environ["BINANCE_API_KEY"]    = key
    os.environ["BINANCE_SECRET_KEY"] = secret

    # Reset market_data module state so it reconnects with new keys
    try:
        import modules.market_data as md
        md.BINANCE_API_KEY    = key
        md.BINANCE_SECRET_KEY = secret
        md._cached_balance    = 0.0
        md._balance_ts        = 0.0
    except Exception as e:
        print(f"[settings] market_data reset error: {e}")

    # Test connection immediately
    try:
        from modules.market_data import get_balance
        balance = get_balance()
        if balance > 0:
            return {
                "success": True,
                "message": f"Connected! Balance: ${balance:.2f} USDT",
                "balance": balance,
            }
        else:
            return {
                "success":  True,
                "message":  "Keys saved. Balance shows $0 — verify keys have Futures permission.",
                "balance":  0,
            }
    except Exception as e:
        return {"success": False, "error": f"Keys saved but connection failed: {str(e)}"}


@router.get("/settings/apikeys")
def get_api_key_status():
    key = _runtime_config.get("binance_key", "")
    return {
        "configured":  bool(key),
        "key_preview": f"{key[:6]}...{key[-4:]}" if len(key) > 10 else "not set",
        "testnet":     _runtime_config.get("testnet", True),
    }


# ── BOT SETTINGS ──────────────────────────────────────────────────────────────

@router.post("/settings/bot")
async def update_bot_settings(request: Request):
    """Update bot trading parameters at runtime."""
    body = await request.json()

    import config as cfg

    if "risk_pct" in body:
        val = float(body["risk_pct"])
        _runtime_config["risk_pct"] = val
        cfg.MAX_RISK_PCT = val / 100
        os.environ["MAX_RISK_PCT"] = str(val / 100)

    if "max_trades" in body:
        val = int(body["max_trades"])
        _runtime_config["max_trades"] = val
        cfg.MAX_OPEN_TRADES = val
        os.environ["MAX_OPEN_TRADES"] = str(val)

    if "min_conf" in body:
        val = float(body["min_conf"])
        _runtime_config["min_conf"] = val
        cfg.MIN_CONFIDENCE = val
        os.environ["MIN_CONFIDENCE"] = str(val)

    if "daily_limit" in body:
        val = float(body["daily_limit"])
        _runtime_config["daily_limit"] = val
        cfg.DAILY_DRAWDOWN_LIMIT = val / 100
        os.environ["DAILY_DRAWDOWN_LIMIT"] = str(val / 100)

    return {"success": True, "message": "Settings applied", "config": _runtime_config}


@router.get("/settings/bot")
def get_bot_settings():
    """Return current bot settings."""
    return {
        "risk_pct":    _runtime_config["risk_pct"] * 100,
        "max_trades":  _runtime_config["max_trades"],
        "min_conf":    _runtime_config["min_conf"],
        "daily_limit": _runtime_config["daily_limit"] * 100,
        "scan_interval": _runtime_config["scan_interval"],
        "leverage_tiers": {
            "100x": _runtime_config["leverage_100"],
            "50x":  _runtime_config["leverage_50"],
            "20x":  _runtime_config["leverage_20"],
            "10x":  _runtime_config["leverage_10"],
        },
    }


# ── TESTNET/MAINNET TOGGLE ────────────────────────────────────────────────────

@router.post("/settings/network")
async def toggle_network(request: Request):
    """Switch between testnet and mainnet."""
    body    = await request.json()
    testnet = body.get("testnet", True)

    _runtime_config["testnet"] = testnet
    os.environ["BINANCE_TESTNET"] = "true" if testnet else "false"

    try:
        import config as cfg
        cfg.BINANCE_TESTNET = testnet

        import modules.market_data as md
        md.BINANCE_TESTNET = testnet
        # Update execution URL
        if testnet:
            md.EXEC_URL = os.getenv("FUTURES_EXEC_URL", "https://testnet.binancefuture.com")
        else:
            md.EXEC_URL = "https://fapi.binance.com"
        md._cached_balance = 0.0
        md._balance_ts     = 0.0
    except Exception as e:
        print(f"[settings] network toggle error: {e}")

    mode = "TESTNET" if testnet else "MAINNET"
    return {"success": True, "message": f"Switched to {mode}", "testnet": testnet}
