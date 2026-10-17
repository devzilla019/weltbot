"""
backend/modules/candle_provider.py
One seam for "give me candles for this symbol, whichever venue it trades on".

Before this module existed every strategy talked to a venue directly, so the
Silver Bullet detector could only ever run on Capital.com instruments — BTC and
ETH are Binance symbols and there is no Capital.com epic for them, which made
the strategy unreachable for them.

This module only routes. It does NOT re-implement fetching, caching, pacing or
authentication: Capital.com candles still come from `market_data_forex`, and
Binance candles still come from `market_data`. That matters because those two
modules carry the rate-limit handling this project already depends on.

Frame contract (all providers return this or None):
  columns  : timestamp, open, high, low, close, volume
  order    : ascending by timestamp
  attrs    : volume_source -> "tick" | "exchange" | "proxy" | "none"

  "tick"     Capital.com `lastTradedVolume` — the provider's own cleared
             contracts. A proxy for true market volume, not true volume.
  "exchange" Binance real traded base-asset volume.
  "proxy"    A venue that does not report volume at all. The candle provider
             substitutes the candle's price range so a distribution can still
             be built (this degenerates towards a TPO-style profile).
  "none"     No usable volume information whatsoever.

Callers that gate a decision on volume MUST read `attrs["volume_source"]`
rather than assuming the `volume` column is meaningful.
"""
import logging
from typing import Optional, Tuple

import pandas as pd

logger = logging.getLogger(__name__)

# Venue identifiers
CAPITAL = "capital"
BINANCE = "binance"

# Quote assets that identify a Binance symbol. These are exchange symbols, not
# broker epics, so they must never be routed to Capital.com.
_BINANCE_QUOTES = ("USDT", "USDC", "BUSD", "FDUSD", "BTC", "ETH", "BNB")

# Capital.com metals, which have no quote asset and would otherwise be
# ambiguous with a crypto base symbol.
_CAPITAL_METALS = ("XAU", "XAG", "XPT", "XPD")


def normalize_symbol(symbol: str) -> str:
    """'BTC/USDT', 'btc-usdt' and 'BTCUSDT' all become 'BTCUSDT'."""
    if not symbol:
        return ""
    return symbol.replace("/", "").replace("-", "").replace("_", "").strip().upper()


def provider_for(symbol: str) -> str:
    """
    Which venue serves `symbol`.

    Metals are resolved BEFORE the quote-asset test so that XAUUSD (which ends
    in "USD") is never mistaken for a crypto pair.
    """
    bare = normalize_symbol(symbol)
    if bare.startswith(_CAPITAL_METALS):
        return CAPITAL
    for quote in _BINANCE_QUOTES:
        if bare.endswith(quote):
            return BINANCE
    return CAPITAL


def is_binance(symbol: str) -> bool:
    return provider_for(symbol) == BINANCE


def _binance_symbol(symbol: str) -> str:
    """Binance expects 'BTCUSDT' with no separator."""
    return normalize_symbol(symbol)


def _tag_volume_source(df: Optional[pd.DataFrame], source: str) -> Optional[pd.DataFrame]:
    if df is None:
        return None
    # A caller may hand back a frame with no volume at all; labelling it as a
    # real volume source would silently let a volume gate pass.
    if "volume" not in df.columns:
        source = "none"
    df.attrs["volume_source"] = source
    return df


