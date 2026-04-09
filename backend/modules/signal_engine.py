"""
WeltBot Signal Engine v3.0
State-driven SMC strategy.
BOS stored in DB — entry checked every 60 seconds.
Reduces API calls by 80% and catches entries within 1 minute.
"""

import pandas as pd
import numpy as np
from modules.market_data import fetch_ohlcv, compute_atr


def detect_swings(df: pd.DataFrame, lookback: int = 2) -> pd.DataFrame:
    highs = df["high"]
    lows  = df["low"]
    n     = len(df)
    sh    = [False] * n
    sl    = [False] * n
    for i in range(lookback, n - lookback):
        if all(highs.iloc[i] > highs.iloc[i-j] for j in range(1, lookback+1)) and \
           all(highs.iloc[i] > highs.iloc[i+j] for j in range(1, lookback+1)):
            sh[i] = True
        if all(lows.iloc[i] < lows.iloc[i-j] for j in range(1, lookback+1)) and \
           all(lows.iloc[i] < lows.iloc[i+j] for j in range(1, lookback+1)):
            sl[i] = True
    df = df.copy()
    df["swing_high"] = sh
    df["swing_low"]  = sl
    return df


def detect_bos(df: pd.DataFrame) -> dict | None:
    df     = detect_swings(df, lookback=2)
    n      = len(df)
    sh_idx = [i for i in range(n-2) if df["swing_high"].iloc[i]]
    sl_idx = [i for i in range(n-2) if df["swing_low"].iloc[i]]
    if not sh_idx and not sl_idx:
        return None
    last_close = float(df["close"].iloc[-1])

    if sh_idx:
        shi = sh_idx[-1]
        shp = float(df["high"].iloc[shi])
        if last_close > shp:
            sl_before = [i for i in sl_idx if i < shi]
            if sl_before:
                ili = sl_before[-1]
                return {
                    "direction":        "bullish",
                    "bos_level":        shp,
                    "impulse_low":      float(df["low"].iloc[ili]),
                    "impulse_high":     shp,
                    "impulse_low_idx":  ili,
                    "impulse_high_idx": shi,
                    "bos_close":        last_close,
                }

    if sl_idx:
        sli = sl_idx[-1]
        slp = float(df["low"].iloc[sli])
        if last_close < slp:
            sh_before = [i for i in sh_idx if i < sli]
            if sh_before:
                ihi = sh_before[-1]
                return {
                    "direction":         "bearish",
                    "bos_level":         slp,
                    "impulse_high":      float(df["high"].iloc[ihi]),
                    "impulse_low":       slp,
                    "impulse_high_idx":  ihi,
                    "impulse_low_idx":   sli,
                    "bos_close":         last_close,
                }
    return None


def calculate_fib_zone(bos: dict) -> dict:
    hi  = bos["impulse_high"]
    lo  = bos["impulse_low"]
    rng = hi - lo
    if bos["direction"] == "bullish":
        return {
            "zone_high": round(hi - rng * 0.500, 8),
            "zone_low":  round(hi - rng * 0.618, 8),
            "range":     round(rng, 8),
        }
    else:
        return {
            "zone_high": round(lo + rng * 0.618, 8),
            "zone_low":  round(lo + rng * 0.500, 8),
            "range":     round(rng, 8),
        }


def identify_order_block(df: pd.DataFrame, bos: dict, fib: dict) -> dict | None:
    start = bos.get("impulse_low_idx") if bos["direction"] == "bullish" \
            else bos.get("impulse_high_idx")
    if start is None:
        return None
    search = min(25, start)
    for i in range(start, max(0, start - search) - 1, -1):
        c  = df.iloc[i]
        oh = float(c["high"])
        ol = float(c["low"])
        oc = float(c["close"])
        oo = float(c["open"])
        is_bearish = oc < oo
        is_bullish = oc > oo
        overlap    = oh >= fib["zone_low"] and ol <= fib["zone_high"]
        if not overlap:
            continue
        if bos["direction"] == "bullish" and is_bearish:
            return {"ob_high": oh, "ob_low": ol, "ob_idx": i, "direction": "bullish"}
        if bos["direction"] == "bearish" and is_bullish:
            return {"ob_high": oh, "ob_low": ol, "ob_idx": i, "direction": "bearish"}
    return None


