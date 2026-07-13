import pandas as pd
import numpy as np
import requests
import hmac
import hashlib
import time
from urllib.parse import urlencode
from config import BINANCE_API_KEY, BINANCE_SECRET_KEY, BINANCE_TESTNET

# ─── URLs ─────────────────────────────────────────────────────────────────────
# Market data — mainnet futures public API (no auth required)
import os as _os
# Use configurable market data URL — allows override for different regions
MARKET_DATA_URL = _os.getenv("MARKET_DATA_URL", "https://fapi.binance.com")

# Execution — demo trading for paper, mainnet for real
# Note: demo-fapi may not resolve from all servers — use fallback
FUTURES_DEMO_URL    = "https://demo-fapi.binance.com"
FUTURES_MAINNET_URL = "https://fapi.binance.com"

def _get_exec_url():
    import os
    env_url = os.getenv("FUTURES_EXEC_URL", "").strip()
    if env_url:
        return env_url
    if not BINANCE_TESTNET:
        return FUTURES_MAINNET_URL
    import socket
    try:
        socket.getaddrinfo("demo-fapi.binance.com", 443)
        return FUTURES_DEMO_URL
    except Exception:
        print("[market_data] demo-fapi DNS failed — using testnet.binancefuture.com")
        return "https://testnet.binancefuture.com"

EXEC_URL = _get_exec_url()

# ─── BALANCE CACHE ────────────────────────────────────────────────────────────
_cached_balance = 0.0
_balance_ts     = 0.0

# ─── LOT SIZE CACHE ───────────────────────────────────────────────────────────
_lot_cache: dict = {}


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


# ─── BALANCE ──────────────────────────────────────────────────────────────────

def get_balance() -> float:
    global _cached_balance, _balance_ts
    now = time.time()
    if _cached_balance > 0 and (now - _balance_ts) < 60:
        return _cached_balance
    for attempt in range(3):
        try:
            params = _sign({})
            resp   = requests.get(
                f"{EXEC_URL}/fapi/v2/balance",
                params=params, headers=_get_headers(), timeout=15,
            )
            data = resp.json()
            if isinstance(data, list):
                for b in data:
                    if b.get("asset") == "USDT":
                        val = float(b.get("availableBalance", 0))
                        if val == 0:
                            val = float(b.get("walletBalance", 0))
                        if val > 0:
                            _cached_balance = val
                            _balance_ts     = now
                            return val
        except Exception as e:
            print(f"[market_data] balance error (attempt {attempt+1}): {e}")
            time.sleep(2)
    return _cached_balance

def get_asset_balance(asset: str) -> float:
    """Not needed for futures — always returns 0 (we use USDT margin)."""
    return 0.0


# ─── MARKET DATA (mainnet public) ─────────────────────────────────────────────

def fetch_ohlcv(symbol: str, interval: str = "1h", limit: int = 60) -> pd.DataFrame:
    """
    Fetch OHLCV using multiple providers with fallback.
    Priority: Binance direct → Binance mirrors → CoinGecko
    CoinGecko works from ALL cloud servers with no IP restrictions.
    """
    sym = symbol.replace("/", "")

    # All Binance mirrors to try
    binance_endpoints = [
        f"https://api.binance.com/api/v3/klines",
        f"https://api1.binance.com/api/v3/klines",
        f"https://api2.binance.com/api/v3/klines",
        f"https://api3.binance.com/api/v3/klines",
        f"https://api4.binance.com/api/v3/klines",
        f"https://data-api.binance.vision/api/v3/klines",
    ]

    for url in binance_endpoints:
        try:
            resp = requests.get(
                url,
                params={"symbol": sym, "interval": interval, "limit": limit},
                timeout=10,
                headers={"User-Agent": "Mozilla/5.0 (compatible; TradingBot/1.0)"},
            )
            if resp.status_code == 200:
                data = resp.json()
                if isinstance(data, list) and len(data) >= 5:
                    df = pd.DataFrame(data, columns=[
                        "timestamp","open","high","low","close","volume",
                        "close_time","quote_vol","trades","taker_base","taker_quote","ignore"
                    ])
                    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
                    df.set_index("timestamp", inplace=True)
                    for col in ["open","high","low","close","volume"]:
                        df[col] = pd.to_numeric(df[col], errors="coerce")
                    df.dropna(subset=["close"], inplace=True)
                    if len(df) >= 5:
                        return df[["open","high","low","close","volume"]]
        except Exception:
            continue

    # CoinGecko fallback — works from ALL servers
    try:
        base_coin = sym.lower().replace("usdt", "")
        coin_map = {
            "btc": "bitcoin", "eth": "ethereum", "bnb": "binancecoin",
            "sol": "solana", "xrp": "ripple", "ada": "cardano",
            "doge": "dogecoin", "avax": "avalanche-2", "link": "chainlink",
            "uni": "uniswap", "ltc": "litecoin", "atom": "cosmos",
            "near": "near", "dot": "polkadot", "aave": "aave",
        }
        coin_id = coin_map.get(base_coin, base_coin)
        days_map = {"1m": 1, "5m": 1, "15m": 7, "1h": 30, "4h": 90, "1d": 365}
        days = days_map.get(interval, 7)

        resp = requests.get(
            f"https://api.coingecko.com/api/v3/coins/{coin_id}/ohlc",
            params={"vs_currency": "usd", "days": str(days)},
            timeout=15,
            headers={"User-Agent": "TradingBot/1.0"},
        )
        if resp.status_code == 200:
            raw = resp.json()
            if isinstance(raw, list) and len(raw) >= 5:
                df = pd.DataFrame(raw, columns=["timestamp","open","high","low","close"])
                df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
                df.set_index("timestamp", inplace=True)
                df["volume"] = 1000000.0
                for col in ["open","high","low","close"]:
                    df[col] = pd.to_numeric(df[col], errors="coerce")
                df.dropna(inplace=True)
                if len(df) >= 5:
                    df = df.tail(limit)
                    print(f"[market_data] using CoinGecko for {symbol}")
                    return df[["open","high","low","close","volume"]]
    except Exception as e:
        print(f"[market_data] CoinGecko error {symbol}: {e}")

    print(f"[market_data] all providers failed for {symbol}")
    return pd.DataFrame()


