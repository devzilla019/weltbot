import yfinance as yf
import pandas as pd
import numpy as np

def fetch_ohlcv(symbol):
    try:
        ticker = yf.Ticker(symbol)
        df = ticker.history(period="90d", interval="1d", auto_adjust=True)
        df.dropna(inplace=True)
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        return df
    except Exception as e:
        print(f"fetch error {symbol}: {e}")
        return pd.DataFrame()cd ..

def compute_rsi(close, period=14):
    delta = close.diff()
    gain  = delta.clip(lower=0).rolling(period).mean()
    loss  = (-delta.clip(upper=0)).rolling(period).mean()
    rs    = gain / loss.replace(0, np.nan)
    rsi   = 100 - (100 / (1 + rs))
    return round(float(rsi.iloc[-1]), 2)

def score_rsi(rsi):
    if rsi < 30:
        return 1.0
    if rsi > 70:
        return -1.0
    return round((50 - rsi) / 20.0, 4)

def compute_macd(close):
    ema12  = close.ewm(span=12, adjust=False).mean()
    ema26  = close.ewm(span=26, adjust=False).mean()
    macd   = ema12 - ema26
    signal = macd.ewm(span=9, adjust=False).mean()
    hist   = macd - signal
    return {
        "macd":      round(float(macd.iloc[-1]), 6),
        "signal":    round(float(signal.iloc[-1]), 6),
        "histogram": round(float(hist.iloc[-1]), 6),
    }

def score_macd(histogram, price):
    if price == 0:
        return 0.0
    return round(max(-1.0, min(1.0, (histogram / price) * 1000)), 4)

def compute_atr(df, period=14):
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    high  = df["High"].squeeze()
    low   = df["Low"].squeeze()
    close = df["Close"].squeeze()
    prev  = close.shift(1)
    tr    = pd.concat([
        (high - low),
        (high - prev).abs(),
        (low  - prev).abs()
    ], axis=1).max(axis=1)
    return round(float(tr.rolling(period).mean().iloc[-1]), 6)

def compute_ema_trend(close, fast=10, slow=30):
    ema_fast  = close.ewm(span=fast, adjust=False).mean()
    ema_slow  = close.ewm(span=slow, adjust=False).mean()
    delta_pct = float(
        (ema_fast.iloc[-1] - ema_slow.iloc[-1]) / ema_slow.iloc[-1]
    )
    if delta_pct > 0.005:
        label = "bullish"
    elif delta_pct < -0.005:
        label = "bearish"
    else:
        label = "neutral"
    score = round(max(-1.0, min(1.0, delta_pct * 20)), 4)
    return {"label": label, "score": score, "delta_pct": round(delta_pct, 6)}

def detect_volume_anomaly(volume, close, lookback=20):
    avg       = float(volume.rolling(lookback).mean().iloc[-1])
    ratio     = float(volume.iloc[-1]) / avg if avg > 0 else 1.0
    direction = 1 if float(close.iloc[-1]) >= float(close.iloc[-2]) else -1
    spike     = ratio > 1.8
    score     = round(min(1.0, (ratio - 1.0) / 2.0) * direction, 4) if spike else 0.0
    return {"spike": spike, "ratio": round(ratio, 2), "score": score}

def get_market_snapshot(symbol):
    df = fetch_ohlcv(symbol)
    if df.empty or len(df) < 30:
        return {"error": f"Insufficient data for {symbol}"}
    close    = df["Close"].squeeze()
    volume   = df["Volume"].squeeze()
    price    = round(float(close.iloc[-1]), 6)
    prev     = round(float(close.iloc[-2]), 6)
    rsi_val  = compute_rsi(close)
    macd_val = compute_macd(close)
    atr_val  = compute_atr(df)
    trend    = compute_ema_trend(close)
    vol_anom = detect_volume_anomaly(volume, close)
    return {
        "symbol":     symbol,
        "price":      price,
        "change_pct": round((price / prev - 1) * 100, 3),
        "volume":     vol_anom,
        "atr":        atr_val,
        "rsi":        rsi_val,
        "rsi_score":  score_rsi(rsi_val),
        "macd":       macd_val,
        "macd_score": score_macd(macd_val["histogram"], price),
        "trend":      trend,
    }