def check_ma_filter(df: pd.DataFrame, direction: str) -> bool:
    close     = df["close"]
    n         = len(close)
    ema50     = close.ewm(span=50,  adjust=False).mean()
    ema50_now = float(ema50.iloc[-1])
    ema50_prev= float(ema50.iloc[-4])
    price     = float(close.iloc[-1])
    rising    = ema50_now > ema50_prev
    falling   = ema50_now < ema50_prev
    if n >= 200:
        ema200 = float(close.ewm(span=200, adjust=False).mean().iloc[-1])
        if direction == "bullish":
            return ema50_now > ema200 and price > ema50_now
        else:
            return ema50_now < ema200 and price < ema50_now
    else:
        if direction == "bullish":
            return rising and price > ema50_now
        else:
            return falling and price < ema50_now


def check_entry_confirmation(df: pd.DataFrame, direction: str) -> dict:
    if df is None or len(df) < 3:
        return {"confirmed": False, "type": None}
    last  = df.iloc[-1]
    prev  = df.iloc[-2]
    prev2 = df.iloc[-3]
    o, c  = float(last["open"]),  float(last["close"])
    po,pc = float(prev["open"]),  float(prev["close"])
    hi,lo = float(last["high"]),  float(last["low"])
    rng   = hi - lo if hi != lo else 0.0001
    body  = abs(c - o)
    uw    = hi - max(o, c)
    lw    = min(o, c) - lo

    if direction == "bullish":
        if c > o:
            if c > po and o < pc:
                return {"confirmed": True, "type": "engulfing"}
            if body / rng > 0.55:
                return {"confirmed": True, "type": "momentum"}
            if c > float(prev["high"]) and float(prev["high"]) <= float(prev2["high"]):
                return {"confirmed": True, "type": "ib_breakout"}
        if lw > body * 1.5 and lw > uw:
            return {"confirmed": True, "type": "pin_bar"}
    else:
        if c < o:
            if c < po and o > pc:
                return {"confirmed": True, "type": "engulfing"}
            if body / rng > 0.55:
                return {"confirmed": True, "type": "momentum"}
            if c < float(prev["low"]) and float(prev["low"]) >= float(prev2["low"]):
                return {"confirmed": True, "type": "ib_breakout"}
        if uw > body * 1.5 and uw > lw:
            return {"confirmed": True, "type": "pin_bar"}

    return {"confirmed": False, "type": None}


def calculate_sl_tp(entry: float, ob: dict, direction: str,
                    atr: float, df_15m=None) -> dict:
    buf  = atr * 0.3
    if direction == "bullish":
        sl   = round(ob["ob_low"] - buf, 8)
        risk = entry - sl
        base_tp = round(entry + risk * 2.0, 8)
        ext_tp  = round(entry + risk * 3.0, 8)
    else:
        sl   = round(ob["ob_high"] + buf, 8)
        risk = sl - entry
        base_tp = round(entry - risk * 2.0, 8)
        ext_tp  = round(entry - risk * 3.0, 8)

    rr = 2.0
    tp = base_tp

    if df_15m is not None and not df_15m.empty:
        swings = detect_swings(df_15m)
        if direction == "bullish":
            sh_prices = [float(df_15m["high"].iloc[i])
                         for i in range(len(df_15m))
                         if swings["swing_high"].iloc[i] and
                         float(df_15m["high"].iloc[i]) > entry]
            if sh_prices and min(sh_prices) >= ext_tp:
                tp  = ext_tp
                rr  = 3.0
        else:
            sl_prices = [float(df_15m["low"].iloc[i])
                         for i in range(len(df_15m))
                         if swings["swing_low"].iloc[i] and
                         float(df_15m["low"].iloc[i]) < entry]
            if sl_prices and max(sl_prices) <= ext_tp:
                tp  = ext_tp
                rr  = 3.0

    return {
        "stop_loss":   sl,
        "take_profit": tp,
        "risk_dist":   round(abs(risk), 8),
        "risk_pct":    round(abs(risk) / entry * 100, 3),
        "rr":          rr,
    }

