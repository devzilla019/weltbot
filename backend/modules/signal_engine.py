"""
WeltBot Signal Engine v5.0 — Full SMC with Directional Bias
Strategy:
  1. Higher Timeframe Bias (4H + 1H) — direction filter
  2. Structure (BOS on 15m/5m)
  3. Fibonacci 0.5-0.618
  4. Order Block confluence
  5. Fair Value Gap detection
  6. Liquidity sweep detection
  7. Supply/Demand zones
  8. Entry confirmation (1m/5m)
  9. News blackout respect

This engine is designed to trade WITH institutional flow, not against it.
"""

import pandas as pd
import numpy as np
from modules.market_data import fetch_ohlcv, compute_atr


# ─── SWING DETECTION ──────────────────────────────────────────────────────────

def detect_swings(df: pd.DataFrame, lookback: int = 3) -> pd.DataFrame:
    n  = len(df)
    sh = [False] * n
    sl = [False] * n
    hi = df["high"]
    lo = df["low"]
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


# ─── DIRECTIONAL BIAS (HTF) ───────────────────────────────────────────────────

def get_directional_bias(symbol: str) -> dict:
    """
    Checks 4H and 1H structure to determine dominant direction.
    Returns: bullish / bearish / neutral
    Weight: 4H is primary, 1H is secondary confirmation.
    """
    results = {}
    for tf, weight in [("4h", 2), ("1h", 1)]:
        df = fetch_ohlcv(symbol, interval=tf, limit=100)
        if df is None or df.empty or len(df) < 20:
            results[tf] = "neutral"
            continue

        df    = detect_swings(df, lookback=3)
        close = df["close"]
        n     = len(df)
        shi   = [i for i in range(n-2) if df["swing_high"].iloc[i]]
        sli   = [i for i in range(n-2) if df["swing_low"].iloc[i]]
        last  = float(close.iloc[-1])

        ema50 = float(close.ewm(span=50, adjust=False).mean().iloc[-1])

        # Higher highs and higher lows = bullish
        if len(shi) >= 2 and len(sli) >= 2:
            hh = df["high"].iloc[shi[-1]] > df["high"].iloc[shi[-2]]
            hl = df["low"].iloc[sli[-1]]  > df["low"].iloc[sli[-2]]
            lh = df["high"].iloc[shi[-1]] < df["high"].iloc[shi[-2]]
            ll = df["low"].iloc[sli[-1]]  < df["low"].iloc[sli[-2]]

            if hh and hl and last > ema50:
                results[tf] = "bullish"
            elif lh and ll and last < ema50:
                results[tf] = "bearish"
            else:
                results[tf] = "neutral"
        else:
            results[tf] = "neutral"

    # Combine with weighting
    bias_score = 0
    if results.get("4h") == "bullish":  bias_score += 2
    if results.get("4h") == "bearish":  bias_score -= 2
    if results.get("1h") == "bullish":  bias_score += 1
    if results.get("1h") == "bearish":  bias_score -= 1

    if bias_score >= 2:
        final = "bullish"
    elif bias_score <= -2:
        final = "bearish"
    else:
        final = "neutral"

    return {
        "bias":      final,
        "4h":        results.get("4h", "neutral"),
        "1h":        results.get("1h", "neutral"),
        "score":     bias_score,
    }


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
                il = slb[-1]
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
                ih = shb[-1]
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
    search = min(25, int(start))
    for i in range(int(start), max(0, int(start) - search) - 1, -1):
        c  = df.iloc[i]
        oh = float(c["high"])
        ol = float(c["low"])
        oc = float(c["close"])
        oo = float(c["open"])
        overlap = oh >= fib["zone_low"] and ol <= fib["zone_high"]
        if not overlap:
            continue
        if bos["direction"] == "bullish" and oc < oo:
            return {"ob_high": oh, "ob_low": ol, "direction": "bullish"}
        if bos["direction"] == "bearish" and oc > oo:
            return {"ob_high": oh, "ob_low": ol, "direction": "bearish"}
    return None


# ─── FAIR VALUE GAP (FVG) ─────────────────────────────────────────────────────

