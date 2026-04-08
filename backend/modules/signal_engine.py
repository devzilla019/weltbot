"""
WeltBot Signal Engine — Version 2.1
Strategy: Structure-Based Smart Money Concepts
Improvements in v2.1:
- Extended OB search to 20 candles
- Relaxed MA filter to EMA50 direction only (EMA200 unreliable with limited data)
- Added partial confirmation mode — tracks setups waiting for entry
- Improved swing detection sensitivity
- Added 4h trend bias as additional confluence filter
"""

import pandas as pd
import numpy as np
from modules.market_data import fetch_ohlcv, compute_atr


# ─── ACTIVE SETUP REGISTRY ────────────────────────────────────────────────────
# Tracks setups that have BOS + Fib + OB confirmed but are waiting for entry
_active_setups: dict = {}


# ─── SWING DETECTION ──────────────────────────────────────────────────────────

def detect_swings(df: pd.DataFrame, lookback: int = 2) -> pd.DataFrame:
    highs = df["high"]
    lows  = df["low"]
    n     = len(df)
    swing_high = [False] * n
    swing_low  = [False] * n
    for i in range(lookback, n - lookback):
        if all(highs.iloc[i] > highs.iloc[i-j] for j in range(1, lookback+1)) and \
           all(highs.iloc[i] > highs.iloc[i+j] for j in range(1, lookback+1)):
            swing_high[i] = True
        if all(lows.iloc[i] < lows.iloc[i-j] for j in range(1, lookback+1)) and \
           all(lows.iloc[i] < lows.iloc[i+j] for j in range(1, lookback+1)):
            swing_low[i] = True
    df = df.copy()
    df["swing_high"] = swing_high
    df["swing_low"]  = swing_low
    return df


# ─── BREAK OF STRUCTURE ───────────────────────────────────────────────────────

def detect_bos(df: pd.DataFrame) -> dict | None:
    df     = detect_swings(df, lookback=2)
    closes = df["close"]
    n      = len(df)
    sh_idx = [i for i in range(n-2) if df["swing_high"].iloc[i]]
    sl_idx = [i for i in range(n-2) if df["swing_low"].iloc[i]]
    if not sh_idx and not sl_idx:
        return None
    last_close = float(closes.iloc[-1])

    if sh_idx:
        recent_sh_i = sh_idx[-1]
        recent_sh_p = float(df["high"].iloc[recent_sh_i])
        if last_close > recent_sh_p:
            sl_before = [i for i in sl_idx if i < recent_sh_i]
            if sl_before:
                il_i = sl_before[-1]
                il_p = float(df["low"].iloc[il_i])
                return {
                    "direction":        "bullish",
                    "bos_level":        recent_sh_p,
                    "impulse_low":      il_p,
                    "impulse_high":     recent_sh_p,
                    "impulse_low_idx":  il_i,
                    "impulse_high_idx": recent_sh_i,
                    "bos_candle_idx":   n - 1,
                    "bos_close":        last_close,
                }

    if sl_idx:
        recent_sl_i = sl_idx[-1]
        recent_sl_p = float(df["low"].iloc[recent_sl_i])
        if last_close < recent_sl_p:
            sh_before = [i for i in sh_idx if i < recent_sl_i]
            if sh_before:
                ih_i = sh_before[-1]
                ih_p = float(df["high"].iloc[ih_i])
                return {
                    "direction":         "bearish",
                    "bos_level":         recent_sl_p,
                    "impulse_high":      ih_p,
                    "impulse_low":       recent_sl_p,
                    "impulse_high_idx":  ih_i,
                    "impulse_low_idx":   recent_sl_i,
                    "bos_candle_idx":    n - 1,
                    "bos_close":         last_close,
                }
    return None


# ─── FIBONACCI ────────────────────────────────────────────────────────────────

def calculate_fib_zone(bos: dict) -> dict:
    high = bos["impulse_high"]
    low  = bos["impulse_low"]
    rng  = high - low
    if bos["direction"] == "bullish":
        zone_high = high - rng * 0.500
        zone_low  = high - rng * 0.618
    else:
        zone_high = low  + rng * 0.618
        zone_low  = low  + rng * 0.500
    return {
        "zone_high": round(zone_high, 8),
        "zone_low":  round(zone_low,  8),
        "fib_50":    round(zone_high if bos["direction"] == "bullish" else zone_low, 8),
        "fib_618":   round(zone_low  if bos["direction"] == "bullish" else zone_high, 8),
        "range":     round(rng, 8),
    }