def get_ticker_price(symbol: str) -> float:
    sym = symbol.replace("/", "")

    # Try Binance mirrors first
    for base in [
        "https://api.binance.com",
        "https://api1.binance.com",
        "https://api2.binance.com",
        "https://data-api.binance.vision",
    ]:
        try:
            resp = requests.get(
                f"{base}/api/v3/ticker/price",
                params={"symbol": sym}, timeout=8,
                headers={"User-Agent": "Mozilla/5.0"},
            )
            if resp.status_code == 200:
                price = float(resp.json().get("price", 0))
                if price > 0:
                    return price
        except Exception:
            continue

    # CoinGecko price fallback
    try:
        base_coin = sym.lower().replace("usdt", "")
        coin_map = {
            "btc": "bitcoin", "eth": "ethereum", "bnb": "binancecoin",
            "sol": "solana", "xrp": "ripple", "ada": "cardano",
            "doge": "dogecoin", "avax": "avalanche-2", "link": "chainlink",
            "uni": "uniswap", "ltc": "litecoin", "atom": "cosmos",
            "near": "near", "dot": "polkadot", "aave": "aave",
        }
        coin_id = coin_map.get(base_coin, base_coin)
        resp = requests.get(
            f"https://api.coingecko.com/api/v3/simple/price",
            params={"ids": coin_id, "vs_currencies": "usd"},
            timeout=10,
            headers={"User-Agent": "TradingBot/1.0"},
        )
        if resp.status_code == 200:
            data = resp.json()
            price = data.get(coin_id, {}).get("usd", 0)
            if price > 0:
                print(f"[market_data] CoinGecko price {symbol}: ${price}")
                return float(price)
    except Exception as e:
        print(f"[market_data] CoinGecko price error {symbol}: {e}")

    return 0.0

# ─── LOT SIZE ─────────────────────────────────────────────────────────────────

_lot_cache: dict = {}