def get_candles(symbol: str, timeframe: str = "1h",
                limit: int = 400) -> Optional[pd.DataFrame]:
    """
    OHLCV candles for `symbol`, from whichever venue serves it.

    Returns None when the venue is unreachable or has no data, matching the
    existing Capital.com contract, so callers keep their current None-checks.
    """
    if not symbol:
        return None

    if provider_for(symbol) == BINANCE:
        from modules.market_data import fetch_ohlcv

        try:
            df = fetch_ohlcv(_binance_symbol(symbol), interval=timeframe, limit=int(limit))
        except Exception as e:
            logger.error(f"[candles] binance fetch failed for {symbol}: {e}")
            return None

        if df is None or len(df) == 0:
            return None

        df = df.reset_index()
        if "timestamp" not in df.columns:
            df = df.rename(columns={df.columns[0]: "timestamp"})

        # Binance reports real exchange volume. The CoinGecko fallback inside
        # market_data fabricates a constant, which is not volume at all — mark
        # it as a proxy so a profile built from it can be rejected downstream.
        source = "proxy" if _came_from_coingecko(df) else "exchange"
        return _normalize(df, source)

    from modules.market_data_forex import get_candles as fx_get_candles

    try:
        df = fx_get_candles(symbol, timeframe=timeframe, limit=int(limit))
    except Exception as e:
        logger.error(f"[candles] capital fetch failed for {symbol}: {e}")
        return None

    if df is None or len(df) == 0:
        return None

    source = df.attrs.get("volume_source", "none")
    return _normalize(df, source)


def _came_from_coingecko(df: pd.DataFrame) -> bool:
    """
    Detect the CoinGecko fallback.

    market_data stamps a constant 1000000.0 volume on every candle when every
    Binance mirror failed. A constant volume series carries no distributional
    information, so it must not be presented as exchange volume.
    """
    try:
        vol = pd.to_numeric(df["volume"], errors="coerce").dropna()
        if len(vol) < 5:
            return True
        return bool(vol.nunique() == 1)
    except Exception:
        return True


def _normalize(df: pd.DataFrame, volume_source: str) -> Optional[pd.DataFrame]:
    """
    Coerce any provider frame into the shared contract.

    Missing OHLC, unparseable timestamps and duplicated timestamps are all
    dropped rather than raising, because a single malformed candle should
    degrade the profile rather than take the scanner down.
    """
    try:
        out = df.copy()

        for col in ("open", "high", "low", "close"):
            if col not in out.columns:
                logger.warning(f"[candles] frame missing '{col}' — cannot normalize")
                return None
            out[col] = pd.to_numeric(out[col], errors="coerce")

        if "volume" in out.columns:
            out["volume"] = pd.to_numeric(out["volume"], errors="coerce").fillna(0.0)
        else:
            out["volume"] = 0.0
            volume_source = "none"

        if "timestamp" in out.columns:
            out["timestamp"] = pd.to_datetime(out["timestamp"], errors="coerce")
            out = out.dropna(subset=["timestamp"])
            out = out.sort_values("timestamp")
            out = out.drop_duplicates(subset=["timestamp"], keep="last")

        out = out.dropna(subset=["open", "high", "low", "close"]).reset_index(drop=True)

        if out.empty:
            return None

        cols = ["timestamp", "open", "high", "low", "close", "volume"] \
            if "timestamp" in out.columns else \
            ["open", "high", "low", "close", "volume"]
        out = out[cols]

        out.attrs["volume_source"] = volume_source
        return out

    except Exception as e:
        logger.error(f"[candles] normalize error: {e}")
        return None


def get_candles_normalized(symbol: str, timeframe: str = "1h",
                           limit: int = 400) -> Tuple[Optional[pd.DataFrame], str]:
    """
    Convenience wrapper returning (frame, volume_source).

    The source is returned alongside the frame because the two must be judged
    together: a perfectly valid frame whose volume is a range proxy is still
    unusable for a volume-based entry gate.
    """
    df = get_candles(symbol, timeframe, limit)
    if df is None:
        return None, "none"
    return df, df.attrs.get("volume_source", "none")


def get_current_price(symbol: str) -> float:
    """Last traded price for `symbol`, or 0.0 when unavailable."""
    if not symbol:
        return 0.0

    try:
        if provider_for(symbol) == BINANCE:
            from modules.market_data import get_ticker_price
            return float(get_ticker_price(_binance_symbol(symbol)) or 0.0)

        from modules.market_data_forex import get_current_price as fx_price
        return float(fx_price(symbol) or 0.0)
    except Exception as e:
        logger.error(f"[candles] price failed for {symbol}: {e}")
        return 0.0