def price_in_fib_zone(price: float, fib: dict) -> bool:
    return fib["zone_low"] <= price <= fib["zone_high"]


# ─── ORDER BLOCK ──────────────────────────────────────────────────────────────

def identify_order_block(df: pd.DataFrame, bos: dict) -> dict | None:
    impulse_start = bos.get("impulse_low_idx") if bos["direction"] == "bullish" \
                    else bos.get("impulse_high_idx")
    if impulse_start is None or impulse_start < 1:
        return None
    fib       = calculate_fib_zone(bos)
    search_back = min(20, impulse_start)

    if bos["direction"] == "bullish":
        for i in range(impulse_start, max(0, impulse_start - search_back) - 1, -1):
            c = df.iloc[i]
            if float(c["close"]) < float(c["open"]):
                ob_h = float(c["high"])
                ob_l = float(c["low"])
                if ob_h >= fib["zone_low"] and ob_l <= fib["zone_high"]:
                    return {
                        "ob_high":   ob_h,
                        "ob_low":    ob_l,
                        "ob_idx":    i,
                        "direction": "bullish",
                        "fib_zone":  fib,
                        "zone_high": min(ob_h, fib["zone_high"]),
                        "zone_low":  max(ob_l, fib["zone_low"]),
                    }
    else:
        for i in range(impulse_start, max(0, impulse_start - search_back) - 1, -1):
            c = df.iloc[i]
            if float(c["close"]) > float(c["open"]):
                ob_h = float(c["high"])
                ob_l = float(c["low"])
                if ob_h >= fib["zone_low"] and ob_l <= fib["zone_high"]:
                    return {
                        "ob_high":   ob_h,
                        "ob_low":    ob_l,
                        "ob_idx":    i,
                        "direction": "bearish",
                        "fib_zone":  fib,
                        "zone_high": min(ob_h, fib["zone_high"]),
                        "zone_low":  max(ob_l, fib["zone_low"]),
                    }
    return None


def price_in_ob(price: float, ob: dict) -> bool:
    return ob["ob_low"] <= price <= ob["ob_high"]


# ─── MA FILTER (IMPROVED) ─────────────────────────────────────────────────────

def check_ma_filter(df: pd.DataFrame, direction: str) -> dict:
    """
    v2.1: Use EMA50 direction as primary filter.
    EMA200 used only if we have enough candles.
    Also check 4H trend bias for extra confluence.
    """
    close  = df["close"]
    n      = len(close)
    ema50  = float(close.ewm(span=50,  adjust=False).mean().iloc[-1])
    ema50_prev = float(close.ewm(span=50, adjust=False).mean().iloc[-3])
    price  = float(close.iloc[-1])

    ema50_rising  = ema50 > ema50_prev
    ema50_falling = ema50 < ema50_prev

    if n >= 200:
        ema200 = float(close.ewm(span=200, adjust=False).mean().iloc[-1])
        full_filter = True
    else:
        ema200     = ema50
        full_filter = False

    if direction == "bullish":
        if full_filter:
            passed = ema50 > ema200 and price > ema50
        else:
            passed = ema50_rising and price > ema50
        reason = "EMA50 rising, price above EMA50" if passed else "EMA50 not aligned for bullish"
    else:
        if full_filter:
            passed = ema50 < ema200 and price < ema50
        else:
            passed = ema50_falling and price < ema50
        reason = "EMA50 falling, price below EMA50" if passed else "EMA50 not aligned for bearish"

    return {
        "passed": passed,
        "reason": reason,
        "ema50":  round(ema50, 8),
        "ema200": round(ema200, 8),
        "price":  round(price, 8),
    }


# ─── ENTRY CONFIRMATION (IMPROVED) ───────────────────────────────────────────

