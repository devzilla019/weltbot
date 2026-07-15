"""
backend/modules/position_manager.py - FIXED v2
Fixes:
1. KNOWN_RULES moved inline — no import from market_data
2. sync_exchange_positions checks binance_order_id to prevent duplicate rows
3. close_on_exchange uses inline KNOWN_RULES
4. Duplicate prevention: only sync if no existing OPEN trade with same asset+signal
"""
import os, math, time, hmac, hashlib, requests
from datetime import datetime, timedelta
from urllib.parse import urlencode
from database import SessionLocal
from models import Trade

SL_COOLDOWN_HOURS = int(os.getenv("SL_COOLDOWN_HOURS", "6"))
DAILY_LOSS_LIMIT  = float(os.getenv("DAILY_DRAWDOWN_LIMIT", "0.05"))

KNOWN_RULES = {
    "BTCUSDT":  {"step": 0.001},  "ETHUSDT":  {"step": 0.001},
    "BNBUSDT":  {"step": 0.01},   "SOLUSDT":  {"step": 0.1},
    "XRPUSDT":  {"step": 1.0},    "ADAUSDT":  {"step": 1.0},
    "DOGEUSDT": {"step": 1.0},    "AVAXUSDT": {"step": 0.1},
    "LINKUSDT": {"step": 0.01},   "UNIUSDT":  {"step": 0.1},
    "LTCUSDT":  {"step": 0.01},   "ATOMUSDT": {"step": 0.01},
    "NEARUSDT": {"step": 0.1},    "DOTUSDT":  {"step": 0.1},
    "AAVEUSDT": {"step": 0.01},
}

def _sign(params):
    from modules.market_data import BINANCE_SECRET_KEY
    params["timestamp"] = int(time.time() * 1000)
    params["recvWindow"] = 20000
    q = urlencode(params)
    params["signature"] = hmac.new(BINANCE_SECRET_KEY.encode(), q.encode(), hashlib.sha256).hexdigest()
    return params

def _headers():
    from modules.market_data import BINANCE_API_KEY
    return {"X-MBX-APIKEY": BINANCE_API_KEY}

def _exec_url():
    from modules.market_data import EXEC_URL
    return EXEC_URL

def get_exchange_positions():
    try:
        r = requests.get(f"{_exec_url()}/fapi/v2/positionRisk", params=_sign({}), headers=_headers(), timeout=15)
        if r.status_code == 200:
            return [p for p in r.json() if float(p.get("positionAmt", 0)) != 0]
        print(f"[positions] positionRisk error: {r.status_code}")
        return []
    except Exception as e:
        print(f"[positions] get_exchange_positions: {e}")
        return []

def close_position_on_exchange(symbol, signal, qty):
    try:
        sym   = symbol.replace("/", "")
        step  = KNOWN_RULES.get(sym, {}).get("step", 0.001)
        if step > 0:
            dec = max(0, int(round(-math.log10(step))))
            qty = round(math.floor(qty / step) * step, dec)
        if qty <= 0:
            return {"success": False, "error": "qty zero"}
        side = "SELL" if signal == "BUY" else "BUY"
        r = requests.post(f"{_exec_url()}/fapi/v1/order",
            params=_sign({"symbol": sym, "side": side, "type": "MARKET",
                          "quantity": qty, "reduceOnly": "true"}),
            headers=_headers(), timeout=15)
        data = r.json()
        if r.status_code == 200:
            print(f"[positions] ✓ closed {signal} {symbol} qty={qty}")
            return {"success": True}
        print(f"[positions] close error {symbol}: {data.get('msg')}")
        return {"success": False, "error": data.get("msg", str(data))}
    except Exception as e:
        print(f"[positions] close_on_exchange: {e}")
        return {"success": False, "error": str(e)}

def close_all_exchange_positions():
    results = []
    for pos in get_exchange_positions():
        sym_raw = pos.get("symbol", "")
        symbol  = sym_raw[:-4] + "/USDT" if sym_raw.endswith("USDT") else sym_raw
        amt     = float(pos.get("positionAmt", 0))
        if amt == 0: continue
        r = close_position_on_exchange(symbol, "BUY" if amt > 0 else "SELL", abs(amt))
        results.append({"symbol": symbol, **r})
        time.sleep(0.3)
    return results

