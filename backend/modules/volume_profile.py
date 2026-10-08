"""
backend/modules/volume_profile.py
Volume Profile — POC / VAH / VAL.

Builds a price histogram from candle data and derives:
  POC = price bin with the highest accumulated volume
  VAH = upper bound of the value area (70% of total volume)
  VAL = lower bound of the value area

Capital.com supplies `tickVolume` per candle, which is a proxy for traded
volume rather than true volume. Each candle's tick volume is therefore
distributed across the price range it covers, so wide candles contribute
thinly and narrow candles contribute densely. When tick volume is missing
entirely the distribution falls back to range coverage, which still yields
a usable profile (it degenerates towards a TPO-style profile).
"""
import logging
from typing import Optional, Dict

import pandas as pd

logger = logging.getLogger(__name__)

# Fraction of total volume the value area must contain
VALUE_AREA_PCT = 0.70

# Default histogram resolution
DEFAULT_BINS = 50


def calculate_session_volume_profile(candles_df: pd.DataFrame,
                                     num_bins: int = DEFAULT_BINS) -> Optional[Dict]:
    """
    Calculate POC, VAH and VAL from candle data.

    Args:
        candles_df: DataFrame with high, low, close columns; `volume` is
                    used when present.
        num_bins:   histogram resolution.

    Returns:
        {poc, vah, val, price_min, price_max, total_volume, bins_used}
        or None when there is not enough data.
    """
    try:
        if candles_df is None or len(candles_df) < 10:
            return None

        for col in ("high", "low"):
            if col not in candles_df.columns:
                logger.warning(f"[vp] missing '{col}' column — cannot build profile")
                return None

        highs = candles_df["high"].astype(float)
        lows = candles_df["low"].astype(float)

        price_min = float(lows.min())
        price_max = float(highs.max())
        price_range = price_max - price_min
        if price_range <= 0:
            return None

        bin_size = price_range / num_bins

        has_volume = "volume" in candles_df.columns and \
            candles_df["volume"].astype(float).sum() > 0

        bins = {}
        total_volume = 0.0

        for _, candle in candles_df.iterrows():
            c_high = float(candle["high"])
            c_low = float(candle["low"])
            candle_range = max(c_high - c_low, bin_size)

            if has_volume:
                vol = float(candle.get("volume") or 0.0)
            else:
                # No usable volume — weight by range so the profile still
                # reflects where price spent time.
                vol = candle_range

            if vol <= 0:
                continue

            vol_per_price = vol / candle_range
            total_volume += vol

            price = c_low
            while price <= c_high:
                bin_idx = int((price - price_min) / bin_size)
                bin_idx = max(0, min(bin_idx, num_bins - 1))
                bins[bin_idx] = bins.get(bin_idx, 0.0) + vol_per_price * bin_size
                price += bin_size

        if not bins:
            return None

        # ── POC ──────────────────────────────────────────────────────────────
        poc_bin = max(bins, key=bins.get)
        poc = price_min + (poc_bin * bin_size) + (bin_size / 2)

        # ── Value area: expand outward from the POC until 70% is covered ─────
        target = sum(bins.values()) * VALUE_AREA_PCT
        sorted_bins = sorted(bins.items(), key=lambda x: x[1], reverse=True)

        va_bins = []
        accumulated = 0.0
        for bin_idx, vol in sorted_bins:
            va_bins.append(bin_idx)
            accumulated += vol
            if accumulated >= target:
                break

        vah = price_min + (max(va_bins) * bin_size) + bin_size
        val = price_min + (min(va_bins) * bin_size)

        return {
            "poc": round(poc, 5),
            "vah": round(vah, 5),
            "val": round(val, 5),
            "price_min": round(price_min, 5),
            "price_max": round(price_max, 5),
            "total_volume": round(total_volume, 2),
            "bins_used": len(bins),
            "volume_source": "tick" if has_volume else "range",
        }

    except Exception as e:
        logger.error(f"[vp] volume profile error: {e}")
        return None


def classify_price_position(price: float, vp: Dict) -> str:
    """
    Where price sits relative to the value area.

    Returns: 'ABOVE_VALUE' | 'BELOW_VALUE' | 'INSIDE_VALUE' | 'AT_POC' | 'UNKNOWN'
    """
    try:
        if not vp or price is None:
            return "UNKNOWN"

        poc, vah, val = vp.get("poc"), vp.get("vah"), vp.get("val")
        if poc is None or vah is None or val is None:
            return "UNKNOWN"

        # "Near POC" = within 0.1% of it
        if poc and abs(price - poc) / poc < 0.001:
            return "AT_POC"
        if price > vah:
            return "ABOVE_VALUE"
        if price < val:
            return "BELOW_VALUE"
        return "INSIDE_VALUE"

    except Exception as e:
        logger.error(f"[vp] classify error: {e}")
        return "UNKNOWN"


def check_fvg_confluence(fvg: Dict, vp: Dict) -> Dict:
    """
    Grade a fair value gap against the volume profile.

    Returns {grade, size_multiplier} where grade is one of
    POC_OVERLAP | VAH_CONFLUENCE | VAL_CONFLUENCE | NO_CONFLUENCE.
    """
    try:
        if not fvg or not vp:
            return {"grade": "NO_CONFLUENCE", "size_multiplier": 0.5}

        fvg_high = float(fvg.get("fvg_high") or 0.0)
        fvg_low = float(fvg.get("fvg_low") or 0.0)
        if fvg_high <= 0 or fvg_low <= 0:
            return {"grade": "NO_CONFLUENCE", "size_multiplier": 0.5}

        midpoint = (fvg_high + fvg_low) / 2.0

        poc = vp.get("poc")
        vah = vp.get("vah")
        val = vp.get("val")

        # Highest grade — the gap straddles the point of control
        if poc is not None and fvg_low <= poc <= fvg_high:
            return {"grade": "POC_OVERLAP", "size_multiplier": 1.0}

        if vah is not None and vah and abs(midpoint - vah) / vah < 0.001:
            return {"grade": "VAH_CONFLUENCE", "size_multiplier": 1.0}

        if val is not None and val and abs(midpoint - val) / val < 0.001:
            return {"grade": "VAL_CONFLUENCE", "size_multiplier": 1.0}

        return {"grade": "NO_CONFLUENCE", "size_multiplier": 0.5}

    except Exception as e:
        logger.error(f"[vp] confluence error: {e}")
        return {"grade": "NO_CONFLUENCE", "size_multiplier": 0.5}
