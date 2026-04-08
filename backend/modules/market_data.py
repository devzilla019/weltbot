import pandas as pd
import numpy as np
import requests
import hmac
import hashlib
import time
from urllib.parse import urlencode
from config import BINANCE_API_KEY, BINANCE_SECRET_KEY, BINANCE_TESTNET

TESTNET_BASE = "https://testnet.binance.vision"
MAINNET_BASE = "https://api.binance.com"
BASE_URL     = TESTNET_BASE if BINANCE_TESTNET else MAINNET_BASE

_cached_balance = 0.0
_balance_ts     = 0.0


def _get_headers():
    return {"X-MBX-APIKEY": BINANCE_API_KEY.strip()}


def _sign(params: dict) -> dict:
    params["timestamp"]  = int(time.time() * 1000)
    params["recvWindow"] = 20000
    query  = urlencode(params)
    secret = BINANCE_SECRET_KEY.strip().encode()
    sig    = hmac.new(secret, query.encode(), hashlib.sha256).hexdigest()
    params["signature"] = sig
    return params


def get_balance() -> float:
    global _cached_balance, _balance_ts
    now = time.time()
    if _cached_balance > 0 and (now - _balance_ts) < 60:
        return _cached_balance
    for attempt in range(3):
        try:
            params = _sign({})
            resp   = requests.get(
                f"{BASE_URL}/api/v3/account",
                params  = params,
                headers = _get_headers(),
                timeout = 15,
            )
            data = resp.json()
            for b in data.get("balances", []):
                if b["asset"] == "USDT":
                    val = float(b["free"])
                    if val >= 0:
                        _cached_balance = val
                        _balance_ts     = now
                    return _cached_balance
        except Exception as e:
            print(f"[market_data] balance error (attempt {attempt+1}): {e}")
            time.sleep(2)
    return _cached_balance


def get_ticker_price(symbol: str) -> float:
    try:
        sym  = symbol.replace("/", "")
        resp = requests.get(
            f"{BASE_URL}/api/v3/ticker/price",
            params  = {"symbol": sym},
            timeout = 8,
        )
        return float(resp.json().get("price", 0))
    except Exception as e:
        print(f"[market_data] ticker error {symbol}: {e}")
        return 0.0


def fetch_ohlcv(symbol: str, interval: str = "1h", limit: int = 60) -> pd.DataFrame:
    for attempt in range(3):
        try:
            sym  = symbol.replace("/", "")
            resp = requests.get(
                f"{BASE_URL}/api/v3/klines",
                params  = {"symbol": sym, "interval": interval, "limit": limit},
                timeout = 12,
            )
            data = resp.json()
            if not isinstance(data, list) or len(data) < 10:
                if attempt < 2:
                    time.sleep(2)
                    continue
                return pd.DataFrame()
            df = pd.DataFrame(data, columns=[
                "timestamp","open","high","low","close","volume",
                "close_time","quote_vol","trades","taker_base","taker_quote","ignore"
            ])
            df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
            df.set_index("timestamp", inplace=True)
            for col in ["open","high","low","close","volume"]:
                df[col] = pd.to_numeric(df[col])
            return df[["open","high","low","close","volume"]]
        except Exception as e:
            print(f"[market_data] fetch error {symbol} (attempt {attempt+1}): {e}")
            if attempt < 2:
                time.sleep(2)
    return pd.DataFrame()


_lot_cache: dict = {}

def get_lot_size_rules(symbol: str) -> dict:
    sym = symbol.replace("/", "")
    if sym in _lot_cache:
        return _lot_cache[sym]
    try:
        resp = requests.get(
            f"{BASE_URL}/api/v3/exchangeInfo",
            params={"symbol": sym},
            timeout=10,
        )
        data = resp.json()
        for s in data.get("symbols", []):
            if s["symbol"] == sym:
                rules = {"min_qty": 0.0, "step_size": 0.0, "min_notional": 0.0}
                for f in s.get("filters", []):
                    if f["filterType"] == "LOT_SIZE":
                        rules["min_qty"]   = float(f["minQty"])
                        rules["step_size"] = float(f["stepSize"])
                    if f["filterType"] == "NOTIONAL":
                        rules["min_notional"] = float(f.get("minNotional", 0))
                    if f["filterType"] == "MIN_NOTIONAL":
                        rules["min_notional"] = float(f.get("minNotional", 0))
                _lot_cache[sym] = rules
                return rules
    except Exception as e:
        print(f"[market_data] lot size error {symbol}: {e}")
    return {"min_qty": 0.001, "step_size": 0.001, "min_notional": 5.0}


def round_step_size(quantity: float, step_size: float) -> float:
    if step_size <= 0:
        return quantity
    import math
    precision = int(round(-math.log10(step_size)))
    factor    = 10 ** precision
    return math.floor(quantity * factor) / factor


