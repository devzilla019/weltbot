"""
backend/modules/position_manager.py - COMPLETE FIX
Key additions:
1. sync_exchange_positions() - fetches ALL open positions from Binance
   and syncs them into the DB so the bot can track/close them
2. check_and_exit_positions() - closes positions that hit SL/TP
3. close_all_exchange_positions() - emergency close all
"""
import os
import math
import time
import hmac
import hashlib
import requests
from datetime import datetime, timedelta
from urllib.parse import urlencode
from database import SessionLocal
from models import Trade

SL_COOLDOWN_HOURS = int(os.getenv("SL_COOLDOWN_HOURS", "6"))
DAILY_LOSS_LIMIT  = float(os.getenv("DAILY_DRAWDOWN_LIMIT", "0.05"))


def _sign(params: dict) -> dict:
    from modules.market_data import BINANCE_SECRET_KEY
    params["timestamp"]  = int(time.time() * 1000)
    params["recvWindow"] = 20000
    query = urlencode(params)
    params["signature"] = hmac.new(
        BINANCE_SECRET_KEY.encode(), query.encode(), hashlib.sha256
    ).hexdigest()
    return params


def _headers():
    from modules.market_data import BINANCE_API_KEY
    return {"X-MBX-APIKEY": BINANCE_API_KEY}


def _exec_url():
    from modules.market_data import EXEC_URL
    return EXEC_URL


def get_exchange_positions() -> list:
    """Fetch all open positions from Binance futures."""
    try:
        resp = requests.get(
            f"{_exec_url()}/fapi/v2/positionRisk",
            params=_sign({}),
            headers=_headers(),
            timeout=15,
        )
        if resp.status_code == 200:
            positions = resp.json()
            # Only return positions with non-zero size
            return [p for p in positions if float(p.get("positionAmt", 0)) != 0]
        else:
            print(f"[positions] positionRisk error: {resp.status_code} {resp.text[:100]}")
            return []
    except Exception as e:
        print(f"[positions] get_exchange_positions error: {e}")
        return []


def sync_exchange_positions():
    """
    Sync Binance exchange positions → local DB.
    If a position exists on exchange but not in DB, add it.
    This fixes the 'ghost positions' problem.
    """
    db = SessionLocal()
    try:
        positions = get_exchange_positions()
        if not positions:
            return

        from modules.market_data import get_ticker_price, compute_atr, fetch_ohlcv
        synced = 0

        for pos in positions:
            symbol_raw = pos.get("symbol", "")  # e.g. BTCUSDT
            symbol     = symbol_raw[:-4] + "/USDT" if symbol_raw.endswith("USDT") else symbol_raw
            amt        = float(pos.get("positionAmt", 0))
            entry      = float(pos.get("entryPrice", 0))

            if amt == 0 or entry == 0:
                continue

            signal = "BUY" if amt > 0 else "SELL"
            qty    = abs(amt)

            # Check if already in DB
            existing = db.query(Trade).filter(
                Trade.asset   == symbol,
                Trade.outcome == "OPEN",
            ).first()

            if existing:
                continue  # Already tracked

            # Get current price and ATR for SL/TP
            price = get_ticker_price(symbol)
            if price <= 0:
                price = entry

            try:
                df  = fetch_ohlcv(symbol, interval="15m", limit=100)
                atr = compute_atr(df) if df is not None and not df.empty else price * 0.015
            except Exception:
                atr = price * 0.015

            # Calculate SL/TP based on ATR
            buf = atr * 0.5
            rr  = 2.0
            if signal == "BUY":
                sl = round(entry - atr * 1.5, 8)
                tp = round(entry + atr * 3.0, 8)
            else:
                sl = round(entry + atr * 1.5, 8)
                tp = round(entry - atr * 3.0, 8)

            trade = Trade(
                asset            = symbol,
                signal           = signal,
                confidence       = 85.0,
                entry_price      = entry,
                stop_loss        = sl,
                take_profit      = tp,
                position_sz      = qty,
                risk_usd         = 0,
                risk_reward      = rr,
                outcome          = "OPEN",
                binance_order_id = f"synced_{int(time.time())}",
                created_at       = datetime.utcnow(),
            )
            db.add(trade)
            synced += 1
            print(f"[positions] SYNCED {signal} {symbol} qty={qty} entry={entry}")

        if synced > 0:
            db.commit()
            print(f"[positions] synced {synced} positions from exchange")

    except Exception as e:
        print(f"[positions] sync error: {e}")
    finally:
        db.close()