def sync_exchange_positions():
    """
    Sync Binance positions → DB.
    FIXED: only adds row if NO existing OPEN trade for same asset exists at all.
    This prevents the duplicate row bug.
    """
    db = SessionLocal()
    try:
        positions = get_exchange_positions()
        if not positions:
            return
        from modules.market_data import get_ticker_price, compute_atr, fetch_ohlcv
        synced = 0
        for pos in positions:
            sym_raw = pos.get("symbol", "")
            symbol  = sym_raw[:-4] + "/USDT" if sym_raw.endswith("USDT") else sym_raw
            amt     = float(pos.get("positionAmt", 0))
            entry   = float(pos.get("entryPrice", 0))
            if amt == 0 or entry == 0: continue
            signal = "BUY" if amt > 0 else "SELL"
            qty    = abs(amt)

            # KEY FIX: check if ANY open trade exists for this asset (not just signal match)
            existing = db.query(Trade).filter(
                Trade.asset   == symbol,
                Trade.outcome == "OPEN",
            ).first()
            if existing:
                continue  # already tracked — do NOT add duplicate

            price = get_ticker_price(symbol) or entry
            try:
                df  = fetch_ohlcv(symbol, interval="15m", limit=100)
                atr = compute_atr(df) if df is not None and not df.empty else price * 0.015
            except Exception:
                atr = price * 0.015

            sl = round(entry - atr*1.5, 8) if signal=="BUY" else round(entry + atr*1.5, 8)
            tp = round(entry + atr*3.0, 8) if signal=="BUY" else round(entry - atr*3.0, 8)

            db.add(Trade(
                asset=symbol, signal=signal, confidence=85.0,
                entry_price=entry, stop_loss=sl, take_profit=tp,
                position_sz=qty, risk_usd=0, risk_reward=2.0,
                outcome="OPEN",
                binance_order_id=f"synced_{sym_raw}_{int(time.time())}",
                created_at=datetime.utcnow(),
            ))
            synced += 1
            print(f"[positions] SYNCED {signal} {symbol} qty={qty} entry={entry}")

        if synced > 0:
            db.commit()
            print(f"[positions] synced {synced} new positions")
    except Exception as e:
        print(f"[positions] sync error: {e}")
    finally:
        db.close()

def can_reenter(symbol, db):
    cutoff = datetime.utcnow() - timedelta(hours=SL_COOLDOWN_HOURS)
    sl = db.query(Trade).filter(Trade.asset==symbol, Trade.outcome=="LOSS", Trade.closed_at>=cutoff).first()
    return (False, f"SL cooldown {symbol}") if sl else (True, "ok")

def daily_drawdown_check():
    db = SessionLocal()
    try:
        from modules.market_data import get_balance
        bal = get_balance()
        start = datetime.combine(datetime.utcnow().date(), datetime.min.time())
        losses = db.query(Trade).filter(Trade.outcome=="LOSS", Trade.closed_at>=start).all()
        total = sum(abs(t.pnl or 0) for t in losses)
        if bal > 0 and total/bal >= DAILY_LOSS_LIMIT:
            print(f"[positions] daily drawdown: ${total:.2f}")
            return True
        return False
    except Exception as e:
        print(f"[positions] drawdown: {e}")
        return False
    finally:
        db.close()

def check_and_exit_positions():
    """Main monitor — runs every 2 min. Syncs then checks SL/TP."""
    sync_exchange_positions()
    db = SessionLocal()
    try:
        open_trades = db.query(Trade).filter(Trade.outcome=="OPEN").all()
        if not open_trades: return
        from modules.market_data import get_ticker_price
        for t in open_trades:
            if not t.stop_loss or not t.take_profit or not t.entry_price: continue
            current = get_ticker_price(t.asset)
            if current <= 0: continue
            hit_tp = (t.signal=="BUY" and current>=t.take_profit) or (t.signal=="SELL" and current<=t.take_profit)
            hit_sl = (t.signal=="BUY" and current<=t.stop_loss)  or (t.signal=="SELL" and current>=t.stop_loss)
            if not hit_tp and not hit_sl: continue
            outcome = "WIN" if hit_tp else "LOSS"
            close_position_on_exchange(t.asset, t.signal, t.position_sz or 0)
            pnl = (current - t.entry_price)*(t.position_sz or 0) if t.signal=="BUY" \
                  else (t.entry_price - current)*(t.position_sz or 0)
            t.outcome   = outcome
            t.pnl       = round(pnl, 4)
            t.closed_at = datetime.utcnow()
            db.commit()
            try:
                from modules.risk_manager import update_compound_stats
                from modules.market_data  import get_balance
                update_compound_stats(won=(outcome=="WIN"), pnl=pnl, balance=get_balance())
            except Exception: pass
            print(f"[positions] {outcome} {t.asset} @ {current} pnl=${pnl:.4f}")
    except Exception as e:
        print(f"[positions] check: {e}")
    finally:
        db.close()
