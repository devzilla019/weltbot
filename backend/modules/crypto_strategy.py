"""
backend/modules/crypto_strategy.py
Applies the SAME 3-layer strategy to crypto (Binance) that forex uses:

  LAYER 1 — Kronos AI directional bias (H1, 400 candles)
  LAYER 2 — CRT setup: previous-day high/low sweep + close back inside
  LAYER 3 — SMC entry: order block + FVG + liquidity grab on 5m

This module is asset-agnostic: it reuses kronos_engine, crt_detector and
forex_signal_engine, feeding them Binance OHLCV instead of broker candles.
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

# Crypto CRT timeframes (Binance intervals)
CRYPTO_CRT_TIMEFRAMES = ["1d", "4h", "1h", "15m"]


def _crypto_candles(symbol: str, timeframe: str, limit: int = 60):
    """Fetch Binance candles with a 'timestamp' column for the CRT detector."""
    from modules.market_data import fetch_ohlcv

    df = fetch_ohlcv(symbol, interval=timeframe, limit=limit)
    if df is None or df.empty:
        return None
    out = df.reset_index()
    if "timestamp" not in out.columns:
        out = out.rename(columns={out.columns[0]: "timestamp"})
    return out


def update_crypto_levels(symbol: str) -> Optional[dict]:
    """Mark the previous daily range for a crypto symbol (legacy helper)."""
    try:
        from modules.crt_detector import calculate_range

        daily = _crypto_candles(symbol, "1d", 5)
        if daily is None or len(daily) < 2:
            return None

        levels = calculate_range(symbol, daily, timeframe="1d")
        if levels:
            _crypto_levels[symbol] = levels
        return levels
    except Exception as e:
        logger.error(f"[crypto-crt] {symbol} levels error: {e}")
        return None


def scan_crypto_crt(symbol: str) -> Optional[dict]:
    """
    Scan a crypto symbol across 1d / 4h / 1h / 15m for a CRT sweep,
    validated against Kronos bias (optional — neutral mode allowed).
    """
    try:
        from modules.crt_detector import calculate_range, detect_sweep, validate_with_kronos

        bias = get_crypto_bias(symbol)
        found = []

        for tf in CRYPTO_CRT_TIMEFRAMES:
            candles = _crypto_candles(symbol, tf, 60)
            if candles is None or len(candles) < 3:
                continue

            level = calculate_range(symbol, candles, timeframe=tf)
            if not level:
                continue

            sweep = detect_sweep(symbol, candles, level["range_high"],
                                 level["range_low"], timeframe=tf)
            if sweep:
                found.append(sweep)

        if not found:
            return None

        # Prefer the highest timeframe
        found.sort(key=lambda s: CRYPTO_CRT_TIMEFRAMES.index(s["timeframe"]))

        for sweep in found:
            if not validate_with_kronos(sweep, bias):
                continue
            _crypto_setups[symbol] = sweep
            logger.info(f"[crypto-crt] {symbol} {sweep['timeframe']} SWEPT "
                        f"{sweep['sweep_type']} — {sweep['direction']} setup confirmed")
            return sweep

        return None
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
    Cascade: CRT timeframe -> confirm POI on mid TF -> SMC entry on lower TF.
    Returns a signal dict compatible with the crypto executor.
    """
    try:
        from modules.market_data import get_ticker_price
        from modules.forex_signal_engine import check_entry_condition, confirm_on_timeframe
        from modules.crt_detector import get_cascade

        setup = _crypto_setups.get(symbol)
        if not setup:
            return None

        crt_tf = setup.get("timeframe", "1d")
        cascade = get_cascade(crt_tf)
        confirm_tf = cascade["confirm"]
        entry_tf = cascade["entry"]

        # ── STEP 2: confirm a POI on the mid timeframe ────────────────────────
        poi = _crypto_confirm(symbol, setup, confirm_tf)
        if not poi:
            return None

        setup["confirm_timeframe"] = confirm_tf
        setup["entry_timeframe"] = entry_tf
        setup["poi"] = poi

        # ── STEP 3: SMC entry on the lower timeframe ──────────────────────────
        price = get_ticker_price(symbol)
        if price <= 0:
            return None

        df_entry = _crypto_candles(symbol, entry_tf, 60)
        if df_entry is None or len(df_entry) < 20:
            return None

        signal = check_entry_condition(setup, price, df_entry)
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


def _crypto_confirm(symbol: str, setup: dict, confirm_tf: str):
    """Find a POI on the confirmation timeframe for a crypto symbol."""
    try:
        from modules.forex_signal_engine import find_poi, calculate_atr

        df = _crypto_candles(symbol, confirm_tf, 60)
        if df is None or len(df) < 20:
            return None

        price = float(df["close"].iloc[-1])
        atr = calculate_atr(df)
        poi = find_poi(df, setup["direction"], price, atr)
        if poi:
            logger.info(f"[crypto-cascade] {symbol} POI on {confirm_tf}: {poi['kind']} "
                        f"(CRT {setup.get('timeframe')})")
        return poi
    except Exception as e:
        logger.error(f"[crypto-cascade] {symbol} confirm error: {e}")
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