def close_position_on_exchange(symbol: str, signal: str, qty: float) -> dict:
    """Close a position on Binance by placing opposite market order."""
    try:
        from modules.market_data import KNOWN_RULES
        sym_clean = symbol.replace("/", "")
        rules     = KNOWN_RULES.get(sym_clean, {"step": 0.001})
        step      = rules.get("step", 0.001)

        if step > 0:
            decimals = max(0, int(round(-math.log10(step))))
            qty      = round(math.floor(qty / step) * step, decimals)

        side = "SELL" if signal == "BUY" else "BUY"

        resp = requests.post(
            f"{_exec_url()}/fapi/v1/order",
            params=_sign({
                "symbol":     sym_clean,
                "side":       side,
                "type":       "MARKET",
                "quantity":   qty,
                "reduceOnly": "true",
            }),
            headers=_headers(),
            timeout=15,
        )
        data = resp.json()
        if resp.status_code == 200:
            print(f"[positions] closed {signal} {symbol} qty={qty} on exchange")
            return {"success": True, "data": data}
        else:
            print(f"[positions] close error {symbol}: {data}")
            return {"success": False, "error": data.get("msg", str(data))}
    except Exception as e:
        print(f"[positions] close_on_exchange error: {e}")
        return {"success": False, "error": str(e)}


def close_all_exchange_positions():
    """Emergency: close ALL open positions on exchange."""
    positions = get_exchange_positions()
    results   = []
    for pos in positions:
        symbol_raw = pos.get("symbol", "")
        symbol     = symbol_raw[:-4] + "/USDT" if symbol_raw.endswith("USDT") else symbol_raw
        amt        = float(pos.get("positionAmt", 0))
        if amt == 0:
            continue
        signal = "BUY" if amt > 0 else "SELL"
        qty    = abs(amt)
        r = close_position_on_exchange(symbol, signal, qty)
        results.append({"symbol": symbol, **r})
        time.sleep(0.3)
    return results


def can_reenter(symbol: str, db) -> tuple:
    cutoff = datetime.utcnow() - timedelta(hours=SL_COOLDOWN_HOURS)
    recent_sl = db.query(Trade).filter(
        Trade.asset     == symbol,
        Trade.outcome   == "LOSS",
        Trade.closed_at >= cutoff,
    ).first()
    if recent_sl:
        return False, f"SL cooldown active for {symbol} ({SL_COOLDOWN_HOURS}h)"
    return True, "ok"


def daily_drawdown_check() -> bool:
    db = SessionLocal()
    try:
        from modules.market_data import get_balance
        balance = get_balance()
        today   = datetime.utcnow().date()
        start   = datetime.combine(today, datetime.min.time())
        losses  = db.query(Trade).filter(
            Trade.outcome   == "LOSS",
            Trade.closed_at >= start,
        ).all()
        total_loss = sum(abs(t.pnl or 0) for t in losses)
        if balance > 0 and total_loss / balance >= DAILY_LOSS_LIMIT:
            print(f"[positions] daily drawdown hit: ${total_loss:.2f}")
            return True
        return False
    except Exception as e:
        print(f"[positions] drawdown check error: {e}")
        return False
    finally:
        db.close()


def check_and_exit_positions():
    """
    Main position monitor — runs every 2 min.
    1. Sync any ghost positions from exchange
    2. Check SL/TP on all tracked open trades
    3. Close positions that hit SL or TP
    """
    # First sync any positions opened directly on exchange
    sync_exchange_positions()

    db = SessionLocal()
    try:
        open_trades = db.query(Trade).filter(Trade.outcome == "OPEN").all()
        if not open_trades:
            return

        from modules.market_data import get_ticker_price

        for t in open_trades:
            if not t.stop_loss or not t.take_profit or not t.entry_price:
                continue

            current = get_ticker_price(t.asset)
            if current <= 0:
                continue

            hit_tp = (t.signal=="BUY"  and current >= t.take_profit) or \
                     (t.signal=="SELL" and current <= t.take_profit)
            hit_sl = (t.signal=="BUY"  and current <= t.stop_loss)  or \
                     (t.signal=="SELL" and current >= t.stop_loss)

            if not hit_tp and not hit_sl:
                continue

            outcome = "WIN" if hit_tp else "LOSS"

            # Close on exchange first
            result = close_position_on_exchange(t.asset, t.signal, t.position_sz or 0)

            # Calculate PnL
            if t.signal == "BUY":
                pnl = (current - t.entry_price) * (t.position_sz or 0)
            else:
                pnl = (t.entry_price - current) * (t.position_sz or 0)

            t.outcome   = outcome
            t.pnl       = round(pnl, 4)
            t.closed_at = datetime.utcnow()
            db.commit()

            # Update Kelly stats
            try:
                from modules.risk_manager import update_compound_stats
                from modules.market_data  import get_balance
                update_compound_stats(won=(outcome=="WIN"), pnl=pnl, balance=get_balance())
            except Exception:
                pass

            print(f"[positions] {outcome} {t.asset} @ {current} pnl=${pnl:.4f}")

    except Exception as e:
        print(f"[positions] check error: {e}")
    finally:
        db.close()