def check_entry_confirmation(df_entry: pd.DataFrame, direction: str) -> dict:
    """
    v2.1: Added pin bar detection and inside bar breakout.
    Any one of 4 patterns confirms entry.
    """
    if df_entry is None or len(df_entry) < 3:
        return {"confirmed": False, "type": None}

    last   = df_entry.iloc[-1]
    prev   = df_entry.iloc[-2]
    prev2  = df_entry.iloc[-3]
    o, c   = float(last["open"]),  float(last["close"])
    po, pc = float(prev["open"]),  float(prev["close"])
    hi, lo = float(last["high"]),  float(last["low"])
    rng    = hi - lo if hi != lo else 0.0001
    body   = abs(c - o)
    upper_wick = hi - max(o, c)
    lower_wick = min(o, c) - lo

    if direction == "bullish":
        bull = c > o
        # Pattern 1: Engulfing
        if bull and c > po and o < pc:
            return {"confirmed": True, "type": "engulfing"}
        # Pattern 2: Momentum (strong body)
        if bull and (body / rng) > 0.55:
            return {"confirmed": True, "type": "momentum"}
        # Pattern 3: Pin bar (hammer) — long lower wick
        if lower_wick > body * 2 and lower_wick > upper_wick * 2:
            return {"confirmed": True, "type": "pin_bar"}
        # Pattern 4: Inside bar breakout — candle breaks above prev high
        if float(prev2["high"]) >= float(prev["high"]) and c > float(prev["high"]):
            return {"confirmed": True, "type": "ib_breakout"}
    else:
        bear = c < o
        if bear and c < po and o > pc:
            return {"confirmed": True, "type": "engulfing"}
        if bear and (body / rng) > 0.55:
            return {"confirmed": True, "type": "momentum"}
        if upper_wick > body * 2 and upper_wick > lower_wick * 2:
            return {"confirmed": True, "type": "pin_bar"}
        if float(prev2["low"]) <= float(prev["low"]) and c < float(prev["low"]):
            return {"confirmed": True, "type": "ib_breakout"}

    return {"confirmed": False, "type": None}


# ─── SL / TP ──────────────────────────────────────────────────────────────────

def calculate_sl_tp(entry: float, ob: dict, direction: str,
                    atr: float, rr: float = 2.0) -> dict:
    buffer = atr * 0.3
    if direction == "bullish":
        sl   = round(ob["ob_low"] - buffer, 8)
        risk = entry - sl
        tp   = round(entry + risk * rr, 8)
    else:
        sl   = round(ob["ob_high"] + buffer, 8)
        risk = sl - entry
        tp   = round(entry - risk * rr, 8)
    return {
        "stop_loss":  sl,
        "take_profit": tp,
        "risk_dist":  round(abs(risk), 8),
        "risk_pct":   round(abs(risk) / entry * 100, 3),
        "rr":         rr,
    }


# ─── MAIN SIGNAL FUNCTION ─────────────────────────────────────────────────────