def detect_fvg(df: pd.DataFrame, direction: str) -> dict | None:
    """
    FVG = imbalance between candle[i-1] high and candle[i+1] low (bullish)
    or candle[i-1] low and candle[i+1] high (bearish)
    Indicates price moved too fast — will return to fill the gap.
    """
    n = len(df)
    fvgs = []
    for i in range(1, n - 1):
        if direction == "bullish":
            gap_low  = float(df["high"].iloc[i-1])
            gap_high = float(df["low"].iloc[i+1])
            if gap_high > gap_low:
                fvgs.append({"fvg_low": gap_low, "fvg_high": gap_high, "idx": i})
        else:
            gap_high = float(df["low"].iloc[i-1])
            gap_low  = float(df["high"].iloc[i+1])
            if gap_low < gap_high:
                fvgs.append({"fvg_low": gap_low, "fvg_high": gap_high, "idx": i})

    if not fvgs:
        return None
    # Return most recent FVG
    return fvgs[-1]


# ─── LIQUIDITY SWEEP ──────────────────────────────────────────────────────────

def detect_liquidity_sweep(df: pd.DataFrame, direction: str) -> bool:
    """
    Detects if price recently swept liquidity (equal highs/lows).
    A sweep followed by a reversal = high probability setup.
    """
    if len(df) < 10:
        return False
    recent = df.tail(10)
    if direction == "bullish":
        lows = recent["low"].values
        min_low  = min(lows[:-2])
        last_low = lows[-1]
        prev_low = lows[-2]
        swept = prev_low < min_low and last_low > prev_low
        return swept
    else:
        highs    = recent["high"].values
        max_high = max(highs[:-2])
        last_hi  = highs[-1]
        prev_hi  = highs[-2]
        swept = prev_hi > max_high and last_hi < prev_hi
        return swept


# ─── SUPPLY & DEMAND ZONES ────────────────────────────────────────────────────

def identify_supply_demand(df: pd.DataFrame, direction: str) -> dict | None:
    """
    Supply zone = area where price previously reversed bearishly (selling pressure)
    Demand zone = area where price previously reversed bullishly (buying pressure)
    Identified by strong impulse candles (body > 60% of range)
    """
    n = len(df)
    zones = []
    for i in range(2, n - 2):
        c    = df.iloc[i]
        body = abs(float(c["close"]) - float(c["open"]))
        rng  = float(c["high"]) - float(c["low"])
        if rng == 0:
            continue
        if body / rng > 0.65:
            if direction == "bullish" and float(c["close"]) > float(c["open"]):
                zones.append({
                    "zone_high": float(c["high"]),
                    "zone_low":  float(c["low"]),
                    "type": "demand",
                })
            elif direction == "bearish" and float(c["close"]) < float(c["open"]):
                zones.append({
                    "zone_high": float(c["high"]),
                    "zone_low":  float(c["low"]),
                    "type": "supply",
                })
    return zones[-1] if zones else None


# ─── EMA FILTER ───────────────────────────────────────────────────────────────

def check_ma_filter(df: pd.DataFrame, direction: str) -> bool:
    close  = df["close"]
    n      = len(close)
    ema50  = close.ewm(span=50, adjust=False).mean()
    e50n   = float(ema50.iloc[-1])
    e50p   = float(ema50.iloc[-4]) if n > 4 else e50n
    price  = float(close.iloc[-1])
    if n >= 200:
        ema200 = float(close.ewm(span=200, adjust=False).mean().iloc[-1])
        if direction == "bullish":
            return e50n > ema200 and price > e50n
        return e50n < ema200 and price < e50n
    else:
        if direction == "bullish":
            return e50n > e50p and price > e50n
        return e50n < e50p and price < e50n


# ─── ENTRY CONFIRMATION ───────────────────────────────────────────────────────

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


# ─── CONFIDENCE SCORER ────────────────────────────────────────────────────────

def calculate_confidence(
    bias: dict,
    direction: str,
    has_fvg: bool,
    has_liquidity_sweep: bool,
    has_sd_zone: bool,
    entry_type: str,
    htf_aligned: bool,
) -> float:
    """
    Builds confidence score from 85 base up to 99.
    Each confluence adds points. Used for leverage tier selection.
    """
    score = 85.0

    # HTF bias alignment is the biggest factor
    if htf_aligned:
        if bias.get("4h") == direction and bias.get("1h") == direction:
            score += 10.0   # Both 4H and 1H agree = very high conviction
        elif bias.get("4h") == direction:
            score += 6.0    # 4H agrees = high conviction
        elif bias.get("1h") == direction:
            score += 3.0    # Only 1H agrees = moderate

    # Additional confluences
    if has_fvg:             score += 2.0
    if has_liquidity_sweep: score += 3.0  # Liquidity sweep = smart money confirmed
    if has_sd_zone:         score += 2.0
    if entry_type == "engulfing":   score += 1.0
    if entry_type == "momentum":    score += 0.5

    return min(round(score, 1), 99.0)