def _base_hold(symbol, price, reason, extra=None):
    base = {
        "symbol": symbol, "signal": "HOLD", "reason": reason,
        "confidence": 0, "raw_score": 0, "sub_scores": {},
        "market": {
            "price": price, "atr": 0, "atr_ok": True,
            "rsi": 50, "rsi_score": 0,
            "macd": {"histogram": 0}, "macd_score": 0,
            "trend": {"score": 0, "label": "neutral"},
            "volume": {"score": 0}, "change_pct": 0,
        },
        "sentiment": {"score": 0, "label": "neutral"},
    }
    if extra:
        base.update(extra)
    return base


def scan_for_bos(symbol: str) -> dict | None:
    """
    Level 1 scan — runs every 15 minutes.
    Returns BOS + Fib + OB if found, None otherwise.
    Does NOT check entry candles.
    """
    df = fetch_ohlcv(symbol, interval="15m", limit=100)
    if df.empty or len(df) < 20:
        return None
    bos = detect_bos(df)
    if not bos:
        return None
    fib = calculate_fib_zone(bos)
    ob  = identify_order_block(df, bos, fib)
    if not ob:
        return None
    ma_ok = check_ma_filter(df, bos["direction"])
    if not ma_ok:
        return None
    return {
        "symbol":    symbol,
        "direction": bos["direction"],
        "bos":       bos,
        "fib":       fib,
        "ob":        ob,
        "df_15m":    df,
    }


def check_entry_for_setup(setup: dict) -> dict | None:
    symbol    = setup["symbol"]
    bos       = setup["bos"]
    fib       = setup["fib"]
    ob        = setup["ob"]
    direction = setup["direction"]

    df_1m  = fetch_ohlcv(symbol, interval="1m", limit=10)
    df_5m  = fetch_ohlcv(symbol, interval="5m", limit=10)
    df_15m = fetch_ohlcv(symbol, interval="15m", limit=100)

    if df_1m is None or df_1m.empty:
        return None

    current_price = float(df_1m["close"].iloc[-1])

    in_fib = fib["zone_low"] <= current_price <= fib["zone_high"]
    in_ob  = ob["ob_low"]    <= current_price <= ob["ob_high"]

    if not in_fib or not in_ob:
        return None

    if direction == "bullish" and current_price < bos.get("impulse_low", 0):
        return None
    if direction == "bearish" and current_price > bos.get("impulse_high", float("inf")):
        return None

    entry_tf   = "1m"
    entry_conf = check_entry_confirmation(df_1m, direction)

    if not entry_conf["confirmed"]:
        if df_5m is not None and not df_5m.empty:
            entry_tf   = "5m"
            entry_conf = check_entry_confirmation(df_5m, direction)

    if not entry_conf["confirmed"]:
        return None

    atr_val = 0.0
    if df_15m is not None and not df_15m.empty and len(df_15m) >= 15:
        atr_val = compute_atr(df_15m)
    else:
        atr_val = current_price * 0.015

    sl_tp  = calculate_sl_tp(current_price, ob, direction, atr_val)
    signal = "BUY" if direction == "bullish" else "SELL"

    print(f"[entry] ALL CONDITIONS MET — {symbol} {signal} | {entry_conf['type']} on {entry_tf} @ {current_price}")

    return {
        "symbol":     symbol,
        "signal":     signal,
        "confidence": 90.0,
        "raw_score":  0.9 if signal == "BUY" else -0.9,
        "reasoning":  [
            f"BOS {direction} — broke ${bos.get('bos_level', 0):.6f}",
            f"Fib+OB confluence zone hit",
            f"Entry: {entry_conf['type']} on {entry_tf}",
        ],
        "bos":        bos,
        "fib":        fib,
        "ob":         ob,
        "entry_tf":   entry_tf,
        "entry_type": entry_conf["type"],
        "sl_tp":      sl_tp,
        "sub_scores": {"bos": 1, "fib": 1, "ob": 1, "ma": 1, "entry": 1},
        "market": {
            "price":      current_price,
            "atr":        atr_val,
            "atr_ok":     True,
            "rsi":        50,
            "rsi_score":  0,
            "macd":       {"histogram": 0},
            "macd_score": 0,
            "trend":      {"score": 1.0 if direction == "bullish" else -1.0, "label": direction},
            "volume":     {"score": 0},
            "change_pct": 0,
        },
        "sentiment": {"score": 0, "label": "neutral"},
    }
