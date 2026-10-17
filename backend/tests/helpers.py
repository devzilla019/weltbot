"""
backend/tests/helpers.py
Synthetic candle builders shared by the Phase 2 tests.

Everything here is deterministic: the volume profile and structure tests assert
exact numbers, so a random fixture would make them flaky rather than thorough.
"""
from typing import Optional

import pandas as pd


def candles(rows, with_timestamp: bool = True,
            start: str = "2026-10-14 00:00",
            freq: str = "1h",
            volume_source: Optional[str] = None) -> pd.DataFrame:
    """
    Build an OHLCV frame from (open, high, low, close[, volume]) tuples.

    `volume` may be omitted from a row, in which case the column is left absent
    so a caller can exercise the no-volume path.
    """
    records = []
    for row in rows:
        rec = {
            "open": float(row[0]),
            "high": float(row[1]),
            "low": float(row[2]),
            "close": float(row[3]),
        }
        if len(row) > 4 and row[4] is not None:
            rec["volume"] = float(row[4])
        records.append(rec)

    df = pd.DataFrame(records)
    if with_timestamp:
        df.insert(0, "timestamp",
                  pd.date_range(start, periods=len(df), freq=freq, tz="UTC"))
    if volume_source is not None:
        df.attrs["volume_source"] = volume_source
    return df


def flat_candles(low: float, high: float, count: int,
                 volume: float = 100.0,
                 with_timestamp: bool = True,
                 volume_source: Optional[str] = None) -> pd.DataFrame:
    """`count` identical candles all spanning [low, high]."""
    return candles(
        [(low, high, low, high, volume)] * count,
        with_timestamp=with_timestamp,
        volume_source=volume_source,
    )


def uniform_profile(low: float = 100.0, high: float = 110.0,
                    count: int = 60, volume: float = 100.0,
                    with_timestamp: bool = True,
                    volume_source: Optional[str] = None) -> pd.DataFrame:
    """
    Candles whose ranges tile [low, high] evenly.

    Because every candle carries the same volume and the same range, the
    resulting histogram is flat, which makes the POC and the value-area extent
    analytically predictable.
    """
    rows = []
    span = (high - low) / count
    for i in range(count):
        lo = low + i * span
        rows.append((lo, lo + span, lo, lo + span, volume))
    return candles(rows, with_timestamp=with_timestamp,
                   volume_source=volume_source)


def staircase(start: float, step: float, count: int,
              up: bool = True, volume: float = 100.0,
              with_timestamp: bool = True,
              volume_source: Optional[str] = None) -> pd.DataFrame:
    """
    A cleanly trending series of candles, used for the H4 structure tests.

    Each candle's body closes where the next opens, and the wicks extend only a
    fraction of the step, so highs and lows march monotonically and every swing
    is unambiguous.
    """
    rows = []
    price = start
    for _ in range(count):
        nxt = price + (step if up else -step)
        hi = max(price, nxt) + abs(step) * 0.1
        lo = min(price, nxt) - abs(step) * 0.1
        rows.append((price, hi, lo, nxt, volume))
        price = nxt
    return candles(rows, with_timestamp=with_timestamp,
                   volume_source=volume_source)


def contiguous_peaked(count: int = 40, low: float = 100.0,
                      step: float = 0.05, peak_multiplier: float = 4.0,
                      volume_source: Optional[str] = None) -> pd.DataFrame:
    """
    Candles that tile a range WITHOUT gaps, with volume concentrated in the middle.

    Two properties matter and a naive fixture gets one of them wrong:

      * CONTIGUOUS — each candle's range abuts the next, so no price bin between
        them is empty. A histogram with empty bins cannot reach the 70% value
        area without spanning price that never traded, so the profile is
        correctly reported invalid.
      * PEAKED — the volume varies, so there is a real point of control. A ramp
        of identical candles produces a flat histogram, which has no peak and is
        also reported invalid.

    A fixture that is contiguous but flat, or peaked but clustered, exercises a
    rejection path rather than the profile logic a test usually means to cover.
    """
    peak_at = count // 2
    rows = []
    for i in range(count):
        base = low + i * step
        weight = peak_multiplier - abs(i - peak_at) * (peak_multiplier - 1) / max(peak_at, 1)
        rows.append((base, base + step, base, base + step, round(max(weight, 1.0) * 100, 2)))
    return candles(rows, volume_source=volume_source)


def contiguous_range_weighted(count: int = 40, low: float = 100.0,
                              step: float = 0.05,
                              peak_multiplier: float = 4.0) -> pd.DataFrame:
    """
    The same shape with NO volume column, so the profile falls back to range weighting.

    That fallback weights each candle by its own high-low span, so a peaked
    profile requires the SPANS to vary — identical spans produce a flat
    histogram. This builds wide candles in the middle and narrow ones at the
    ends, which is what a quiet-then-busy day actually looks like.
    """
    peak_at = count // 2
    rows = []
    for i in range(count):
        base = low + i * step
        span = step * (peak_multiplier - abs(i - peak_at) * (peak_multiplier - 1) / max(peak_at, 1))
        rows.append((base, base + max(span, step), base, base + max(span, step)))
    # No volume in the row tuples, so `candles()` leaves the column absent and
    # the profile takes the range-weighting fallback.
    return candles(rows)


