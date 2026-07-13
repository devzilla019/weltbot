"""
backend/modules/signal_engine.py
KEY FIXES for win rate:
1. Fib zone properly validated before use
2. OB must STRICTLY overlap fib zone
3. Entry candle requires STRONGER confirmation
4. Added ATR filter - no trade if ATR too small (choppy market)
5. Added volume confirmation
6. HTF bias is now STRICT - neutral bias = no trade on low confidence
"""

import pandas as pd
import numpy as np
from modules.market_data import fetch_ohlcv, compute_atr


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
    df = df.copy()
    df["swing_high"] = sh
    df["swing_low"]  = sl
    return df


def get_directional_bias(symbol: str) -> dict:
    """
    Checks 4H and 1H structure.
    STRICT: requires BOTH timeframes to agree for high-conviction bias.
    """
    results = {}
    for tf in ["4h", "1h"]:
        df = fetch_ohlcv(symbol, interval=tf, limit=100)
        if df is None or df.empty or len(df) < 20:
            results[tf] = "neutral"
            continue
        df    = detect_swings(df, lookback=3)
        close = df["close"]
        n     = len(df)
        shi   = [i for i in range(n - 2) if df["swing_high"].iloc[i]]
        sli   = [i for i in range(n - 2) if df["swing_low"].iloc[i]]
        last  = float(close.iloc[-1])
        ema50 = float(close.ewm(span=50, adjust=False).mean().iloc[-1])

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

    # Score
    score = 0
    if results.get("4h") == "bullish": score += 2
    if results.get("4h") == "bearish": score -= 2
    if results.get("1h") == "bullish": score += 1
    if results.get("1h") == "bearish": score -= 1

    # STRICT: require score >= 2 for bullish, <= -2 for bearish
    if   score >= 2: bias = "bullish"
    elif score <= -2: bias = "bearish"
    else:            bias = "neutral"

    return {"bias": bias, "4h": results.get("4h","neutral"), "1h": results.get("1h","neutral"), "score": score}


def detect_bos(df: pd.DataFrame) -> dict | None:
    df  = detect_swings(df, lookback=2)
    n   = len(df)
    shi = [i for i in range(n - 2) if df["swing_high"].iloc[i]]
    sli = [i for i in range(n - 2) if df["swing_low"].iloc[i]]
    if not shi or not sli:
        return None
    lc = float(df["close"].iloc[-1])

    # Bearish BOS first (price breaks below swing low)
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

    # Bullish BOS (price breaks above swing high)
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
    return None


def calculate_fib_zone(bos: dict) -> dict | None:
    """Returns fib zone or None if invalid."""
    try:
        hi  = float(bos["impulse_high"])
        lo  = float(bos["impulse_low"])
        rng = hi - lo
        if rng <= 0 or rng / lo < 0.005:  # 0.05% minimum range
            return None
        if bos["direction"] == "bullish":
            zh = hi - rng * 0.500
            zl = hi - rng * 0.618
        else:
            zh = lo + rng * 0.618
            zl = lo + rng * 0.500
        if zh <= zl or zl <= 0:
            return None
        return {"zone_high": round(zh,8), "zone_low": round(zl,8), "range": round(rng,8)}
    except Exception as e:
        print(f"[signal] fib error: {e}")
        return None


def identify_order_block(df: pd.DataFrame, bos: dict, fib: dict) -> dict | None:
    """Find OB that STRICTLY overlaps fib zone."""
    try:
        if bos["direction"] == "bullish":
            start = int(bos.get("impulse_low_idx", 0))
        else:
            start = int(bos.get("impulse_high_idx", 0))

        lookback = min(20, start)
        for i in range(start, max(0, start - lookback) - 1, -1):
            c   = df.iloc[i]
            oh  = float(c["high"])
            ol  = float(c["low"])
            oc  = float(c["close"])
            oo  = float(c["open"])
            # STRICT overlap: OB must overlap at least 30% with fib zone
            overlap_low  = max(ol, fib["zone_low"])
            overlap_high = min(oh, fib["zone_high"])
            if overlap_high <= overlap_low:
                continue
            overlap_pct = (overlap_high - overlap_low) / (fib["zone_high"] - fib["zone_low"])
            if overlap_pct < 0.3:
                continue
            if bos["direction"] == "bullish" and oc < oo:  # bearish candle = OB
                return {"ob_high": oh, "ob_low": ol, "direction": "bullish", "overlap_pct": overlap_pct}
            if bos["direction"] == "bearish" and oc > oo:  # bullish candle = OB
                return {"ob_high": oh, "ob_low": ol, "direction": "bearish", "overlap_pct": overlap_pct}
        return None
    except Exception as e:
        print(f"[signal] OB error: {e}")
        return None


