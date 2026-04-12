"""
WeltBot Signal Engine v4.0
Dual Strategy:
  A) SMC on 5m — BOS + Fib + OB + EMA50 filter
  B) EMA Momentum Scalp — EMA9/21 cross + EMA50 trend
SMC takes priority. Momentum fires when no SMC setup active.
Generates 2-8 trades per day in normal market conditions.
"""

import pandas as pd
import numpy as np
from modules.market_data import fetch_ohlcv, compute_atr


# ─── SWING DETECTION ──────────────────────────────────────────────────────────

def detect_swings(df: pd.DataFrame, lookback: int = 2) -> pd.DataFrame:
    n   = len(df)
    sh  = [False] * n
    sl  = [False] * n
    hi  = df["high"]
    lo  = df["low"]
    for i in range(lookback, n - lookback):
        if all(hi.iloc[i] > hi.iloc[i-j] for j in range(1, lookback+1)) and \
           all(hi.iloc[i] > hi.iloc[i+j] for j in range(1, lookback+1)):
            sh[i] = True
        if all(lo.iloc[i] < lo.iloc[i-j] for j in range(1, lookback+1)) and \
           all(lo.iloc[i] < lo.iloc[i+j] for j in range(1, lookback+1)):
            sl[i] = True
    out = df.copy()
    out["swing_high"] = sh
    out["swing_low"]  = sl
    return out


# ─── BOS DETECTION ────────────────────────────────────────────────────────────

def detect_bos(df: pd.DataFrame) -> dict | None:
    df  = detect_swings(df, lookback=2)
    n   = len(df)
    shi = [i for i in range(n-2) if df["swing_high"].iloc[i]]
    sli = [i for i in range(n-2) if df["swing_low"].iloc[i]]
    if not shi and not sli:
        return None
    lc = float(df["close"].iloc[-1])

    if shi:
        i   = shi[-1]
        shp = float(df["high"].iloc[i])
        if lc > shp:
            slb = [x for x in sli if x < i]
            if slb:
                il  = slb[-1]
                return {
                    "direction":        "bullish",
                    "bos_level":        shp,
                    "impulse_high":     shp,
                    "impulse_low":      float(df["low"].iloc[il]),
                    "impulse_high_idx": i,
                    "impulse_low_idx":  il,
                    "bos_close":        lc,
                }
    if sli:
        i   = sli[-1]
        slp = float(df["low"].iloc[i])
        if lc < slp:
            shb = [x for x in shi if x < i]
            if shb:
                ih  = shb[-1]
                return {
                    "direction":         "bearish",
                    "bos_level":         slp,
                    "impulse_high":      float(df["high"].iloc[ih]),
                    "impulse_low":       slp,
                    "impulse_high_idx":  ih,
                    "impulse_low_idx":   i,
                    "bos_close":         lc,
                }
    return None


# ─── FIBONACCI ────────────────────────────────────────────────────────────────

def calculate_fib_zone(bos: dict) -> dict:
    hi  = bos["impulse_high"]
    lo  = bos["impulse_low"]
    rng = hi - lo
    if rng == 0:
        rng = lo * 0.01
    if bos["direction"] == "bullish":
        zh = round(hi - rng * 0.500, 8)
        zl = round(hi - rng * 0.618, 8)
    else:
        zh = round(lo + rng * 0.618, 8)
        zl = round(lo + rng * 0.500, 8)
    return {"zone_high": zh, "zone_low": zl, "range": round(rng, 8)}


# ─── ORDER BLOCK ──────────────────────────────────────────────────────────────

def identify_order_block(df: pd.DataFrame, bos: dict, fib: dict) -> dict | None:
    start = bos.get("impulse_low_idx") if bos["direction"] == "bullish" \
            else bos.get("impulse_high_idx")
    if start is None:
        return None
    for i in range(int(start), max(0, int(start) - 25) - 1, -1):
        c   = df.iloc[i]
        oh  = float(c["high"])
        ol  = float(c["low"])
        oc  = float(c["close"])
        oo  = float(c["open"])
        if oh >= fib["zone_low"] and ol <= fib["zone_high"]:
            if bos["direction"] == "bullish" and oc < oo:
                return {"ob_high": oh, "ob_low": ol, "direction": "bullish"}
            if bos["direction"] == "bearish" and oc > oo:
                return {"ob_high": oh, "ob_low": ol, "direction": "bearish"}
    return None


# ─── MA FILTER ────────────────────────────────────────────────────────────────

