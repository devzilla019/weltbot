"""
backend/modules/volume_profile.py
Volume Profile — POC / VAH / VAL.

Builds a price histogram from candle data and derives:
  POC = the price bin with the highest accumulated volume
      ("the price of the peak cleared volume")
  VAH = upper bound of the Value Area
  VAL = lower bound of the Value Area

VALUE AREA METHOD (this is the part the sample code got wrong)
-------------------------------------------------------------
The Value Area is the central ~70% of activity around the POC. The reference
method (CBOT Market Profile, Steidlmayer) expands OUTWARD from the POC one
adjacent bin at a time, each step taking whichever of the two neighbouring
bins — the next one up, or the next one down — holds more volume, until the
accumulated share reaches the target.

Two things matter and are easy to get wrong:
  1. The bins must be CONTIGUOUS. Selecting the globally largest bins in
     descending order (which is what picking the top-N bins by value does) can
     return two separated clusters and imply a value area that price never
     actually filled.
  2. The expansion is a greedy two-sided walk, not a re-sort.

The literal CBOT definition is POC +/- one standard deviation. A volume
percentage is the more common practical reading and is what this project uses,
so VALUE_AREA_PCT defaults to 0.70.

VOLUME IS A PROXY
-----------------
Capital.com reports `lastTradedVolume` per candle: the contracts that provider
itself cleared. For FX and CFDs that is a thin slice of a decentralised market,
so it is a PROXY for traded volume, never true exchange-traded volume.

Binance reports real traded volume, and the code distinguishes the two via
`volume_source`. When a source reports no volume at all the profile falls back
to range coverage, which still yields a usable profile but degenerates towards
a TPO-style time-at-price distribution. Every profile reports which source was
used so a caller can refuse to gate a decision on a proxy.
"""
import logging
from typing import Dict, List, Optional, Tuple

import pandas as pd

logger = logging.getLogger(__name__)

# Fraction of total volume the Value Area must contain.
VALUE_AREA_PCT = 0.70

# Default histogram resolution.
DEFAULT_BINS = 50

# Fewest candles a profile can be built from. Below this the histogram is
# noise and the resulting levels would be arbitrary.
MIN_CANDLES = 10

# Volume sources whose `volume` column carries real information.
TRUSTED_VOLUME_SOURCES = ("tick", "exchange")

# A profile is "valid" as a distribution only when no single bin holds an
# outsized share of the total.
#
# The threshold is 0.35 because a spike bleeds across the bin grid: a candle
# whose range does not align with the bins leaves half its range in each of two
# neighbours, so the tallest bin of a genuine shelf carries roughly half the
# shelf's share. Rejecting at 0.35 therefore still catches any shelf holding
# more than ~70% of the window, which is the "one level dominated the day" case
# the check exists for.
#
# Market Profile theory is explicit that a non-equilibrium distribution —
# bimodal, or concentrated on a single price — has no meaningful POC or standard
# deviation: "if the market is not in equilibrium there is no valid POC". So it
# is surfaced rather than silently returned as if the levels meant something.
MAX_BIN_CONCENTRATION = 0.35

# Two bins are "equal" for the purposes of a tie-break within this relative
# tolerance. Candles partition across bins using floating-point arithmetic, so a
# genuinely uniform histogram arrives with values of 120.00000000000009 next to
# 119.99999999999999; comparing exactly would call the largest of those a real
# peak and hand the profile a POC that is pure rounding noise.
BIN_TIE_REL_TOL = 1e-9


# ── Histogram construction ────────────────────────────────────────────────────

