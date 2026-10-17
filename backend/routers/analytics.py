from fastapi import APIRouter, Depends, Request, HTTPException
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

            # ── Risk / reward metrics for the live dashboard ──────────────
            size = t.position_sz or 0
            entry = t.entry_price or 0
            sl = t.stop_loss or 0
            tp = t.take_profit or 0

            risk_usd = abs(entry - sl) * size if sl else 0.0
            reward_usd = abs(tp - entry) * size if tp else 0.0
            rr = (reward_usd / risk_usd) if risk_usd > 0 else 0.0
            risk_pct = (risk_usd / balance * 100) if balance > 0 else 0.0
            reward_pct = (reward_usd / balance * 100) if balance > 0 else 0.0

            # Progress toward TP (0% at SL, 100% at TP)
            span = (tp - sl) if (tp and sl) else 0
            progress = ((current - sl) / span * 100) if span else 0
            progress = max(0.0, min(100.0, progress))

            positions.append({
                "trade_id":   t.id,
                "asset":      t.asset,
                "signal":     t.signal,
                "confidence": t.confidence,
                "entry":      entry,
                "current":    current,
                "sl":         sl,
                "tp":         tp,
                "pnl_pct":    round(pnl_pct * 100, 3),
                "unrealized": unreal,
                "size":       size,
                # risk / reward
                "risk_usd":     round(risk_usd, 4),
                "reward_usd":   round(reward_usd, 4),
                "risk_pct":     round(risk_pct, 2),
                "reward_pct":   round(reward_pct, 2),
                "risk_reward":  round(rr, 2),
                "progress":     round(progress, 1),
            })

    # ── Forex (Capital.com) balance — separate from crypto ────────────────────
    forex_balance     = 0.0
    forex_profit_loss = 0.0
    forex_connected   = False
    try:
        from config import FOREX_ENABLED
        if FOREX_ENABLED:
            from modules.market_data_forex import get_capital_balance
            fb = get_capital_balance()
            forex_balance     = fb.get("balance", 0.0)
            forex_profit_loss = fb.get("profit_loss", 0.0)
            forex_connected   = fb.get("connected", False)
    except Exception as e:
        print(f"[analytics] forex balance error: {e}")

    total_balance = round(balance + forex_balance, 2)

    # ── Aggregate risk / reward across all open positions ─────────────────────
    total_risk   = sum(p["risk_usd"] for p in positions)
    total_reward = sum(p["reward_usd"] for p in positions)
    avg_rr = (total_reward / total_risk) if total_risk > 0 else 0.0
    risk_pct_of_balance = (total_risk / balance * 100) if balance > 0 else 0.0

    return {
        "balance_usdt":       round(balance, 4),          # crypto / Binance
        "forex_balance":      round(forex_balance, 2),    # Capital.com balance
        "forex_profit_loss":  round(forex_profit_loss, 2),
        "forex_connected":    forex_connected,
        "total_balance":      total_balance,              # crypto + forex
        "open_count":         len(positions),
        "unrealized_pnl":     round(unrealized, 4),
        "positions":          positions,
        # aggregate risk dashboard
        "total_risk_usd":     round(total_risk, 2),
        "total_reward_usd":   round(total_reward, 2),
        "avg_risk_reward":    round(avg_rr, 2),
        "risk_pct_of_balance": round(risk_pct_of_balance, 2),
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


# ── RISK SETTINGS ─────────────────────────────────────────────────────────────

@router.get("/settings/risk")
def get_risk_settings():
    """
    Current risk settings plus the bounds each one is validated against.

    Everything here is user-controllable, including switching the daily loss
    limits off — a hard stop that cannot be relaxed makes a strategy
    impossible to evaluate, because nothing fires again until the next day.

    The returned `limits` are the same bounds enforced server-side on write,
    so the UI and the API can never disagree about what is acceptable.
    """
    from modules.risk_settings import get_settings, _BOUNDS

    rs = get_settings(force=True)

    units = {
        "daily_loss_limit": "fraction",
        "risk_pct":         "fraction",
        "min_confidence":   "percent",
        "max_trades":       "count",
    }
    steps = {"daily_loss_limit": 0.005, "risk_pct": 0.001,
             "min_confidence": 1.0, "max_trades": 1}

    limits = {}
    for key, (low, high) in _BOUNDS.items():
        for tag, unit in units.items():
            if key.endswith(tag):
                limits[key] = {"min": low, "max": high,
                               "step": steps[tag], "unit": unit}
                break

    return {
        "settings": rs,
        "limits": limits,
        "defaults": {
            "forex_daily_loss_limit": 0.06, "crypto_daily_loss_limit": 0.05,
            "forex_risk_pct": 0.02, "crypto_risk_pct": 0.01,
            "forex_min_confidence": 88.0, "crypto_min_confidence": 90.0,
            "forex_max_trades": 3, "crypto_max_trades": 2,
        },
    }


@router.post("/settings/risk")
async def update_risk_settings(request: Request):
    """
    Apply partial risk-setting changes.

    Unknown keys and out-of-range values are rejected and reported rather than
    silently coerced, so a typo cannot quietly become a different limit than
    the one the user asked for.
    """
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="Expected a JSON object")

    from modules.risk_settings import update_settings, validate_changes

    _, rejected = validate_changes(body)
    updated = update_settings(body)
    return {
        "success":   True,
        "message":   "Settings applied" if not rejected else "Settings applied with rejections",
        "settings":  updated,
        "rejected":  [{"key": k, "reason": r} for k, r in rejected],
    }