def check_ma_filter(df: pd.DataFrame, direction: str) -> bool:
    close = df["close"]
    e50   = close.ewm(span=50, adjust=False).mean()
    e50n  = float(e50.iloc[-1])
    e50p  = float(e50.iloc[-4]) if len(e50) > 4 else e50n
    price = float(close.iloc[-1])
    if direction == "bullish":
        return e50n > e50p and price > e50n
    return e50n < e50p and price < e50n


# ─── ENTRY CANDLE ─────────────────────────────────────────────────────────────

def check_entry_confirmation(df: pd.DataFrame, direction: str) -> dict:
    if df is None or df.empty or len(df) < 3:
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


# ─── SL/TP ────────────────────────────────────────────────────────────────────

def calculate_sl_tp(entry: float, ob: dict, direction: str, atr: float) -> dict:
    buf  = max(atr * 0.3, entry * 0.002)
    if direction == "bullish":
        sl   = round(ob["ob_low"] - buf, 8)
        risk = entry - sl
        if risk <= 0:
            risk = entry * 0.015
            sl   = round(entry - risk, 8)
        tp = round(entry + risk * 2.0, 8)
    else:
        sl   = round(ob["ob_high"] + buf, 8)
        risk = sl - entry
        if risk <= 0:
            risk = entry * 0.015
            sl   = round(entry + risk, 8)
        tp = round(entry - risk * 2.0, 8)
    return {
        "stop_loss":   sl,
        "take_profit": tp,
        "risk_dist":   round(abs(risk), 8),
        "risk_pct":    round(abs(risk) / entry * 100, 3),
    }


# ─── STRATEGY A: SMC 5M ───────────────────────────────────────────────────────

def scan_for_bos(symbol: str) -> dict | None:
    """L1 scan — detects BOS on 5m and 15m, returns setup if valid."""
    for tf in ["5m", "15m"]:
        df = fetch_ohlcv(symbol, interval=tf, limit=100)
        if df is None or df.empty or len(df) < 20:
            continue
        bos = detect_bos(df)
        if not bos:
            continue
        fib = calculate_fib_zone(bos)
        ob  = identify_order_block(df, bos, fib)
        if not ob:
            continue
        ma_ok = check_ma_filter(df, bos["direction"])
        if not ma_ok:
            continue
        price = float(df["close"].iloc[-1])
        print(f"[SMC] {symbol} {tf} {bos['direction'].upper()} BOS found — price={price}")
        return {
            "symbol":    symbol,
            "direction": bos["direction"],
            "timeframe": tf,
            "bos":       bos,
            "fib":       fib,
            "ob":        ob,
            "candle_age": 0,
            "strategy":  "SMC",
        }
    return None


def check_entry_for_setup(setup: dict) -> dict | None:
    """L2 check — verifies price in zone and entry candle exists."""
    symbol    = setup["symbol"]
    bos       = setup["bos"]
    fib       = setup["fib"]
    ob        = setup["ob"]
    direction = setup["direction"]
    tf        = setup.get("timeframe", "5m")

    df_1m  = fetch_ohlcv(symbol, interval="1m", limit=10)
    df_5m  = fetch_ohlcv(symbol, interval="5m", limit=10)
    df_ref = fetch_ohlcv(symbol, interval=tf,   limit=100)

    if df_1m is None or df_1m.empty:
        return None

    price = float(df_1m["close"].iloc[-1])

    in_fib = fib["zone_low"] <= price <= fib["zone_high"]
    in_ob  = ob["ob_low"]    <= price <= ob["ob_high"]

    if not (in_fib and in_ob):
        return None

    if direction == "bullish" and price < bos.get("impulse_low", 0):
        return None
    if direction == "bearish" and price > bos.get("impulse_high", float("inf")):
        return None

    entry_tf   = "1m"
    entry_conf = check_entry_confirmation(df_1m, direction)
    if not entry_conf["confirmed"]:
        entry_tf   = "5m"
        entry_conf = check_entry_confirmation(df_5m, direction)

    if not entry_conf["confirmed"]:
        return None

    atr = 0.0
    if df_ref is not None and not df_ref.empty and len(df_ref) >= 15:
        atr = compute_atr(df_ref)
    if atr == 0:
        atr = price * 0.015

    sl_tp  = calculate_sl_tp(price, ob, direction, atr)
    signal = "BUY" if direction == "bullish" else "SELL"
    print(f"[SMC ENTRY] {symbol} {signal} | {entry_conf['type']} on {entry_tf} @ {price}")

    return _build_signal(symbol, signal, price, atr, bos, fib, ob,
                         entry_conf["type"], entry_tf, sl_tp, "SMC")


# ─── STRATEGY B: EMA MOMENTUM SCALP ──────────────────────────────────────────