# ─── SL/TP ────────────────────────────────────────────────────────────────────

def calculate_sl_tp(entry: float, ob: dict, direction: str,
                    atr: float, confidence: float) -> dict:
    buf  = atr * 0.3
    # Higher confidence = tighter stop, bigger leverage does the work
    if confidence >= 95:
        rr = 3.0   # 1:3 for extreme conviction
    else:
        rr = 2.0   # 1:2 standard

    if direction == "bullish":
        sl   = round(ob["ob_low"] - buf, 8)
        risk = entry - sl
        if risk <= 0:
            risk = entry * 0.015
            sl   = round(entry - risk, 8)
        tp = round(entry + risk * rr, 8)
    else:
        sl   = round(ob["ob_high"] + buf, 8)
        risk = sl - entry
        if risk <= 0:
            risk = entry * 0.015
            sl   = round(entry + risk, 8)
        tp = round(entry - risk * rr, 8)

    return {
        "stop_loss":   sl,
        "take_profit": tp,
        "risk_dist":   round(abs(risk), 8),
        "risk_pct":    round(abs(risk) / entry * 100, 3),
        "rr":          rr,
    }


# ─── MAIN L1 SCAN ─────────────────────────────────────────────────────────────

def scan_for_bos(symbol: str) -> dict | None:
    """L1 scan — detects BOS on 15m and 5m, returns setup if valid."""
    for tf in ["15m", "5m"]:
        df = fetch_ohlcv(symbol, interval=tf, limit=100)
        if df is None or df.empty or len(df) < 20:
            continue
        bos = detect_bos(df)
        if not bos:
            continue

        # Build fib zone safely
        try:
           fib = calculate_fib_zone(bos)
           if not fib or "zone_low" not in fib or "zone_high" not in fib:
                return hold("Fib calculation failed", {"bos": bos, "sub_scores": sub})
        except Exception:
            return hold("Fib calculation error", {"bos": bos, "sub_scores": sub})
       
        # Validate fib keys exist
        if not fib or "zone_low" not in fib or "zone_high" not in fib:
            continue

        ob = identify_order_block(df, bos, fib)
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

# ─── MAIN L2 ENTRY CHECK ──────────────────────────────────────────────────────