def _build_histogram(df: pd.DataFrame, num_bins: int,
                     price_min: float, bin_size: float
                     ) -> Tuple[Dict[int, float], float, str]:
    """
    Distribute each candle's volume across the price bins it spans.

    A candle's volume is spread uniformly over its own high-low range, so a
    wide candle contributes thinly per unit of price and a narrow candle
    contributes densely. That is the standard assumption when only OHLCV is
    available: the bar does not reveal the order in which its prices traded.

    Each bin's contribution is clipped to the part of the candle's range that
    actually falls inside that bin. Without the clip, a candle that only clips
    the edge of a bin would contribute a whole bin's worth and the histogram
    would over-count.

    Returns (bins, total_volume, binned_volume, used_source).
    """
    has_volume = "volume" in df.columns and \
        pd.to_numeric(df["volume"], errors="coerce").fillna(0.0).sum() > 0

    used_source = "volume" if has_volume else "range"
    bins: Dict[int, float] = {}
    total_volume = 0.0
    # Volume actually placed in bins. A candle that only clips the edge of a bin
    # has the out-of-bin part of its range discarded when the first/last bin is
    # clamped, so this can be below `total_volume` and a share measured against
    # `total_volume` would understate the value area.
    binned_volume = 0.0
    for _, candle in df.iterrows():
        try:
            c_high = float(candle["high"])
            c_low = float(candle["low"])
        except (TypeError, ValueError):
            continue
        if c_high < c_low:
            c_high, c_low = c_low, c_high

        candle_range = c_high - c_low

        if has_volume:
            vol = float(pd.to_numeric(candle.get("volume"), errors="coerce") or 0.0)
        else:
            # No usable volume — weight by range so the profile still reflects
            # where price spent time rather than returning nothing.
            vol = candle_range

        if vol <= 0:
            continue

        span = candle_range
        if span <= 0:
            # A zero-range candle still carries volume; place it in the single
            # bin it sits in rather than dropping it.
            span = bin_size

        vol_per_price = vol / span
        total_volume += vol
        # Counted across the bins actually touched below. A candle whose range
        # falls entirely outside the histogram (possible only when unparseable
        # prices were dropped earlier) then correctly contributes nothing rather
        # than inflating the binned total with volume no bin holds.
        candle_placed = 0.0

        first = int((c_low - price_min) / bin_size)
        last = int((c_high - price_min) / bin_size)
        first = max(0, min(first, num_bins - 1))
        last = max(0, min(last, num_bins - 1))

        for bin_idx in range(first, last + 1):
            if candle_range <= 0:
                overlap = bin_size
            else:
                bin_low = price_min + bin_idx * bin_size
                bin_high = bin_low + bin_size
                overlap = min(c_high, bin_high) - max(c_low, bin_low)
            if overlap <= 0:
                continue
            part = vol_per_price * overlap
            bins[bin_idx] = bins.get(bin_idx, 0.0) + part
            candle_placed += part

        binned_volume += candle_placed

    return bins, total_volume, binned_volume, used_source


def _tied_bins(bins: Dict[int, float]) -> List[int]:
    """
    Every bin holding the peak volume, ascending, within a relative tolerance.

    Exact comparison is wrong here. Bin contributions are computed with
    floating-point arithmetic, so a genuinely uniform histogram holds
    119.99999999999999 in one bin and 120.00000000000009 in its neighbour;
    `max` would single out the latter as the peak, the profile would report a
    POC that is nothing but rounding noise, and the value-area walk would start
    off-centre.
    """
    peak = max(bins.values())
    if peak <= 0:
        return sorted(bins)
    tol = abs(peak) * BIN_TIE_REL_TOL
    return sorted(b for b, v in bins.items() if abs(v - peak) <= tol)