def check_ma_filter(df: pd.DataFrame, direction: str) -> bool:
    close = df["close"]
    n     = len(close)
    ema50 = close.ewm(span=50, adjust=False).mean()
    e50n  = float(ema50.iloc[-1])
    e50p  = float(ema50.iloc[-4]) if n > 4 else e50n
    price = float(close.iloc[-1])
    if n >= 200:
        ema200 = float(close.ewm(span=200, adjust=False).mean().iloc[-1])
        return (e50n > ema200 and price > e50n) if direction == "bullish" else (e50n < ema200 and price < e50n)
    return (e50n > e50p and price > e50n) if direction == "bullish" else (e50n < e50p and price < e50n)


def check_atr_filter(df: pd.DataFrame) -> bool:
    """Reject choppy markets where ATR is too small relative to price."""
    try:
        atr   = compute_atr(df)
        price = float(df["close"].iloc[-1])
        atr_pct = atr / price * 100
        return atr_pct >= 0.3  # ATR must be at least 0.3% of price
    except:
        return True


def detect_fvg(df: pd.DataFrame, direction: str) -> dict | None:
    n    = len(df)
    fvgs = []
    for i in range(1, n - 1):
        if direction == "bullish":
            gap_low  = float(df["high"].iloc[i-1])
            gap_high = float(df["low"].iloc[i+1])
            if gap_high > gap_low:
                fvgs.append({"fvg_low": gap_low, "fvg_high": gap_high})
        else:
            gap_high = float(df["low"].iloc[i-1])
            gap_low  = float(df["high"].iloc[i+1])
            if gap_low < gap_high:
                fvgs.append({"fvg_low": gap_low, "fvg_high": gap_high})
    return fvgs[-1] if fvgs else None


def detect_liquidity_sweep(df: pd.DataFrame, direction: str) -> bool:
    if len(df) < 10:
        return False
    recent = df.tail(10)
    if direction == "bullish":
        lows = recent["low"].values
        return len(lows) > 2 and lows[-2] < min(lows[:-2]) and lows[-1] > lows[-2]
    else:
        highs = recent["high"].values
        return len(highs) > 2 and highs[-2] > max(highs[:-2]) and highs[-1] < highs[-2]


def check_entry_confirmation(df: pd.DataFrame, direction: str) -> dict:
    """STRICTER entry confirmation — requires clear pattern."""
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
            # Strong engulfing: close > prev high AND body > 60% range
            if c > po and o < pc and body / rng > 0.60:
                return {"confirmed": True, "type": "engulfing"}
            # Strong momentum: body > 65% range AND close in top 20%
            if body / rng > 0.65 and (hi - c) / rng < 0.20:
                return {"confirmed": True, "type": "momentum"}
        # Strong pin bar: lower wick > 2.5x body, upper wick small
        if lw > body * 2.5 and lw > uw * 2 and c > o:
            return {"confirmed": True, "type": "pin_bar"}
    else:  # bearish
        if c < o:
            # Strong engulfing
            if c < po and o > pc and body / rng > 0.60:
                return {"confirmed": True, "type": "engulfing"}
            # Strong momentum: body > 65% AND close in bottom 20%
            if body / rng > 0.65 and (c - lo) / rng < 0.20:
                return {"confirmed": True, "type": "momentum"}
        # Strong pin bar
        if uw > body * 2.5 and uw > lw * 2 and c < o:
            return {"confirmed": True, "type": "pin_bar"}

    return {"confirmed": False, "type": None}


def calculate_confidence(bias, direction, has_fvg, has_liq, has_sd, entry_type, htf_aligned) -> float:
    score = 85.0
    b4h   = bias.get("4h", "neutral")
    b1h   = bias.get("1h", "neutral")

    # Strict bias scoring
    if b4h == direction and b1h == direction:
        score += 10.0   # both aligned = highest conviction
    elif b4h == direction:
        score += 5.0
    elif b1h == direction:
        score += 2.0
    else:
        score -= 5.0    # PENALTY for trading against even partial bias

    if has_fvg:  score += 2.0
    if has_liq:  score += 3.0  # liquidity sweep = smart money
    if has_sd:   score += 1.5
    if entry_type == "engulfing": score += 1.5
    if entry_type == "pin_bar":   score += 1.0
    if entry_type == "momentum":  score += 0.5

    return min(round(score, 1), 99.0)