@router.post("/settings/risk/reset")
def reset_risk_settings():
    """Restore every risk setting to its default."""
    from modules.risk_settings import update_settings

    defaults = {
        "forex_enabled": True, "crypto_enabled": True,
        "forex_daily_limit_enabled": True, "forex_daily_loss_limit": 0.06,
        "crypto_daily_limit_enabled": True, "crypto_daily_loss_limit": 0.05,
        "forex_risk_pct": 0.02, "crypto_risk_pct": 0.01,
        "forex_min_confidence": 88.0, "crypto_min_confidence": 90.0,
        "forex_max_trades": 3, "crypto_max_trades": 2,
        "diagnostic_mode": False,
        "auto_resume": True, "weekend_guard": True,
    }
    return {"success": True, "settings": update_settings(defaults)}


# ── DIAGNOSTICS ───────────────────────────────────────────────────────────────

@router.get("/diagnostics")
def get_diagnostics(limit: int = 50):
    """
    Recent signal evaluations with the reason each one passed or was blocked.

    These are SIMULATED evaluations: no entry here represents an executed
    order. When diagnostic mode is on, every row is marked simulated and the
    execution guard suppresses any order the scanner would otherwise place.
    """
    from main import get_diagnostics as _get, record_diagnostic
    from modules.risk_settings import get_settings, diagnostic_mode

    rs = get_settings(force=True)
    return {
        "diagnostic_mode": bool(rs.get("diagnostic_mode", False)),
        "simulated":       diagnostic_mode(),
        "note":            ("Diagnostic mode is ON — signals are evaluated but no "
                            "orders are submitted, modified, or closed."
                            if rs.get("diagnostic_mode")
                            else "Diagnostic mode is OFF — normal trading is active; "
                                 "entries below show the last observed decisions."),
        "entries":         _get(limit),
    }


@router.post("/diagnostics/clear")
def clear_diagnostics():
    """Drop the in-memory diagnostic ring."""
    from main import clear_diagnostics as _clear

    return {"success": True, "cleared": _clear()}


@router.post("/diagnostics/evaluate")
def evaluate_symbol(payload: dict):
    """
    Run one symbol through the signal path WITHOUT executing anything.

    This is a dry evaluation: it reports what the engine would decide and why,
    and always refuses to place an order regardless of diagnostic mode.
    """
    symbol = (payload or {}).get("symbol")
    market = (payload or {}).get("market", "crypto")
    if not symbol:
        raise HTTPException(status_code=400, detail="symbol is required")

    from main import record_diagnostic

    try:
        if market == "forex":
            from modules.forex_position_manager import can_open_forex_trade
            allowed, reason = can_open_forex_trade(symbol)
        else:
            # Dry evaluation against the ONE live strategy. This used to run the
            # retired crypto CRT scan, which would report a verdict from an
            # engine that can no longer trade — a diagnostic that contradicts
            # the runtime is worse than no diagnostic.
            from modules.silver_bullet import get_daily_bias
            from modules.forex_signal_engine import MIN_CONFIDENCE, current_session

            session = current_session()
            if not session:
                allowed, reason = False, "outside the Silver Bullet session windows"
            else:
                bias = get_daily_bias(symbol)
                if not bias:
                    allowed, reason = False, "no daily bias computed for today"
                elif bias.get("h4_bias") == "NEUTRAL":
                    allowed, reason = False, "H4 bias is NEUTRAL — no trade today"
                elif not bias.get("vp_gateable"):
                    allowed, reason = False, (
                        f"volume profile not gateable: "
                        f"{bias.get('vp_gate_reason') or 'unavailable'}")
                else:
                    allowed, reason = True, (
                        f"Silver Bullet armed in {session}, H4 "
                        f"{bias['h4_bias']} (floor {MIN_CONFIDENCE})")
    except Exception as e:
        allowed, reason = False, f"evaluation error: {e}"

    decision = "PASS" if allowed else "REJECT"
    record_diagnostic(market, symbol, decision, reason)
    return {
        "symbol":    symbol,
        "market":    market,
        "decision":  decision,
        "reason":    reason,
        "simulated": True,
        "order_placed": False,
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