def ema_momentum_scan(symbol: str) -> dict | None:
    """
    Fires when EMA9 crosses EMA21 with EMA50 as trend filter.
    Entry on cross confirmation candle.
    Works on 5m for multiple signals per day.
    """
    df = fetch_ohlcv(symbol, interval="5m", limit=60)
    if df is None or df.empty or len(df) < 30:
        return None

    close  = df["close"]
    price  = float(close.iloc[-1])
    ema9   = close.ewm(span=9,  adjust=False).mean()
    ema21  = close.ewm(span=21, adjust=False).mean()
    ema50  = close.ewm(span=50, adjust=False).mean()

    e9n, e9p   = float(ema9.iloc[-1]),  float(ema9.iloc[-2])
    e21n, e21p = float(ema21.iloc[-1]), float(ema21.iloc[-2])
    e50n       = float(ema50.iloc[-1])
    e50p       = float(ema50.iloc[-4]) if len(ema50) > 4 else e50n

    bull_cross = e9p <= e21p and e9n > e21n
    bear_cross = e9p >= e21p and e9n < e21n

    if not bull_cross and not bear_cross:
        return None

    direction = "bullish" if bull_cross else "bearish"

    if direction == "bullish":
        if not (e50n > e50p and price > e50n):
            return None
    else:
        if not (e50n < e50p and price < e50n):
            return None

    atr = compute_atr(df)
    if atr == 0:
        atr = price * 0.015

    buf = atr * 0.5
    if direction == "bullish":
        sl  = round(price - atr * 1.5, 8)
        tp  = round(price + atr * 3.0, 8)
    else:
        sl  = round(price + atr * 1.5, 8)
        tp  = round(price - atr * 3.0, 8)

    ob_fake = {
        "ob_high": price + buf,
        "ob_low":  price - buf,
        "direction": direction,
    }
    sl_tp = {"stop_loss": sl, "take_profit": tp,
             "risk_dist": abs(price - sl), "risk_pct": abs(price - sl) / price * 100}
    signal = "BUY" if direction == "bullish" else "SELL"
    bos_fake = {
        "direction":    direction,
        "bos_level":    price,
        "impulse_high": price + atr * 2,
        "impulse_low":  price - atr * 2,
    }
    fib_fake = {"zone_high": price + buf, "zone_low": price - buf, "range": atr * 2}
    print(f"[EMA CROSS] {symbol} {signal} EMA9/21 cross on 5m @ {price}")
    return _build_signal(symbol, signal, price, atr, bos_fake, fib_fake, ob_fake,
                         "ema_cross", "5m", sl_tp, "EMA_MOMENTUM")


# ─── STRATEGY C: RSI REVERSAL ─────────────────────────────────────────────────

def rsi_reversal_scan(symbol: str) -> dict | None:
    """
    Catches oversold/overbought reversals.
    RSI < 28 = buy. RSI > 72 = sell. On 5m with EMA50 agreement.
    """
    df = fetch_ohlcv(symbol, interval="5m", limit=30)
    if df is None or df.empty or len(df) < 20:
        return None

    close = df["close"]
    price = float(close.iloc[-1])
    delta = close.diff()
    gain  = delta.clip(lower=0).rolling(14).mean()
    loss  = (-delta.clip(upper=0)).rolling(14).mean()
    rs    = gain / loss.replace(0, np.nan)
    rsi   = float((100 - 100 / (1 + rs)).iloc[-1])

    if np.isnan(rsi):
        return None

    ema50     = float(close.ewm(span=50, adjust=False).mean().iloc[-1])
    ema50_prev= float(close.ewm(span=50, adjust=False).mean().iloc[-4]) \
                if len(close) > 4 else ema50

    if rsi < 28 and price > ema50 * 0.99:
        direction = "bullish"
        signal    = "BUY"
    elif rsi > 72 and price < ema50 * 1.01:
        direction = "bearish"
        signal    = "SELL"
    else:
        return None

    entry_conf = check_entry_confirmation(df, direction)
    if not entry_conf["confirmed"]:
        return None

    atr = compute_atr(df)
    if atr == 0:
        atr = price * 0.015

    if direction == "bullish":
        sl = round(price - atr * 1.5, 8)
        tp = round(price + atr * 2.5, 8)
    else:
        sl = round(price + atr * 1.5, 8)
        tp = round(price - atr * 2.5, 8)

    buf      = atr * 0.3
    ob_fake  = {"ob_high": price + buf, "ob_low": price - buf, "direction": direction}
    sl_tp    = {"stop_loss": sl, "take_profit": tp,
                "risk_dist": abs(price - sl), "risk_pct": abs(price - sl) / price * 100}
    bos_fake = {"direction": direction, "bos_level": price,
                "impulse_high": price + atr*2, "impulse_low": price - atr*2}
    fib_fake = {"zone_high": price + buf, "zone_low": price - buf, "range": atr*2}

    print(f"[RSI REVERSAL] {symbol} {signal} RSI={rsi:.1f} on 5m @ {price}")
    return _build_signal(symbol, signal, price, atr, bos_fake, fib_fake, ob_fake,
                         entry_conf["type"], "5m", sl_tp, "RSI_REVERSAL")