def check_entry_for_setup(setup: dict) -> dict | None:
    """
    L2 entry check — runs every 60 seconds on active setups only.
    Verifies price is in zone and entry candle confirms.
    """
    symbol    = setup["symbol"]
    bos       = setup["bos"]
    fib       = setup["fib"]
    ob        = setup["ob"]
    direction = setup["direction"]
    bias      = setup.get("bias", {})
    fvg       = setup.get("fvg")
    liq_sweep = setup.get("liq_sweep", False)
    sd_zone   = setup.get("sd_zone")
    htf_aligned = setup.get("htf_aligned", True)

    df_1m  = fetch_ohlcv(symbol, interval="1m", limit=10)
    df_5m  = fetch_ohlcv(symbol, interval="5m", limit=10)
    df_15m = fetch_ohlcv(symbol, interval="15m", limit=100)

    if df_1m is None or df_1m.empty:
        return None

    price = float(df_1m["close"].iloc[-1])

    # Check price is in confluence zone
    in_fib = fib["zone_low"] <= price <= fib["zone_high"]
    in_ob  = ob["ob_low"]    <= price <= ob["ob_high"]
    if not (in_fib and in_ob):
        return None

    # Invalidation check
    if direction == "bullish" and price < bos.get("impulse_low", 0):
        return None
    if direction == "bearish" and price > bos.get("impulse_high", float("inf")):
        return None

    # Re-check directional bias in real time
    fresh_bias = get_directional_bias(symbol)
    if fresh_bias["bias"] == "bullish" and direction == "bearish":
        print(f"[L2] {symbol} SELL blocked — bias flipped BULLISH")
        return None
    if fresh_bias["bias"] == "bearish" and direction == "bullish":
        print(f"[L2] {symbol} BUY blocked — bias flipped BEARISH")
        return None

    # Entry confirmation
    entry_tf   = "1m"
    entry_conf = check_entry_confirmation(df_1m, direction)
    if not entry_conf["confirmed"]:
        entry_tf   = "5m"
        entry_conf = check_entry_confirmation(df_5m, direction)

    if not entry_conf["confirmed"]:
        return None

    # Calculate ATR and confidence
    atr = compute_atr(df_15m) if df_15m is not None and not df_15m.empty and len(df_15m) >= 15 \
          else price * 0.015

    confidence = calculate_confidence(
        bias           = fresh_bias,
        direction      = direction,
        has_fvg        = bool(fvg),
        has_liquidity_sweep = liq_sweep,
        has_sd_zone    = bool(sd_zone),
        entry_type     = entry_conf["type"],
        htf_aligned    = htf_aligned,
    )

    sl_tp  = calculate_sl_tp(price, ob, direction, atr, confidence)
    signal = "BUY" if direction == "bullish" else "SELL"

    confluence_list = []
    if fresh_bias["bias"] == direction:
        confluence_list.append(f"4H+1H bias {direction}")
    if fvg:
        confluence_list.append("FVG present")
    if liq_sweep:
        confluence_list.append("Liquidity swept")
    if sd_zone:
        confluence_list.append("S/D zone")

    print(f"[ENTRY] ✓ {symbol} {signal} @ {price} | conf={confidence}% "
          f"| {entry_conf['type']} on {entry_tf} "
          f"| {' + '.join(confluence_list)}")

    return {
        "symbol":       symbol,
        "signal":       signal,
        "confidence":   confidence,
        "raw_score":    0.9 if signal == "BUY" else -0.9,
        "strategy":     "SMC_v5_BIAS",
        "reasoning":    [
            f"HTF Bias: {fresh_bias['4h'].upper()} (4H) + {fresh_bias['1h'].upper()} (1H)",
            f"BOS {direction} confirmed on {setup['timeframe']}",
            f"Fib+OB confluence zone: ${fib['zone_low']:.5f}–${fib['zone_high']:.5f}",
            f"Entry: {entry_conf['type']} on {entry_tf}",
            *([f"FVG at ${fvg['fvg_low']:.5f}–${fvg['fvg_high']:.5f}"] if fvg else []),
            *([f"Liquidity sweep confirmed"] if liq_sweep else []),
        ],
        "bos":          bos,
        "fib":          fib,
        "ob":           ob,
        "bias":         fresh_bias,
        "entry_tf":     entry_tf,
        "entry_type":   entry_conf["type"],
        "sl_tp":        sl_tp,
        "sub_scores": {"bos":1,"fib":1,"ob":1,"ma":1,"entry":1,"bias":1},
        "market": {
            "price": price, "atr": atr, "atr_ok": True,
            "rsi": 50, "rsi_score": 0,
            "macd": {"histogram": 0}, "macd_score": 0,
            "trend": {"score": 1.0 if direction=="bullish" else -1.0, "label": direction},
            "volume": {"score": 0}, "change_pct": 0,
        },
        "sentiment": {"score": 0, "label": "neutral"},
    }


# ─── EMA MOMENTUM SCALP ───────────────────────────────────────────────────────

def ema_momentum_scan(symbol: str) -> dict | None:
    """
    Secondary strategy — EMA9/21 cross with bias confirmation.
    Only fires when aligned with HTF bias.
    """
    bias = get_directional_bias(symbol)
    df   = fetch_ohlcv(symbol, interval="5m", limit=60)
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

    # Must align with HTF bias
    if bias["bias"] != direction and bias["bias"] != "neutral":
        return None

    if direction == "bullish" and not (e50n > e50p and price > e50n):
        return None
    if direction == "bearish" and not (e50n < e50p and price < e50n):
        return None

    atr = compute_atr(df)
    if atr == 0:
        atr = price * 0.015

    if direction == "bullish":
        sl = round(price - atr * 1.5, 8)
        tp = round(price + atr * 3.0, 8)
    else:
        sl = round(price + atr * 1.5, 8)
        tp = round(price - atr * 3.0, 8)

    signal = "BUY" if direction == "bullish" else "SELL"
    buf    = atr * 0.5
    ob_fake = {"ob_high": price + buf, "ob_low": price - buf, "direction": direction}
    sl_tp   = {"stop_loss": sl, "take_profit": tp,
               "risk_dist": abs(price-sl), "risk_pct": abs(price-sl)/price*100}
    bos_fake = {"direction": direction, "bos_level": price,
                "impulse_high": price+atr*2, "impulse_low": price-atr*2}
    fib_fake = {"zone_high": price+buf, "zone_low": price-buf, "range": atr*2}

    confidence = calculate_confidence(
        bias=bias, direction=direction,
        has_fvg=False, has_liquidity_sweep=False, has_sd_zone=False,
        entry_type="momentum", htf_aligned=bias["bias"]==direction,
    )

    return {
        "symbol": symbol, "signal": signal, "confidence": confidence,
        "raw_score": 0.85 if signal == "BUY" else -0.85,
        "strategy": "EMA_CROSS_BIAS",
        "bos": bos_fake, "fib": fib_fake, "ob": ob_fake,
        "bias": bias, "entry_tf": "5m", "entry_type": "ema_cross",
        "sl_tp": sl_tp,
        "sub_scores": {"bos":1,"fib":1,"ob":1,"ma":1,"entry":1,"bias":1},
        "reasoning": [f"EMA9/21 cross {direction} + HTF bias confirmed"],
        "market": {"price": price, "atr": atr, "atr_ok": True,
                   "rsi":50,"rsi_score":0,"macd":{"histogram":0},"macd_score":0,
                   "trend":{"score":1.0 if direction=="bullish" else -1.0,"label":direction},
                   "volume":{"score":0},"change_pct":0},
        "sentiment": {"score": 0, "label": "neutral"},
    }