def _poc_bin(bins: Dict[int, float]) -> int:
    """
    The POC bin: the bin holding the most volume, nearest the middle on a tie.

    The tie-break matters on a flat or near-flat histogram — a market that has
    not yet built a shelf, which is exactly when a session scan runs. Breaking
    towards the LOWEST bin (what `max(bins, key=lambda b: (bins[b], -b))` does)
    pins the POC to the bottom of the range and pushes the value area to one end
    of it.

    Returning the median of the tied bins keeps the POC, and therefore the area
    built around it, centred on the tied plateau that is genuinely the point of
    control.

    Callers must check `poc_is_ambiguous` first: on a histogram where EVERY bin
    is tied there is no point of control at all and the level is arbitrary.
    """
    tied = _tied_bins(bins)
    return tied[len(tied) // 2]


def _best_poc_bin(bins: Dict[int, float]) -> int:
    """
    The bin the value area is seeded from.

    That is the single busiest bin, NOT the widest contiguous plateau tie. The
    plateau rule is the more faithful Market Profile reading, but it fails on
    the distribution this strategy actually meets: a quiet two-hour shelf
    against a heavy background produces a wide plateau holding only a fifth of
    the window, and a walk seeded there cannot reach a 70% target at all — the
    value area comes back holding 53% of the volume while being presented as the
    70% area.

    Seeding from the busiest single bin lets the walk travel outward until the
    target genuinely is met, which is what makes the reported share mean what it
    says. On a flat histogram the tied peak still yields the centred bin.
    """
    return _poc_bin(bins)


def poc_is_ambiguous(bins: Dict[int, float]) -> bool:
    """
    True when the histogram holds no point of control.

    That is the case when every populated bin carries the same volume: a
    perfectly uniform distribution has no peak, so "the price of the peak
    cleared volume" has no answer and any bin chosen would be an artefact of the
    tie-break rather than a fact about the market.

    The test is against the MEAN, not against the maximum: a distribution with a
    peak has bins below the mean, whereas on a uniform histogram every bin sits
    on the mean up to a rounding residue.
    """
    if not bins:
        return True
    if len(bins) <= 1:
        return True
    mean = sum(bins.values()) / len(bins)
    if mean <= 0:
        return True
    return all(abs(v - mean) <= abs(mean) * BIN_TIE_REL_TOL * len(bins)
               for v in bins.values())


def _expand_from(bins: Dict[int, float], seed: int, target: float
                 ) -> Tuple[List[int], float]:
    """
    Grow one contiguous area outward from `seed` until it covers `target`.

    Returns (bins_in_the_area, accumulated_volume). The accumulation is whatever
    the walk could actually reach, which may be less than `target` when the seed
    is fenced in by empty bins.
    """
    included = {seed}
    accumulated = bins[seed]

    # The seed is counted with the lower side so the tie-break starts level on
    # equal neighbours, which makes a uniform histogram grow 17 bins down and 18
    # up rather than 17 and 19.
    below = accumulated
    above = 0.0

    low = seed
    high = seed

    # Bounded by the number of populated bins. Without a bound a target larger
    # than the reachable volume would loop for ever: both neighbours are None,
    # `low`/`high` never move, and the `break` on the next pass never comes.
    for _ in range(len(bins)):
        if accumulated >= target:
            break

        up = bins.get(high + 1)
        down = bins.get(low - 1)

        if up is None and down is None:
            break

        if up is None:
            take_up = False
        elif down is None:
            take_up = True
        elif up != down:
            take_up = up > down
        else:
            take_up = above <= below

        if take_up:
            high += 1
            accumulated += up
            above += up
            included.add(high)
        else:
            low -= 1
            accumulated += down
            below += down
            included.add(low)

    return sorted(included), accumulated


def _expand_value_area(bins: Dict[int, float], target: float,
                       poc_bin: Optional[int] = None
                       ) -> Tuple[List[int], float]:
    """
    The Value Area: the most volume a contiguous band from the POC can hold.

    Grows outward from the POC one adjacent bin at a time, each step taking
    whichever of the two neighbouring bins holds more volume. Both sides are
    walked, so the result can never be two detached clusters and is always
    contiguous.

    A missing neighbour is skipped, not treated as zero: an empty gap in the
    histogram must never be entered, or the value area would span price that
    never traded.

    When the two neighbours hold EXACTLY the same volume the tie is broken
    towards whichever side of the POC already holds less volume, counting the
    POC bin itself with the lower side so the two sides start level. A flat
    histogram is the case that makes this matter: `up >= down` would climb until
    the range ran out and return "the top 70% of the range" rather than a value
    area around the POC.

    A distribution can be fenced in. A narrow high-volume shelf inside a mostly
    quiet range has empty bins on both sides, so a walk seeded there runs out of
    adjacent bins partway to the target and would return 53% of the volume while
    calling it the value area. The walk is therefore restarted from each
    remaining bin in descending volume and the best contiguous band found wins,
    which is by construction the area the target is asking about.

    Returns (bin_indices_in_the_area, accumulated_volume).
    """
    if not bins:
        return [], 0.0

    if poc_bin is None:
        poc_bin = _best_poc_bin(bins)

    best_bins, best_volume = _expand_from(bins, poc_bin, target)

    if best_volume < target:
        for seed in sorted(bins, key=lambda b: (-bins[b], b)):
            if seed == poc_bin:
                continue
            area, volume = _expand_from(bins, seed, target)
            # `>` so a tie keeps the band already held, and the seeds are
            # ordered by descending volume, so the band anchored nearest the
            # busiest bin is preferred among equal-volume bands.
            if volume > best_volume:
                best_bins, best_volume = area, volume
            if best_volume >= target:
                break

    return best_bins, best_volume


# ── Public API ────────────────────────────────────────────────────────────────

def calculate_session_volume_profile(candles_df: pd.DataFrame,
                                     num_bins: int = DEFAULT_BINS,
                                     value_area_pct: float = VALUE_AREA_PCT,
                                     volume_source: Optional[str] = None
                                     ) -> Optional[Dict]:
    """
    Calculate POC, VAH and VAL from candle data.

    Args:
        candles_df:     DataFrame with high and low columns; `volume` is used
                        when present and non-zero. Timestamps are ignored — the
                        caller is responsible for passing a correctly bounded
                        window (see `previous_day_profile`).
        num_bins:       histogram resolution.
        value_area_pct: share of binned volume the Value Area must cover.
        volume_source:  override for the provenance label. Read from
                        `candles_df.attrs["volume_source"]` when omitted.

    Returns a dict, or None when no profile can be built at all:
      {
        poc, vah, val, price_min, price_max,
        total_volume, bins_used, bin_size,
        value_area_pct, value_area_volume, value_area_share,
        volume_source,      # tick | exchange | range | none | proxy
        source_trusted,     # True only for tick/exchange
        valid,              # False when the distribution is unusable
        warning,            # human-readable reason when valid is False
      }
    """
    try:
        if candles_df is None or len(candles_df) < MIN_CANDLES:
            logger.debug("[vp] not enough candles for a profile")
            return None

        for col in ("high", "low"):
            if col not in candles_df.columns:
                logger.warning(f"[vp] missing '{col}' column — cannot build profile")
                return None

        df = candles_df.copy()
        df["high"] = pd.to_numeric(df["high"], errors="coerce")
        df["low"] = pd.to_numeric(df["low"], errors="coerce")
        df = df.dropna(subset=["high", "low"])
        if len(df) < MIN_CANDLES:
            return None

        try:
            src = volume_source or df.attrs.get("volume_source", "range")
        except Exception:
            src = volume_source or "range"

        price_min = float(df["low"].min())
        price_max = float(df["high"].max())
        price_range = price_max - price_min

        bins_requested = int(num_bins)
        if bins_requested < 2:
            return None

        if not (price_range > 0):
            # Every candle covers the same single price. There is no
            # distribution to describe, so every level collapses onto it and the
            # profile is reported as invalid rather than as a usable flat VAH/VAL.
            return {
                "poc": round(price_min, 5),
                "vah": round(price_min, 5),
                "val": round(price_min, 5),
                "price_min": round(price_min, 5),
                "price_max": round(price_min, 5),
                "total_volume": 0.0,
                "bins_used": 0,
                "bin_size": 0.0,
                "value_area_pct": round(float(value_area_pct), 4),
                "value_area_volume": 0.0,
                "value_area_share": 0.0,
                "volume_source": src,
                "source_trusted": src in TRUSTED_VOLUME_SOURCES,
                "valid": False,
                "warning": "zero price range — degenerate profile",
            }

        bin_size = price_range / bins_requested
        bins, total_volume, binned_volume, _used = _build_histogram(
            df, bins_requested, price_min, bin_size
        )

        if not bins or total_volume <= 0:
            logger.debug("[vp] histogram empty — no profile")
            return None

        # ── POC: the price of the peak cleared volume ────────────────────────
        poc_bin = _poc_bin(bins)
        poc = price_min + (poc_bin * bin_size) + (bin_size / 2)

        # ── Value Area: contiguous expansion outward from the POC ────────────
        # The share is measured against the volume actually placed in bins, not
        # against `total_volume`: a candle range that clips a bin edge is
        # discarded by the overlap clip, so the two can differ. Using the binned
        # total keeps the reported share internally consistent with the
        # histogram.
        target = binned_volume * float(value_area_pct)
        area_bins, area_volume = _expand_value_area(bins, target, poc_bin)

        vah = price_min + ((max(area_bins) + 1) * bin_size)
        val = price_min + (min(area_bins) * bin_size)
        achieved_share = (area_volume / binned_volume) if binned_volume else 0.0

        # ── Distribution quality ─────────────────────────────────────────────
        concentration = max(bins.values()) / binned_volume if binned_volume else 0.0
        valid = True
        warning = None
        if poc_is_ambiguous(bins):
            valid = False
            warning = ("flat distribution — every populated price bin holds the "
                       "same volume, so there is no point of control and the "
                       "value area is arbitrary")
        elif concentration > MAX_BIN_CONCENTRATION:
            valid = False
            warning = (f"non-equilibrium distribution — one bin holds "
                       f"{concentration*100:.0f}% of volume; POC and value area "
                       f"are not statistically meaningful")
        elif achieved_share + 1e-9 < float(value_area_pct):
            # The walk is fenced in by empty bins and could not reach the
            # requested share. That happens when the volume sits in separated
            # clusters: no contiguous band spans them, and entering the empty
            # price between them would place the value area across price that
            # never traded.
            #
            # This is reported as INVALID rather than as a valid short area. A
            # caller reading `valid: True` is entitled to believe the value area
            # is the 70% area it asked for, and the confluence grader and the
            # gate both key off this flag — a 53% "value area" presented as a
            # 70% one would silently widen every level the strategy trades.
            valid = False
            warning = (f"value area holds {achieved_share*100:.0f}% of volume, "
                       f"below the requested {float(value_area_pct)*100:.0f}% — "
                       f"the distribution is clustered, so no contiguous band "
                       f"reaches the target")

        if src in ("range", "none", "proxy"):
            warning = warning or f"volume is a {src} proxy, not traded volume"

        return {
            "poc": round(poc, 5),
            "vah": round(vah, 5),
            "val": round(val, 5),
            "price_min": round(price_min, 5),
            "price_max": round(price_max, 5),
            "total_volume": round(total_volume, 2),
            "bins_used": len(bins),
            "bin_size": round(bin_size, 8),
            "value_area_pct": round(float(value_area_pct), 4),
            "value_area_volume": round(area_volume, 2),
            "value_area_share": round(achieved_share, 4),
            "volume_source": src,
            "source_trusted": src in TRUSTED_VOLUME_SOURCES,
            "valid": valid,
            "warning": warning,
        }

    except Exception as e:
        logger.error(f"[vp] volume profile error: {e}")
        return None


def classify_price_position(price: float, vp: Dict) -> str:
    """
    Where price sits relative to the value area.

    Returns one of: ABOVE_VALUE | BELOW_VALUE | INSIDE_VALUE | AT_POC | UNKNOWN

    AT_POC is checked first so a price sitting on the POC reads as AT_POC
    rather than as merely inside the value area.
    """
    try:
        if not vp or price is None:
            return "UNKNOWN"

        poc, vah, val = vp.get("poc"), vp.get("vah"), vp.get("val")
        if poc is None or vah is None or val is None:
            return "UNKNOWN"

        price = float(price)
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


def _overlaps(low: float, high: float, level: float) -> bool:
    """True when `level` sits inside [low, high]."""
    return low <= level <= high


def check_fvg_confluence(fvg: Dict, vp: Dict,
                         tolerance: float = 0.0015) -> Dict:
    """
    Grade a fair value gap against the volume profile.

    Confluence is judged on OVERLAP, not on a midpoint distance, because the
    question that matters is "does this gap touch the level?". A midpoint test
    at a fixed percentage of price is ATR-scale on FX and makes the VAH/VAL
    grades almost unreachable. `tolerance` widens each level into a thin band so
    a gap that closes exactly at a level still grades as touching it.

    Grades, strongest first:
      POC_OVERLAP      gap covers the point of control
      VAH_CONFLUENCE   gap touches the value area high
      VAL_CONFLUENCE   gap touches the value area low
      INSIDE_VALUE     gap sits inside the value area without touching POC
      NO_CONFLUENCE    gap is outside the value area entirely

    Returns {grade, size_multiplier, volume_source, source_trusted,
             profile_valid, reason}.

    `size_multiplier` is a *relative* position-size hint and is capped at 1.0. A
    heuristic confluence grade is not evidence of a higher win probability, so
    it must never open a LARGER position than the configured risk allows; it may
    only reduce one.
    """
    try:
        if not fvg or not vp:
            return {"grade": "NO_CONFLUENCE", "size_multiplier": 0.5,
                    "volume_source": (vp or {}).get("volume_source"),
                    "source_trusted": bool((vp or {}).get("source_trusted")),
                    "profile_valid": False,
                    "reason": "missing fvg or profile"}

        fvg_high = float(fvg.get("fvg_high") or 0.0)
        fvg_low = float(fvg.get("fvg_low") or 0.0)
        if fvg_high <= 0 or fvg_low <= 0 or fvg_high < fvg_low:
            return {"grade": "NO_CONFLUENCE", "size_multiplier": 0.5,
                    "volume_source": vp.get("volume_source"),
                    "source_trusted": bool(vp.get("source_trusted")),
                    "profile_valid": bool(vp.get("valid")),
                    "reason": "invalid fvg bounds"}

        poc = vp.get("poc")
        vah = vp.get("vah")
        val = vp.get("val")

        base = {
            "volume_source": vp.get("volume_source"),
            "source_trusted": bool(vp.get("source_trusted")),
            "profile_valid": bool(vp.get("valid")),
        }

        if poc is None or vah is None or val is None:
            return {**base, "grade": "NO_CONFLUENCE", "size_multiplier": 0.5,
                    "reason": "profile incomplete"}

        band = abs(float(poc)) * float(tolerance) if poc else 0.0

        if _overlaps(fvg_low, fvg_high, float(poc)):
            return {**base, "grade": "POC_OVERLAP", "size_multiplier": 1.0,
                    "reason": "gap covers the point of control"}

        if _overlaps(fvg_low - band, fvg_high + band, float(vah)):
            return {**base, "grade": "VAH_CONFLUENCE", "size_multiplier": 1.0,
                    "reason": "gap touches the value area high"}

        if _overlaps(fvg_low - band, fvg_high + band, float(val)):
            return {**base, "grade": "VAL_CONFLUENCE", "size_multiplier": 1.0,
                    "reason": "gap touches the value area low"}

        if fvg_low >= float(val) and fvg_high <= float(vah):
            return {**base, "grade": "INSIDE_VALUE", "size_multiplier": 0.75,
                    "reason": "gap inside the value area, away from POC"}

        return {**base, "grade": "NO_CONFLUENCE", "size_multiplier": 0.5,
                "reason": "gap outside the value area"}

    except Exception as e:
        logger.error(f"[vp] confluence error: {e}")
        return {"grade": "NO_CONFLUENCE", "size_multiplier": 0.5,
                "volume_source": None, "source_trusted": False,
                "profile_valid": False, "reason": f"error: {e}"}


def gateable(vp: Optional[Dict], require_trusted_volume: bool = True) -> Tuple[bool, str]:
    """
    Whether a profile is fit to gate an entry decision on.

    Returns (ok, reason). A profile built from a range proxy is perfectly usable
    for display and for context, but gating a trade on it would be gating on
    time-at-price while calling it volume.
    """
    if not vp:
        return False, "no profile"
    if not vp.get("valid"):
        return False, vp.get("warning") or "profile flagged invalid"
    if require_trusted_volume and not vp.get("source_trusted"):
        return False, (f"volume source '{vp.get('volume_source')}' is a proxy, "
                       f"not traded volume")
    return True, "ok"


# ── UTC day boundaries and the previous-day profile ───────────────────────────

def utc_day_bounds(now: Optional[pd.Timestamp] = None) -> Tuple[pd.Timestamp, pd.Timestamp]:
    """
    The [start, end) of today in UTC, as tz-aware timestamps.

    All session and daily logic in this project rolls on UTC. Deriving the
    boundary from a naive local `datetime.utcnow()` and then comparing against
    tz-aware candle timestamps is the classic way to get an off-by-hours window,
    so the boundary is always tz-aware and callers compare like with like.
    """
    ts = pd.Timestamp.now(tz="UTC") if now is None else pd.Timestamp(now)
    if ts.tzinfo is None:
        ts = ts.tz_localize("UTC")
    else:
        ts = ts.tz_convert("UTC")
    start = ts.normalize()
    return start, start + pd.Timedelta(days=1)


def previous_day_bounds(now: Optional[pd.Timestamp] = None
                        ) -> Tuple[pd.Timestamp, pd.Timestamp]:
    """The [start, end) of the PREVIOUS UTC day."""
    start, _ = utc_day_bounds(now)
    return start - pd.Timedelta(days=1), start


def utc_date_key(now: Optional[pd.Timestamp] = None) -> str:
    """
    The UTC date key used to key daily state, e.g. '2026-10-15'.

    Daily bias records are only valid for the UTC day they were computed on;
    comparing this string is how a stale record is detected after midnight or
    after a redeploy.
    """
    start, _ = utc_day_bounds(now)
    return start.strftime("%Y-%m-%d")


def slice_utc_window(candles_df: Optional[pd.DataFrame],
                     start: pd.Timestamp,
                     end: pd.Timestamp) -> Optional[pd.DataFrame]:
    """
    Candles whose timestamp falls in [start, end).

    Returns None when the frame has no usable timestamp column, because
    silently profiling "whatever the caller passed" is how a profile ends up
    built from a window that is not the one that was asked for.
    """
    if candles_df is None or len(candles_df) == 0:
        return None
    if "timestamp" not in candles_df.columns:
        logger.warning("[vp] frame has no timestamp column — cannot bound window")
        return None

    try:
        df = candles_df.copy()
        ts = pd.to_datetime(df["timestamp"], errors="coerce", utc=True)
        df = df.assign(_ts=ts).dropna(subset=["_ts"])
        if len(df) == 0:
            return None
        df = df[(df["_ts"] >= start) & (df["_ts"] < end)].drop(columns=["_ts"])
        return df.reset_index(drop=True) if len(df) else None
    except Exception as e:
        logger.error(f"[vp] window slice error: {e}")
        return None


def previous_day_profile(candles_df: Optional[pd.DataFrame],
                         now: Optional[pd.Timestamp] = None,
                         num_bins: int = DEFAULT_BINS) -> Optional[Dict]:
    """
    Volume profile of the previous UTC day, from candles that actually fall in
    that day.

    The prior implementation profiled `get_candles(..., "1h", limit=48)` — a
    trailing 48-bar window, which is not a day boundary. During a session it
    covered most of yesterday plus part of today, so the POC drifted with the
    current session and the levels were not reproducible from one run to the
    next. Bounding explicitly on UTC makes the profile a function of the date
    rather than of when the scan happened to run.
    """
    start, end = previous_day_bounds(now)
    window = slice_utc_window(candles_df, start, end)
    if window is None or len(window) < MIN_CANDLES:
        return None

    vp = calculate_session_volume_profile(window, num_bins=num_bins)
    if vp:
        vp["window_start"] = start.isoformat()
        vp["window_end"] = end.isoformat()
        vp["window_candles"] = len(window)
    return vp