def bull_sweep_sequence(swing_low: float = 1.1000) -> list:
    """
    The nine-candle bullish Silver Bullet sequence, as (o, h, l, c) tuples.

    Every stage is unambiguous and independently checkable, and the numbers are
    chosen so each threshold is genuinely cleared rather than nearly cleared:

        idx 0-3  base candles. idx 1's high 1.1060 is the pre-sweep swing high,
                 and there are four of them because the MSS detector needs
                 pre-sweep history to find the level it must break
        idx 4    the SWEEP: low 1.0990 wicks below swing_low 1.1000 and closes
                 back at 1.1040, with a body worth 45% of the range (the filter
                 needs 40%)
        idx 5    the MSS candle: closes 1.1075, above the 1.1060 swing high,
                 one candle after the sweep
        idx 6-8  displacement leaving a bullish FVG between idx 6's high
                 (1.1080) and idx 8's low (1.1088)

    The gap comes out at [1.1080, 1.1088], which is what the VP fixtures below
    are aligned to.
    """
    return [
        (1.1045, 1.1055, 1.1040, 1.1050),  # 0
        (1.1050, 1.1060, 1.1045, 1.1055),  # 1  pre-sweep swing high = 1.1060
        (1.1055, 1.1058, 1.1048, 1.1052),  # 2
        (1.1052, 1.1056, 1.1046, 1.1050),  # 3
        (1.1015, 1.1045, 1.0990, 1.1040),  # 4  SWEEP: wick 1.0990, close 1.1040
        (1.1040, 1.1080, 1.1038, 1.1075),  # 5  MSS: close 1.1075 > 1.1060
        (1.1075, 1.1092, 1.1070, 1.1090),  # 6  FVG candle 1
        (1.1090, 1.1120, 1.1088, 1.1118),  # 7  displacement
        (1.1118, 1.1130, 1.1105, 1.1125),  # 8  FVG candle 3
    ]


def bear_sweep_sequence(swing_high: float = 1.2000) -> list:
    """The bearish mirror of `bull_sweep_sequence`."""
    return [
        (1.1960, 1.1965, 1.1945, 1.1950),  # 0
        (1.1950, 1.1955, 1.1940, 1.1945),  # 1  pre-sweep swing low = 1.1940
        (1.1945, 1.1952, 1.1942, 1.1948),  # 2
        (1.1948, 1.1954, 1.1944, 1.1950),  # 3
        (1.1985, 1.2010, 1.1955, 1.1960),  # 4  SWEEP: wick 1.2010, close 1.1960
        (1.1960, 1.1962, 1.1920, 1.1925),  # 5  MSS: close 1.1925 < 1.1940
        (1.1925, 1.1930, 1.1908, 1.1910),  # 6
        (1.1910, 1.1912, 1.1880, 1.1882),  # 7  displacement
        (1.1882, 1.1895, 1.1870, 1.1880),  # 8
    ]


def silver_session_levels(swing_low: float = 1.1000,
                          swing_high: float = 1.2000) -> dict:
    """A pre-session liquidity record in the shape `mark_session_liquidity` writes."""
    return {
        "symbol": "EURUSD",
        "session": "LONDON",
        "swing_high": swing_high,
        "swing_low": swing_low,
        "range": round(swing_high - swing_low, 5),
        "date": "2026-10-15",
        "marked_at": "2026-10-15T07:59:00",
        "source_candles": 5,
    }


def silver_bias(h4_bias: str = "BULLISH", strength: int = 3,
                price_position: str = "ABOVE_VALUE",
                vp_levels: Optional[dict] = None,
                vp_gateable: bool = True) -> dict:
    """A daily-bias record in the shape Phase 2's `calculate_daily_bias` writes."""
    return {
        "symbol": "EURUSD",
        "h4_bias": h4_bias,
        "strength": strength,
        "vp_levels": vp_levels,
        "vp_levels_valid": bool(vp_levels and vp_levels.get("valid")),
        "vp_levels_trusted": bool(vp_levels and vp_levels.get("source_trusted")),
        "price_position": price_position,
        "vp_gateable": vp_gateable,
        "vp_gate_reason": "ok" if vp_gateable else "volume source is a proxy",
        "session_date": "2026-10-15",
    }


def trusted_vp(poc: float = 1.1084, vah: float = 1.1150,
               val: float = 1.1050) -> dict:
    """
    A gateable profile whose value area brackets the bullish FVG
    (1.1080-1.1088) and whose POC sits inside it, so the confluence grade is
    POC_OVERLAP and the score clears the 88 floor.
    """
    return {
        "poc": poc, "vah": vah, "val": val,
        "price_min": val, "price_max": vah,
        "total_volume": 1000.0, "bins_used": 40, "bin_size": 0.001,
        "value_area_pct": 0.70, "value_area_volume": 700.0,
        "value_area_share": 0.72,
        "volume_source": "exchange",
        "source_trusted": True,
        "valid": True,
        "warning": None,
    }


def trusted_vp_bearish(poc: float = 1.1916, vah: float = 1.1950,
                       val: float = 1.1880) -> dict:
    """The bearish mirror of `trusted_vp`, aligned to the FVG 1.1912-1.1920."""
    return trusted_vp(poc=poc, vah=vah, val=val)


def silver_entry_frame(sequence=None, filler: int = 20) -> pd.DataFrame:
    """
    A frame long enough to size a stop from, ending with the sweep sequence.

    ATR needs `period + 1` (15) candles, and the entry path refuses to trade
    without one. The sequence alone is only 9 bars, so quiet filler is prepended
    — prepended rather than appended because the sweep detector scans the newest
    candles and an appended bar would be scanned first.
    """
    if sequence is None:
        sequence = bull_sweep_sequence()
    quiet = [(1.1050, 1.1055, 1.1045, 1.1050, 100.0)] * filler
    return candles(quiet + sequence)