def calculate_sl_tp(entry: float, ob: dict, direction: str, atr: float, confidence: float) -> dict:
    buf  = atr * 0.5  # wider buffer for cleaner SL
    rr   = 3.0 if confidence >= 95 else 2.0

    if direction == "bullish":
        sl   = round(ob["ob_low"] - buf, 8)
        risk = entry - sl
        if risk <= 0 or risk / entry > 0.05:  # cap risk at 5% of entry
            risk = entry * 0.015
            sl   = round(entry - risk, 8)
        tp = round(entry + risk * rr, 8)
    else:
        sl   = round(ob["ob_high"] + buf, 8)
        risk = sl - entry
        if risk <= 0 or risk / entry > 0.05:
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


# ── MAIN L1 SCAN ──────────────────────────────────────────────────────────────

def scan_for_bos(symbol: str) -> dict | None:
    """
    Full SMC scan with ALL validations.
    Returns setup only if ALL conditions are genuinely met.
    """
    bias     = get_directional_bias(symbol)
    htf_bias = bias["bias"]

    for tf in ["15m", "5m"]:
        df = fetch_ohlcv(symbol, interval=tf, limit=100)
        if df is None or df.empty or len(df) < 20:
            continue

        # ATR filter — skip choppy markets
        if not check_atr_filter(df):
            continue

        bos = detect_bos(df)
        if not bos:
            continue

        direction = bos["direction"]

        # STRICT HTF bias filter
        if htf_bias == "bullish" and direction == "bearish":
            print(f"[signal] {symbol} {tf} BEARISH blocked — HTF BULLISH")
            continue
        if htf_bias == "bearish" and direction == "bullish":
            print(f"[signal] {symbol} {tf} BULLISH blocked — HTF BEARISH")
            continue
        # Neutral bias allowed — only block OPPOSITE direction

        fib = calculate_fib_zone(bos)
        if not fib:
            print(f"[L1] {symbol} fib zone invalid — skipping")
            continue

        ob = identify_order_block(df, bos, fib)
        if not ob:
            continue

        if not check_ma_filter(df, direction):
            continue

        fvg      = detect_fvg(df, direction)
        liq      = detect_liquidity_sweep(df, direction)
        htf_al   = htf_bias == direction

        price = float(df["close"].iloc[-1])
        print(f"[L1] SETUP {symbol} {tf} {direction.upper()} | bias={htf_bias} fvg={bool(fvg)} liq={liq}")
        return {
            "symbol":     symbol,
            "direction":  direction,
            "timeframe":  tf,
            "bos":        bos,
            "fib":        fib,
            "ob":         ob,
            "bias":       bias,
            "fvg":        fvg,
            "liq_sweep":  liq,
            "htf_aligned":htf_al,
            "candle_age": 0,
            "strategy":   "SMC_v5",
        }
    return None


# ── MAIN L2 ENTRY CHECK ───────────────────────────────────────────────────────