# ─── SHARED SIGNAL BUILDER ────────────────────────────────────────────────────

def _build_signal(symbol, signal, price, atr, bos, fib, ob,
                  entry_type, entry_tf, sl_tp, strategy) -> dict:
    direction = "bullish" if signal == "BUY" else "bearish"
    return {
        "symbol":     symbol,
        "signal":     signal,
        "confidence": 85.0,
        "raw_score":  0.85 if signal == "BUY" else -0.85,
        "strategy":   strategy,
        "reasoning":  [
            f"Strategy: {strategy}",
            f"Entry: {entry_type} on {entry_tf}",
            f"SL: {sl_tp['stop_loss']:.6f} | TP: {sl_tp['take_profit']:.6f}",
        ],
        "bos":        bos,
        "fib":        fib,
        "ob":         ob,
        "entry_tf":   entry_tf,
        "entry_type": entry_type,
        "sl_tp":      sl_tp,
        "sub_scores": {"bos": 1, "fib": 1, "ob": 1, "ma": 1, "entry": 1},
        "market": {
            "price": price, "atr": atr, "atr_ok": True,
            "rsi": 50, "rsi_score": 0,
            "macd": {"histogram": 0}, "macd_score": 0,
            "trend": {"score": 1.0 if direction == "bullish" else -1.0,
                      "label": direction},
            "volume": {"score": 0}, "change_pct": 0,
        },
        "sentiment": {"score": 0, "label": "neutral"},
    }


# ─── COMPUTE SIGNAL (cache/dashboard) ────────────────────────────────────────

def compute_signal(symbol: str, learned_bias: float = 0.0) -> dict:
    df = fetch_ohlcv(symbol, interval="5m", limit=100)
    price = 0.0
    if df is not None and not df.empty:
        price = float(df["close"].iloc[-1])

    def hold(reason, extra=None):
        base = {
            "symbol": symbol, "signal": "HOLD", "reason": reason,
            "confidence": 0, "raw_score": 0, "sub_scores": {},
            "market": {"price": price, "atr": 0, "atr_ok": True,
                       "rsi": 50, "rsi_score": 0, "macd": {"histogram": 0},
                       "macd_score": 0, "trend": {"score": 0, "label": "neutral"},
                       "volume": {"score": 0}, "change_pct": 0},
            "sentiment": {"score": 0, "label": "neutral"},
        }
        if extra:
            base.update(extra)
        return base

    if df is None or df.empty or len(df) < 20:
        return hold("No 5m data")

    bos  = detect_bos(df)
    sub  = {"bos": 0, "fib": 0, "ob": 0, "ma": 0, "entry": 0}
    reason = "No BOS on 5m"

    if bos:
        sub["bos"] = 1
        fib  = calculate_fib_zone(bos)
        ob   = identify_order_block(df, bos, fib)
        ma   = check_ma_filter(df, bos["direction"])
        in_fib = fib["zone_low"] <= price <= fib["zone_high"]
        in_ob  = ob and ob["ob_low"] <= price <= ob["ob_high"] if ob else False

        if in_fib:
            sub["fib"] = 1
        if in_ob:
            sub["ob"] = 1
        if ma:
            sub["ma"] = 1

        if not in_fib:
            reason = f"BOS {bos['direction']} — price not in fib zone yet"
        elif not ob:
            reason = "BOS + Fib — no OB found"
        elif not in_ob:
            reason = f"BOS + Fib + OB — price not in OB yet"
        elif not ma:
            reason = "Structure met — MA not aligned"
        else:
            reason = "All structure met — monitoring for entry"

        return hold(reason, {
            "bos": bos, "fib": fib, "ob": ob,
            "sub_scores": sub,
            "market": {"price": price, "atr": 0, "atr_ok": True,
                       "rsi": 50, "rsi_score": 0, "macd": {"histogram": 0},
                       "macd_score": 0,
                       "trend": {"score": 1 if bos["direction"]=="bullish" else -1,
                                 "label": bos["direction"]},
                       "volume": {"score": 0}, "change_pct": 0},
        })

    return hold(reason, {"sub_scores": sub})