# ─── DASHBOARD COMPUTE SIGNAL ─────────────────────────────────────────────────

def compute_signal(symbol: str, learned_bias: float = 0.0) -> dict:
    """Cache/dashboard signal — shows bias and structure state."""
    df = fetch_ohlcv(symbol, interval="5m", limit=100)
    price = 0.0
    if df is not None and not df.empty:
        price = float(df["close"].iloc[-1])

    bias = get_directional_bias(symbol)

    def hold(reason, extra=None):
        base = {
            "symbol": symbol, "signal": "HOLD", "reason": reason,
            "confidence": 0, "raw_score": 0, "sub_scores": {},
            "bias": bias,
            "market": {"price": price, "atr": 0, "atr_ok": True,
                       "rsi":50,"rsi_score":0,"macd":{"histogram":0},"macd_score":0,
                       "trend":{"score":0,"label":"neutral"},
                       "volume":{"score":0},"change_pct":0},
            "sentiment": {"score": 0, "label": "neutral"},
        }
        if extra:
            base.update(extra)
        return base

    if df is None or df.empty or len(df) < 20:
        return hold("No 5m data")

    bos = detect_bos(df)
    sub = {"bos":0,"fib":0,"ob":0,"ma":0,"entry":0,"bias":0}

    if bias["bias"] != "neutral":
        sub["bias"] = 1

    if not bos:
        reason = f"No BOS on 5m | HTF: {bias['4h'].upper()} 4H / {bias['1h'].upper()} 1H"
        return hold(reason, {"sub_scores": sub})

    sub["bos"] = 1
    direction = bos["direction"]
    fib  = calculate_fib_zone(bos)
    ob   = identify_order_block(df, bos, fib)
    ma   = check_ma_filter(df, direction)

    in_fib = fib["zone_low"] <= price <= fib["zone_high"]
    in_ob  = ob and ob["ob_low"] <= price <= ob["ob_high"] if ob else False

    if in_fib:   sub["fib"] = 1
    if in_ob:    sub["ob"]  = 1
    if ma:       sub["ma"]  = 1

    bias_blocked = (bias["bias"] == "bullish" and direction == "bearish") or \
                   (bias["bias"] == "bearish" and direction == "bullish")

    if bias_blocked:
        reason = f"BOS {direction} BLOCKED by HTF bias ({bias['4h']} 4H)"
    elif not in_fib:
        reason = f"BOS {direction} | bias={bias['bias']} | Waiting for fib zone"
    elif not ob:
        reason = "BOS + Fib ✓ | No OB found"
    elif not in_ob:
        reason = f"BOS + Fib + OB ✓ | Price not in OB yet"
    elif not ma:
        reason = "Structure met | MA not aligned"
    else:
        reason = f"All conditions met | Monitoring for {direction} entry"

    return hold(reason, {
        "bos": bos, "fib": fib, "ob": ob,
        "sub_scores": sub,
        "market": {"price": price, "atr": 0, "atr_ok": True,
                   "rsi":50,"rsi_score":0,"macd":{"histogram":0},"macd_score":0,
                   "trend":{"score":1 if direction=="bullish" else -1,"label":direction},
                   "volume":{"score":0},"change_pct":0},
    })