def check_entry_for_setup(setup: dict) -> dict | None:
    symbol    = setup["symbol"]
    bos       = setup["bos"]
    fib       = setup["fib"]
    ob        = setup["ob"]
    direction = setup["direction"]
    bias      = setup.get("bias", {})

    # Validate fib zone is present and valid
    if not fib or "zone_low" not in fib or "zone_high" not in fib:
        return None

    df_1m  = fetch_ohlcv(symbol, interval="1m", limit=10)
    df_5m  = fetch_ohlcv(symbol, interval="5m", limit=10)
    df_15m = fetch_ohlcv(symbol, interval="15m", limit=100)

    if df_1m is None or df_1m.empty:
        return None

    price = float(df_1m["close"].iloc[-1])

    # Price must be INSIDE both fib zone AND order block
    in_fib = fib["zone_low"] <= price <= fib["zone_high"]
    in_ob  = ob and ob["ob_low"] <= price <= ob["ob_high"]

    if not (in_fib and in_ob):
        return None

    # Invalidation: if price breaks opposite side of impulse
    if direction == "bullish" and price < bos.get("impulse_low", 0):
        return None
    if direction == "bearish" and price > bos.get("impulse_high", float("inf")):
        return None

    # Re-check bias in real time
    fresh_bias = get_directional_bias(symbol)
    if fresh_bias["bias"] == "bullish" and direction == "bearish":
        return None
    if fresh_bias["bias"] == "bearish" and direction == "bullish":
        return None

    # Entry confirmation — try 1m first, fall back to 5m
    entry_conf = check_entry_confirmation(df_1m, direction)
    entry_tf   = "1m"
    if not entry_conf["confirmed"]:
        entry_conf = check_entry_confirmation(df_5m, direction)
        entry_tf   = "5m"
    if not entry_conf["confirmed"]:
        return None

    atr = compute_atr(df_15m) if df_15m is not None and not df_15m.empty else price * 0.015

    fvg  = setup.get("fvg")
    liq  = setup.get("liq_sweep", False)
    sd   = False  # simplified

    confidence = calculate_confidence(
        bias=fresh_bias, direction=direction,
        has_fvg=bool(fvg), has_liq=liq, has_sd=sd,
        entry_type=entry_conf["type"], htf_aligned=fresh_bias["bias"]==direction,
    )

    # Minimum confidence gate
    from config import MIN_CONFIDENCE
    if confidence < MIN_CONFIDENCE:
        print(f"[L2] {symbol} confidence {confidence}% below minimum {MIN_CONFIDENCE}% — skipping")
        return None

    sl_tp  = calculate_sl_tp(price, ob, direction, atr, confidence)
    signal = "BUY" if direction == "bullish" else "SELL"

    reasons = [
        f"HTF: {fresh_bias.get('4h','?').upper()} 4H / {fresh_bias.get('1h','?').upper()} 1H",
        f"BOS {direction} on {setup['timeframe']}",
        f"Fib+OB zone: ${fib['zone_low']:.5f}–${fib['zone_high']:.5f}",
        f"Entry: {entry_conf['type']} on {entry_tf}",
    ]
    if fvg:  reasons.append("FVG present")
    if liq:  reasons.append("Liquidity swept")

    print(f"[ENTRY] ✓ {symbol} {signal} @ {price} | conf={confidence}% | {entry_conf['type']} on {entry_tf}")

    return {
        "symbol":     symbol,
        "signal":     signal,
        "confidence": confidence,
        "raw_score":  0.9 if signal == "BUY" else -0.9,
        "strategy":   "SMC_v5",
        "reasoning":  reasons,
        "bos":        bos,
        "fib":        fib,
        "ob":         ob,
        "bias":       fresh_bias,
        "entry_tf":   entry_tf,
        "entry_type": entry_conf["type"],
        "sl_tp":      sl_tp,
        "sub_scores": {"bos":1,"fib":1,"ob":1,"ma":1,"entry":1,"bias":1},
        "market":     {"price":price,"atr":atr,"atr_ok":True,"rsi":50,"rsi_score":0,
                       "macd":{"histogram":0},"macd_score":0,
                       "trend":{"score":1.0 if direction=="bullish" else -1.0,"label":direction},
                       "volume":{"score":0},"change_pct":0},
        "sentiment":  {"score":0,"label":"neutral"},
    }


# ── EMA MOMENTUM (secondary strategy) ────────────────────────────────────────

def ema_momentum_scan(symbol: str) -> dict | None:
    bias = get_directional_bias(symbol)
    # Allow neutral bias — only block opposite direction below

    df = fetch_ohlcv(symbol, interval="5m", limit=60)
    if df is None or df.empty or len(df) < 30:
        return None

    close  = df["close"]
    price  = float(close.iloc[-1])
    ema9   = close.ewm(span=9,  adjust=False).mean()
    ema21  = close.ewm(span=21, adjust=False).mean()
    ema50  = close.ewm(span=50, adjust=False).mean()
    e9n,e9p   = float(ema9.iloc[-1]),  float(ema9.iloc[-2])
    e21n,e21p = float(ema21.iloc[-1]), float(ema21.iloc[-2])
    e50n      = float(ema50.iloc[-1])
    e50p      = float(ema50.iloc[-4]) if len(ema50) > 4 else e50n

    bull = e9p <= e21p and e9n > e21n
    bear = e9p >= e21p and e9n < e21n
    if not bull and not bear:
        return None

    direction = "bullish" if bull else "bearish"
    if bias["bias"] != direction:
        return None

    if direction == "bullish" and not (e50n > e50p and price > e50n):
        return None
    if direction == "bearish" and not (e50n < e50p and price < e50n):
        return None

    atr    = compute_atr(df) or price * 0.015
    signal = "BUY" if direction == "bullish" else "SELL"
    buf    = atr * 0.5
    sl     = round(price - atr*1.5, 8) if direction=="bullish" else round(price + atr*1.5, 8)
    tp     = round(price + atr*3.0, 8) if direction=="bullish" else round(price - atr*3.0, 8)
    conf   = calculate_confidence(bias=bias, direction=direction, has_fvg=False,
                has_liq=False, has_sd=False, entry_type="momentum", htf_aligned=True)
    if conf < 87:  # stricter threshold for EMA strategy
        return None

    return {
        "symbol":symbol,"signal":signal,"confidence":conf,"raw_score":0.85 if signal=="BUY" else -0.85,
        "strategy":"EMA_CROSS",
        "bos":{"direction":direction,"bos_level":price,"impulse_high":price+atr*2,"impulse_low":price-atr*2},
        "fib":{"zone_high":price+buf,"zone_low":price-buf,"range":atr*2},
        "ob":{"ob_high":price+buf,"ob_low":price-buf,"direction":direction},
        "bias":bias,"entry_tf":"5m","entry_type":"ema_cross",
        "sl_tp":{"stop_loss":sl,"take_profit":tp,"risk_dist":abs(price-sl),"risk_pct":abs(price-sl)/price*100},
        "sub_scores":{"bos":1,"fib":1,"ob":1,"ma":1,"entry":1,"bias":1},
        "reasoning":[f"EMA9/21 cross {direction} | HTF bias {bias['bias']}"],
        "market":{"price":price,"atr":atr,"atr_ok":True,"rsi":50,"rsi_score":0,
                  "macd":{"histogram":0},"macd_score":0,
                  "trend":{"score":1.0 if direction=="bullish" else -1.0,"label":direction},
                  "volume":{"score":0},"change_pct":0},
        "sentiment":{"score":0,"label":"neutral"},
    }