def place_order_raw(symbol: str, side: str, quantity: float) -> dict:
    try:
        sym   = symbol.replace("/", "")
        rules = get_lot_size_rules(symbol)

        step      = rules["step_size"]
        min_qty   = rules["min_qty"]
        min_notl  = rules["min_notional"]
        price     = get_ticker_price(symbol)

        qty = round_step_size(quantity, step)

        if qty < min_qty:
            qty = min_qty

        if price > 0 and qty * price < min_notl:
            qty = round_step_size(min_notl / price * 1.01, step)
            if qty < min_qty:
                qty = min_qty

        qty_str = f"{qty:.8f}".rstrip("0").rstrip(".")
        print(f"[market_data] placing {side} {qty_str} {sym} (step={step} min={min_qty})")

        params = _sign({
            "symbol":        sym,
            "side":          side.upper(),
            "type":          "MARKET",
            "quantity":      qty_str,
            "recvWindow":    20000,
        })
        resp = requests.post(
            f"{BASE_URL}/api/v3/order",
            params  = params,
            headers = _get_headers(),
            timeout = 15,
        )
        data = resp.json()
        if "code" in data:
            print(f"[market_data] order error: {data}")
            return {"success": False, "error": data.get("msg", str(data))}

        fills      = data.get("fills", [])
        fill_price = float(fills[0]["price"]) if fills else price
        qty_filled = float(data.get("executedQty", qty))

        return {
            "success":    True,
            "order_id":   str(data.get("orderId", "")),
            "fill_price": fill_price,
            "qty_filled": qty_filled,
            "raw":        data,
        }
    except Exception as e:
        print(f"[market_data] place_order_raw error: {e}")
        return {"success": False, "error": str(e)}

def compute_rsi(close: pd.Series, period: int = 14) -> float:
    if len(close) < period + 1:
        return 50.0
    delta = close.diff()
    gain  = delta.clip(lower=0).rolling(period).mean()
    loss  = (-delta.clip(upper=0)).rolling(period).mean()
    rs    = gain / loss.replace(0, np.nan)
    rsi   = 100 - (100 / (1 + rs))
    val   = float(rsi.iloc[-1])
    return round(val if not np.isnan(val) else 50.0, 2)


def score_rsi(rsi: float) -> float:
    if rsi < 30: return 1.0
    if rsi > 70: return -1.0
    return round((50 - rsi) / 20.0, 4)


def compute_macd(close: pd.Series) -> dict:
    ema12  = close.ewm(span=12, adjust=False).mean()
    ema26  = close.ewm(span=26, adjust=False).mean()
    macd   = ema12 - ema26
    signal = macd.ewm(span=9, adjust=False).mean()
    hist   = macd - signal
    return {
        "macd":      round(float(macd.iloc[-1]), 8),
        "signal":    round(float(signal.iloc[-1]), 8),
        "histogram": round(float(hist.iloc[-1]), 8),
    }


def score_macd(histogram: float, price: float) -> float:
    if price == 0: return 0.0
    return round(max(-1.0, min(1.0, (histogram / price) * 1000)), 4)


def compute_atr(df: pd.DataFrame, period: int = 14) -> float:
    if len(df) < period + 1:
        return float(df["close"].iloc[-1]) * 0.02
    high  = df["high"]
    low   = df["low"]
    close = df["close"]
    prev  = close.shift(1)
    tr    = pd.concat([
        (high - low),
        (high - prev).abs(),
        (low  - prev).abs(),
    ], axis=1).max(axis=1)
    val = float(tr.rolling(period).mean().iloc[-1])
    return round(val if not np.isnan(val) else float(df["close"].iloc[-1]) * 0.02, 8)


def compute_ema_trend(close: pd.Series, fast: int = 10, slow: int = 30) -> dict:
    ema_fast  = close.ewm(span=fast, adjust=False).mean()
    ema_slow  = close.ewm(span=slow, adjust=False).mean()
    delta_pct = float((ema_fast.iloc[-1] - ema_slow.iloc[-1]) / ema_slow.iloc[-1])
    if delta_pct > 0.003:
        label = "bullish"
    elif delta_pct < -0.003:
        label = "bearish"
    else:
        label = "neutral"
    score = round(max(-1.0, min(1.0, delta_pct * 30)), 4)
    return {"label": label, "score": score, "delta_pct": round(delta_pct, 6)}


def detect_volume_anomaly(volume: pd.Series, close: pd.Series, lookback: int = 10) -> dict:
    if len(volume) < lookback + 1:
        return {"spike": False, "ratio": 1.0, "score": 0.0}
    avg       = float(volume.rolling(lookback).mean().iloc[-1])
    ratio     = float(volume.iloc[-1]) / avg if avg > 0 else 1.0
    direction = 1 if float(close.iloc[-1]) >= float(close.iloc[-2]) else -1
    spike     = ratio > 1.5
    score     = round(min(1.0, (ratio - 1.0) / 2.0) * direction, 4) if spike else 0.0
    return {"spike": spike, "ratio": round(ratio, 2), "score": score}


def get_market_snapshot(symbol: str) -> dict:
    df = fetch_ohlcv(symbol, limit=60)
    if df.empty or len(df) < 30:
        return {"error": f"Insufficient data for {symbol} (got {len(df)} candles)"}
    close    = df["close"]
    volume   = df["volume"]
    price    = round(float(close.iloc[-1]), 8)
    prev     = round(float(close.iloc[-2]), 8)
    rsi_val  = compute_rsi(close)
    macd_val = compute_macd(close)
    atr_val  = compute_atr(df)
    trend    = compute_ema_trend(close)
    vol_anom = detect_volume_anomaly(volume, close)
    return {
        "symbol":     symbol,
        "price":      price,
        "change_pct": round((price / prev - 1) * 100, 3) if prev > 0 else 0.0,
        "volume":     vol_anom,
        "atr":        atr_val,
        "atr_ok":     True,
        "rsi":        rsi_val,
        "rsi_score":  score_rsi(rsi_val),
        "macd":       macd_val,
        "macd_score": score_macd(macd_val["histogram"], price),
        "trend":      trend,
    }
def fetch_multi_tf(symbol: str) -> dict:
    """Fetch 15m, 5m, and 1m candles for structure analysis."""
    return {
        "15m": fetch_ohlcv(symbol, interval="15m", limit=50),
        "5m":  fetch_ohlcv(symbol, interval="5m",  limit=30),
        "1m":  fetch_ohlcv(symbol, interval="1m",  limit=20),
    }