try:
    from modules.sentiment import get_sentiment
    sent = get_sentiment(symbol)
    conf = 90.0
    if direction == "bullish" and sent.get("label") == "bullish":
        conf = 95.0
    elif direction == "bearish" and sent.get("label") == "bearish":
        conf = 95.0
    elif (direction == "bullish" and sent.get("label") == "bearish") or \
         (direction == "bearish" and sent.get("label") == "bullish"):
        conf = 85.0
except Exception:
    conf = 90.0
   
def compute_signal(symbol: str, learned_bias: float = 0.0) -> dict:
    """
    Legacy compatibility wrapper — used by cache refresh and API.
    Runs full analysis for dashboard display.
    """
    df_15m = fetch_ohlcv(symbol, interval="15m", limit=100)
    if df_15m.empty or len(df_15m) < 20:
        price = 0
        return _base_hold(symbol, price, f"No 15m data")

    price = float(df_15m["close"].iloc[-1])
    bos   = detect_bos(df_15m)
    if not bos:
        return _base_hold(symbol, price, "No BOS detected on 15m",
                          {"market": {"price": price, "atr": 0, "atr_ok": True,
                                      "rsi": 50, "rsi_score": 0, "macd": {"histogram": 0},
                                      "macd_score": 0, "trend": {"score": 0, "label": "neutral"},
                                      "volume": {"score": 0}, "change_pct": 0}})

    fib = calculate_fib_zone(bos)
    ob  = identify_order_block(df_15m, bos, fib)
    ma_ok = check_ma_filter(df_15m, bos["direction"])

    sub_scores = {
        "bos":   1 if bos else 0,
        "fib":   1 if (bos and fib["zone_low"] <= price <= fib["zone_high"]) else 0,
        "ob":    1 if (ob and ob["ob_low"] <= price <= ob["ob_high"]) else 0,
        "ma":    1 if ma_ok else 0,
        "entry": 0,
    }

    in_fib = price_in_zone = fib["zone_low"] <= price <= fib["zone_high"]
    in_ob  = ob and ob["ob_low"] <= price <= ob["ob_high"]

    reason = "No BOS detected"
    if bos and not in_fib:
        reason = f"BOS {bos['direction']} — waiting for retracement into ${fib['zone_low']:.5f}–${fib['zone_high']:.5f}"
    elif bos and in_fib and not ob:
        reason = f"BOS + Fib confirmed — no OB overlap found"
    elif bos and in_fib and ob and not in_ob:
        reason = f"OB identified — price not yet inside ${ob['ob_low']:.5f}–${ob['ob_high']:.5f}"
    elif bos and in_fib and ob and in_ob and not ma_ok:
        reason = f"All structure met — MA filter not aligned"
    elif bos and in_fib and ob and in_ob and ma_ok:
        reason = f"All structure conditions met — monitoring for entry candle"

    return _base_hold(symbol, price, reason, {
        "bos": bos, "fib": fib, "ob": ob,
        "sub_scores": sub_scores,
        "market": {
            "price": price, "atr": 0, "atr_ok": True,
            "rsi": 50, "rsi_score": 0,
            "macd": {"histogram": 0}, "macd_score": 0,
            "trend": {"score": 1 if bos["direction"]=="bullish" else -1, "label": bos["direction"]},
            "volume": {"score": 0}, "change_pct": 0,
        },
        "sentiment": {"score": 0, "label": "neutral"},
    })