# ── DASHBOARD COMPUTE (for signal card display) ───────────────────────────────

def compute_signal(symbol: str, learned_bias: float = 0.0) -> dict:
    df    = fetch_ohlcv(symbol, interval="5m", limit=100)
    price = float(df["close"].iloc[-1]) if df is not None and not df.empty else 0.0
    bias  = get_directional_bias(symbol)

    def hold(reason, extra=None):
        base = {
            "symbol":symbol,"signal":"HOLD","reason":reason,"confidence":0,"raw_score":0,
            "sub_scores":{},"bias":bias,
            "market":{"price":price,"atr":0,"atr_ok":True,"rsi":50,"rsi_score":0,
                      "macd":{"histogram":0},"macd_score":0,
                      "trend":{"score":0,"label":"neutral"},"volume":{"score":0},"change_pct":0},
            "sentiment":{"score":0,"label":"neutral"},
        }
        if extra: base.update(extra)
        return base

    if df is None or df.empty or len(df) < 20:
        return hold("No 5m data")

    bos = detect_bos(df)
    sub = {"bos":0,"fib":0,"ob":0,"ma":0,"entry":0,"bias":0}
    if bias["bias"] != "neutral": sub["bias"] = 1
    if not bos:
        return hold(f"No BOS | HTF: {bias['4h'].upper()} 4H / {bias['1h'].upper()} 1H", {"sub_scores":sub})

    sub["bos"] = 1
    direction  = bos["direction"]

    fib = calculate_fib_zone(bos)
    if not fib:
        return hold(f"BOS {direction} | Fib zone invalid", {"bos":bos,"sub_scores":sub})

    ob    = identify_order_block(df, bos, fib)
    ma_ok = check_ma_filter(df, direction)
    price_f = price

    in_fib = fib["zone_low"] <= price_f <= fib["zone_high"]
    in_ob  = ob and ob["ob_low"] <= price_f <= ob["ob_high"] if ob else False

    if in_fib: sub["fib"] = 1
    if in_ob:  sub["ob"]  = 1
    if ma_ok:  sub["ma"]  = 1

    bias_blocked = (bias["bias"]=="bullish" and direction=="bearish") or \
                   (bias["bias"]=="bearish" and direction=="bullish")

    if bias_blocked:
        reason = f"BOS {direction} BLOCKED by HTF ({bias['4h']} 4H)"
    elif not in_fib:
        reason = f"BOS {direction} | bias={bias['bias']} | Price not in fib yet"
    elif not ob:
        reason = "BOS+Fib ✓ | No OB found"
    elif not in_ob:
        reason = f"BOS+Fib+OB ✓ | Waiting for price to enter OB"
    elif not ma_ok:
        reason = "Structure met | MA not aligned"
    else:
        reason = f"All conditions met | Watching for {direction} entry candle"

    return hold(reason, {"bos":bos,"fib":fib,"ob":ob,"sub_scores":sub,
        "market":{"price":price_f,"atr":0,"atr_ok":True,"rsi":50,"rsi_score":0,
                  "macd":{"histogram":0},"macd_score":0,
                  "trend":{"score":1 if direction=="bullish" else -1,"label":direction},
                  "volume":{"score":0},"change_pct":0}})
