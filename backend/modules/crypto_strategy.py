"""
backend/modules/crypto_strategy.py
Applies the SAME 3-layer strategy to crypto (Binance) that forex uses:

  LAYER 1 — Kronos AI directional bias (H1, 400 candles)
  LAYER 2 — CRT setup: previous-day high/low sweep + close back inside
  LAYER 3 — SMC entry: order block + FVG + liquidity grab on 5m

This module is asset-agnostic: it reuses kronos_engine, crt_detector and
forex_signal_engine, feeding them Binance OHLCV instead of MetaApi candles.
"""
import logging
from datetime import datetime, timedelta
from typing import Optional, Dict

import pandas as pd

logger = logging.getLogger(__name__)

# In-memory state (mirrors the forex bot's dicts)
_crypto_bias: Dict[str, dict] = {}
_crypto_levels: Dict[str, dict] = {}
_crypto_setups: Dict[str, dict] = {}


# ── helpers ───────────────────────────────────────────────────────────────────

def _to_kronos_df(df: pd.DataFrame) -> Optional[pd.DataFrame]:
    """Convert Binance OHLCV (DatetimeIndex) into Kronos format (timestamp column)."""
    if df is None or df.empty:
        return None
    out = df.reset_index()
    # Binance index is named 'timestamp' (datetime) — normalise the column name
    if "timestamp" not in out.columns:
        out = out.rename(columns={out.columns[0]: "timestamp"})
    out["timestamp"] = pd.to_datetime(out["timestamp"])
    for col in ("open", "high", "low", "close"):
        if col not in out.columns:
            return None
    if "volume" not in out.columns:
        out["volume"] = 0.0
    return out[["timestamp", "open", "high", "low", "close", "volume"]]


def _daily_from_h1(h1: pd.DataFrame) -> Optional[pd.DataFrame]:
    """Aggregate H1 candles into daily candles for PDH/PDL."""
    if h1 is None or h1.empty:
        return None
    df = h1.copy()
    if not isinstance(df.index, pd.DatetimeIndex):
        if "timestamp" in df.columns:
            df = df.set_index("timestamp")
        else:
            return None
    daily = df.resample("1D").agg({
        "open": "first", "high": "max", "low": "min",
        "close": "last", "volume": "sum",
    }).dropna()
    daily = daily.reset_index()
    if "index" in daily.columns:
        daily = daily.rename(columns={"index": "timestamp"})
    return daily


# ── LAYER 1: Kronos bias ──────────────────────────────────────────────────────

def update_crypto_bias(symbol: str) -> Optional[dict]:
    """Fetch H1 candles from Binance and compute Kronos bias."""
    try:
        from modules.market_data import fetch_ohlcv
        from modules.kronos_engine import predict_bias, is_kronos_available

        if not is_kronos_available():
            return None

        h1 = fetch_ohlcv(symbol, interval="1h", limit=400)
        kdf = _to_kronos_df(h1)
        if kdf is None or len(kdf) < 400:
            logger.debug(f"[crypto-kronos] {symbol} insufficient H1 data")
            return None

        bias = predict_bias(symbol, kdf)
        if bias:
            _crypto_bias[symbol] = bias
            logger.info(f"[crypto-kronos] {symbol} bias={bias['bias']} "
                        f"change={bias['predicted_change_pct']}%")
        return bias
    except Exception as e:
        logger.error(f"[crypto-kronos] {symbol} error: {e}")
        return None


def get_crypto_bias(symbol: str) -> Optional[dict]:
    return _crypto_bias.get(symbol)


def get_all_crypto_biases() -> Dict[str, dict]:
    return _crypto_bias.copy()


# ── LAYER 2: CRT setup ────────────────────────────────────────────────────────

def update_crypto_levels(symbol: str) -> Optional[dict]:
    """Compute previous-day high/low for a crypto symbol."""
    try:
        from modules.market_data import fetch_ohlcv
        from modules.crt_detector import calculate_pdh_pdl

        h1 = fetch_ohlcv(symbol, interval="1h", limit=200)
        daily = _daily_from_h1(h1)
        if daily is None or len(daily) < 2:
            return None

        levels = calculate_pdh_pdl(symbol, daily)
        if levels:
            _crypto_levels[symbol] = levels
        return levels
    except Exception as e:
        logger.error(f"[crypto-crt] {symbol} levels error: {e}")
        return None


def scan_crypto_crt(symbol: str) -> Optional[dict]:
    """Detect a CRT sweep on H1 and validate against Kronos bias."""
    try:
        from modules.market_data import fetch_ohlcv
        from modules.crt_detector import detect_sweep, validate_with_kronos

        levels = _crypto_levels.get(symbol) or update_crypto_levels(symbol)
        if not levels:
            return None

        h1 = fetch_ohlcv(symbol, interval="1h", limit=10)
        if h1 is None or len(h1) < 3:
            return None

        # detect_sweep expects a 'timestamp' column
        h1r = h1.reset_index()
        if "timestamp" not in h1r.columns:
            h1r = h1r.rename(columns={h1r.columns[0]: "timestamp"})

        sweep = detect_sweep(symbol, h1r, levels["pdh"], levels["pdl"])
        if not sweep:
            return None

        bias = get_crypto_bias(symbol)
        if not validate_with_kronos(sweep, bias):
            return None

        _crypto_setups[symbol] = sweep
        logger.info(f"[crypto-crt] {symbol} SWEPT {sweep['sweep_type']} — "
                    f"{sweep['direction']} setup confirmed")
        return sweep
    except Exception as e:
        logger.error(f"[crypto-crt] {symbol} scan error: {e}")
        return None


def get_crypto_setups() -> Dict[str, dict]:
    return _crypto_setups.copy()


def clear_crypto_setup(symbol: str):
    _crypto_setups.pop(symbol, None)


# ── LAYER 3: SMC entry ────────────────────────────────────────────────────────

def check_crypto_entry(symbol: str) -> Optional[dict]:
    """
    For an active CRT setup, look for an SMC entry on 5m:
    order block + FVG (+ optional liquidity grab).
    Returns a signal dict compatible with the crypto executor.
    """
    try:
        from modules.market_data import fetch_ohlcv, get_ticker_price
        from modules.forex_signal_engine import check_entry_condition

        setup = _crypto_setups.get(symbol)
        if not setup:
            return None

        price = get_ticker_price(symbol)
        if price <= 0:
            return None

        df5 = fetch_ohlcv(symbol, interval="5m", limit=60)
        if df5 is None or len(df5) < 20:
            return None

        df5r = df5.reset_index()
        if "timestamp" not in df5r.columns:
            df5r = df5r.rename(columns={df5r.columns[0]: "timestamp"})

        signal = check_entry_condition(setup, price, df5r)
        if not signal:
            return None

        # Add Kronos confidence boost
        bias = get_crypto_bias(symbol)
        if bias:
            signal["confidence"] = min(signal["confidence"] + bias.get("confidence_boost", 0), 99)
            signal["kronos_bias"] = bias.get("bias", "NEUTRAL")

        signal["asset_class"] = "crypto"
        return signal
    except Exception as e:
        logger.error(f"[crypto-smc] {symbol} entry error: {e}")
        return None


def update_all_crypto_bias(symbols) -> int:
    """Update Kronos bias for a list of crypto symbols. Returns count updated."""
    n = 0
    for sym in symbols:
        if update_crypto_bias(sym):
            n += 1
    return n


def update_all_crypto_levels(symbols) -> int:
    """Update PDH/PDL for a list of crypto symbols. Returns count updated."""
    n = 0
    for sym in symbols:
        if update_crypto_levels(sym):
            n += 1
    return n