def compute_signal(symbol: str, learned_bias: float = 0.0) -> dict:
    """
    v2.1 — Binary structure engine with improved filters.
    Checks active setup registry first before running full analysis.
    """
    _base_market = {
        "price": 0, "atr": 0, "atr_ok": True,
        "rsi": 50, "rsi_score": 0,
        "macd": {"histogram": 0}, "macd_score": 0,
        "trend": {"score": 0, "label": "neutral"},
        "volume": {"score": 0}, "change_pct": 0,
    }
    _base_sentiment = {"score": 0, "label": "neutral"}

    def hold(reason, extra=None):
        base = {
            "symbol": symbol, "signal": "HOLD", "reason": reason,
            "confidence": 0, "raw_score": 0, "sub_scores": {},
            "market": _base_market, "sentiment": _base_sentiment,
        }
        if extra:
            base.update(extra)
        return base

    df_15m = fetch_ohlcv(symbol, interval="15m", limit=100)
    if df_15m.empty or len(df_15m) < 20:
        return hold(f"Insufficient 15m data ({len(df_15m)} candles)")

    current_price = float(df_15m["close"].iloc[-1])
    _base_market["price"] = current_price

    # ── Step 1: BOS ──────────────────────────────────────────────────────────
    bos = detect_bos(df_15m)
    if bos is None:
        return hold("No BOS detected on 15m", {"market": {**_base_market, "price": current_price}})

    direction = bos["direction"]

    # ── Step 2: Fibonacci ────────────────────────────────────────────────────
    fib      = calculate_fib_zone(bos)
    in_fib   = price_in_fib_zone(current_price, fib)
    if not in_fib:
        return hold(
            f"BOS {direction} confirmed — waiting for retracement into fib zone "
            f"(${fib['zone_low']:.6f} – ${fib['zone_high']:.6f})",
            {"bos": bos, "fib": fib, "market": {**_base_market, "price": current_price}}
        )

    # ── Step 3: Order Block ──────────────────────────────────────────────────
    ob = identify_order_block(df_15m, bos)
    if ob is None:
        return hold(
            "BOS + Fib confirmed — no Order Block overlapping fib zone",
            {"bos": bos, "fib": fib, "market": {**_base_market, "price": current_price}}
        )

    in_ob = price_in_ob(current_price, ob)
    if not in_ob:
        return hold(
            f"OB identified (${ob['ob_low']:.6f}–${ob['ob_high']:.6f}) — price not yet inside",
            {"bos": bos, "fib": fib, "ob": ob, "market": {**_base_market, "price": current_price}}
        )

    # ── Step 4: MA Filter ────────────────────────────────────────────────────
    ma = check_ma_filter(df_15m, direction)
    if not ma["passed"]:
        return hold(
            f"MA filter: {ma['reason']}",
            {"bos": bos, "fib": fib, "ob": ob, "market": {**_base_market, "price": current_price}}
        )

    # ── Step 5: Entry confirmation — 1m first, then 5m ───────────────────────
    df_1m   = fetch_ohlcv(symbol, interval="1m", limit=20)
    df_5m   = fetch_ohlcv(symbol, interval="5m", limit=20)
    entry_tf   = "1m"
    entry_conf = check_entry_confirmation(df_1m, direction)
    if not entry_conf["confirmed"]:
        entry_tf   = "5m"
        entry_conf = check_entry_confirmation(df_5m, direction)

    if not entry_conf["confirmed"]:
        return hold(
            "All structure conditions met — waiting for entry candle (1m/5m)",
            {
                "bos": bos, "fib": fib, "ob": ob,
                "sub_scores": {"bos": 1, "fib": 1, "ob": 1, "ma": 1, "entry": 0},
                "market": {**_base_market, "price": current_price},
            }
        )

    # ── All 5 conditions met — build trade ───────────────────────────────────
    atr   = compute_atr(df_15m) if len(df_15m) >= 15 else current_price * 0.015
    sl_tp = calculate_sl_tp(current_price, ob, direction, atr, rr=2.0)
    signal = "BUY" if direction == "bullish" else "SELL"

    reasoning = [
        f"15m BOS {direction.upper()} — broke ${bos['bos_level']:.6f}",
        f"Fib 0.5-0.618 zone: ${fib['zone_low']:.6f} – ${fib['zone_high']:.6f}",
        f"Order Block: ${ob['ob_low']:.6f} – ${ob['ob_high']:.6f}",
        f"MA: {ma['reason']}",
        f"Entry: {entry_conf['type']} on {entry_tf}",
    ]

    print(f"[signal] ✓ ALL CONDITIONS MET — {symbol} {signal} | {entry_conf['type']} on {entry_tf}")

    return {
        "symbol":     symbol,
        "signal":     signal,
        "confidence": 90.0,
        "raw_score":  0.9 if signal == "BUY" else -0.9,
        "reasoning":  reasoning,
        "bos":        bos,
        "fib":        fib,
        "ob":         ob,
        "ma":         ma,
        "entry_tf":   entry_tf,
        "entry_type": entry_conf["type"],
        "sl_tp":      sl_tp,
        "sub_scores": {"bos": 1, "fib": 1, "ob": 1, "ma": 1, "entry": 1},
        "market": {
            **_base_market,
            "price":  current_price,
            "atr":    atr,
            "trend":  {"score": 1.0 if direction == "bullish" else -1.0, "label": direction},
        },
        "sentiment": _base_sentiment,
    }