def get_lot_size_rules(symbol: str) -> dict:
    sym = symbol.replace("/", "")
    if sym in _lot_cache:
        return _lot_cache[sym]

    # Hardcoded futures precision rules for common assets
    # AAVE, LINK, UNI etc require whole number quantities on futures
    KNOWN_RULES = {
        "BTCUSDT":  {"min_qty": 0.001,  "step_size": 0.001,  "min_notional": 5.0},
        "ETHUSDT":  {"min_qty": 0.001,  "step_size": 0.001,  "min_notional": 5.0},
        "BNBUSDT":  {"min_qty": 0.01,   "step_size": 0.01,   "min_notional": 5.0},
        "SOLUSDT":  {"min_qty": 0.1,    "step_size": 0.1,    "min_notional": 5.0},
        "XRPUSDT":  {"min_qty": 1.0,    "step_size": 1.0,    "min_notional": 5.0},
        "ADAUSDT":  {"min_qty": 1.0,    "step_size": 1.0,    "min_notional": 5.0},
        "DOGEUSDT": {"min_qty": 1.0,    "step_size": 1.0,    "min_notional": 5.0},
        "AVAXUSDT": {"min_qty": 0.1,    "step_size": 0.1,    "min_notional": 5.0},
        "LINKUSDT": {"min_qty": 0.1,    "step_size": 0.1,    "min_notional": 5.0},
        "UNIUSDT":  {"min_qty": 0.1,    "step_size": 0.1,    "min_notional": 5.0},
        "LTCUSDT":  {"min_qty": 0.01,   "step_size": 0.01,   "min_notional": 5.0},
        "ATOMUSDT": {"min_qty": 0.01,   "step_size": 0.01,   "min_notional": 5.0},
        "NEARUSDT": {"min_qty": 0.1,    "step_size": 0.1,    "min_notional": 5.0},
        "DOTUSDT":  {"min_qty": 0.1,    "step_size": 0.1,    "min_notional": 5.0},
        "AAVEUSDT": {"min_qty": 0.01, "step_size": 0.01, "min_notional": 5.0},
    }

    if sym in KNOWN_RULES:
        _lot_cache[sym] = KNOWN_RULES[sym]
        return KNOWN_RULES[sym]

    # Try fetching from exchange info
    try:
        resp = requests.get(
            f"{MARKET_DATA_URL}/fapi/v1/exchangeInfo",
            timeout=10,
        )
        if resp.status_code == 200:
            data = resp.json()
            for s in data.get("symbols", []):
                if s["symbol"] == sym:
                    rules = {"min_qty": 0.001, "step_size": 0.001, "min_notional": 5.0}
                    for f in s.get("filters", []):
                        if f["filterType"] == "LOT_SIZE":
                            rules["min_qty"]   = float(f["minQty"])
                            rules["step_size"] = float(f["stepSize"])
                        if f["filterType"] in ("MIN_NOTIONAL", "NOTIONAL"):
                            rules["min_notional"] = float(f.get("notional", f.get("minNotional", 5.0)))
                    _lot_cache[sym] = rules
                    return rules
    except Exception as e:
        print(f"[market_data] lot size fetch error {symbol}: {e}")

    default = {"min_qty": 0.01, "step_size": 0.01, "min_notional": 5.0}
    _lot_cache[sym] = default
    return default


def round_step_size(quantity: float, step_size: float) -> float:
    import math
    if step_size <= 0:
        return quantity
    precision = int(round(-math.log10(step_size)))
    factor    = 10 ** precision
    return math.floor(quantity * factor) / factor


# ─── ORDER PLACEMENT (futures) ────────────────────────────────────────────────

def set_leverage(symbol: str, leverage: int = 5):
    """Set leverage for a futures symbol."""
    try:
        sym    = symbol.replace("/", "")
        params = _sign({"symbol": sym, "leverage": leverage})
        resp   = requests.post(
            f"{EXEC_URL}/fapi/v1/leverage",
            params=params, headers=_get_headers(), timeout=10,
        )
        data = resp.json()
        print(f"[market_data] leverage set {sym} {leverage}x: {data.get('leverage', '?')}x")
    except Exception as e:
        print(f"[market_data] leverage error {symbol}: {e}")


def place_order_raw(symbol: str, side: str, quantity: float) -> dict:
    """
    Place a futures market order.
    BUY  = LONG position
    SELL = SHORT position (this works on futures, not spot)
    """
    try:
        sym   = symbol.replace("/", "")
        rules = get_lot_size_rules(symbol)
        step  = rules["step_size"]
        min_q = rules["min_qty"]
        price = get_ticker_price(symbol)

        qty = round_step_size(quantity, step)
        if qty < min_q:
            qty = min_q

        # Futures position side
        pos_side = "LONG" if side.upper() == "BUY" else "SHORT"

        import math
        if step > 0:
            decimals = max(0, int(round(-math.log10(step))))
        else:
            decimals = 2
        qty_str = f"{qty:.{decimals}f}"
        print(f"[market_data] placing {side} {qty_str} {sym} futures")

        params = _sign({
            "symbol":       sym,
            "side":         side.upper(),
            "type":         "MARKET",
            "quantity":     qty_str,
            "recvWindow":   20000,
        })
        resp = requests.post(
            f"{EXEC_URL}/fapi/v1/order",
            params=params, headers=_get_headers(), timeout=15,
        )
        data = resp.json()

        if "code" in data and data["code"] < 0:
            print(f"[market_data] order error: {data}")
            return {"success": False, "error": data.get("msg", str(data))}

        avg_price = float(data.get("avgPrice", 0)) or price
        qty_filled = float(data.get("executedQty", qty))

        return {
            "success":    True,
            "order_id":   str(data.get("orderId", "")),
            "fill_price": avg_price,
            "qty_filled": qty_filled,
            "raw":        data,
        }
    except Exception as e:
        print(f"[market_data] place_order_raw error: {e}")
        return {"success": False, "error": str(e)}


def close_futures_position(symbol: str, side: str, quantity: float) -> dict:
    """
    Close a futures position by placing the opposite side order.
    If we BOUGHT (LONG) → close with SELL
    If we SOLD  (SHORT) → close with BUY
    """
    close_side = "SELL" if side == "BUY" else "BUY"
    return place_order_raw(symbol, close_side, quantity)


# ─── TECHNICAL INDICATORS ─────────────────────────────────────────────────────

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
        return {"error": f"Insufficient data for {symbol}"}
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