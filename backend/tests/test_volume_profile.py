"""
backend/tests/test_volume_profile.py
Phase 2 — Volume Profile: POC / VAH / VAL, the value-area method, and the
invalid-input paths.

The numbers asserted here are derived analytically from fixtures whose
distribution is known exactly (a flat histogram, a symmetric spike, a clipped
range), not copied from a run of the implementation.
"""
import math

import pandas as pd
import pytest

from tests.helpers import (candles, contiguous_peaked,
                           contiguous_range_weighted, flat_candles,
                           uniform_profile)
from modules import volume_profile as vp


def _profile(df, **kwargs):
    return vp.calculate_session_volume_profile(df, **kwargs)


# ── POC / VAH / VAL on a known distribution ───────────────────────────────────

def test_flat_histogram_yields_the_whole_range_and_is_rejected():
    """
    60 candles tile [100, 110] with identical volume and identical range, so the
    histogram is perfectly flat.

    A flat profile has no peak, so the analysis is degenerate and must be
    reported rather than papered over: "the price of the peak cleared volume"
    has no answer, and the POC returned is the middle of the tied plateau, which
    is not a fact about the market.

    The value area is still computed, and the level tie-break keeps it centred:
    36 of the 50 bins, 17 below the middle and 18 above, so it is the middle of
    the range rather than a band pinned to one end.

    The profile is therefore invalid. Its levels are still returned (a caller
    may want to display them) but it must never gate an entry.
    """
    p = _profile(uniform_profile(100.0, 110.0, count=60, volume=100.0))

    assert p is not None
    assert p["bins_used"] == 50
    assert p["bin_size"] == pytest.approx(10.0 / 50, rel=1e-9)

    assert 100.0 <= p["poc"] <= 110.0
    assert p["val"] <= p["poc"] <= p["vah"]

    # 70% of 50 equal bins is reached as 36 bins, grown with a level tie-break:
    # 17 down and 18 up from the middle, so the area is the middle of the range
    # rather than a band pinned to one end.
    assert p["value_area_share"] == pytest.approx(0.72, abs=1e-6)
    assert p["vah"] - p["val"] == pytest.approx(7.2, abs=0.21)
    assert p["val"] > 100.0 and p["vah"] < 110.0

    assert p["valid"] is False
    assert "flat distribution" in p["warning"]

    ok, reason = vp.gateable(p)
    assert ok is False
    assert "flat distribution" in reason


def test_an_unpeaked_histogram_holds_at_least_the_requested_share():
    """
    The value area must always contain at least the requested share of binned
    volume. It may contain more: a whole bin is the smallest unit the walk adds,
    so the target is approached from below and then stepped over.
    """
    # A flat histogram cannot demonstrate the overshoot (it covers everything),
    # so use a distribution with a real shelf and check every requested share.
    rows = [(100.0, 100.5, 99.5, 100.0, 20.0)] * 10
    rows += [(101.0, 101.5, 100.5, 101.0, 40.0)] * 10
    rows += [(102.0, 102.5, 101.5, 102.0, 80.0)] * 10
    rows += [(103.0, 103.5, 102.5, 103.0, 40.0)] * 10
    rows += [(104.0, 104.5, 103.5, 104.0, 20.0)] * 10

    for pct in (0.5, 0.7, 0.9):
        p = _profile(candles(rows), value_area_pct=pct)
        assert p is not None
        assert p["value_area_share"] >= pct, f"{pct} not reached"
        assert p["value_area_share"] <= pct + 0.25, f"{pct} overshot too far"
        # The area is the symmetric band around the 102 shelf.
        assert p["val"] <= 102.5 and p["vah"] >= 102.0


def test_poc_sits_on_a_clearly_dominant_price():
    """
    A high-volume shelf at 104-105 must win the POC, and the value area must
    cover the shelf: the shelf alone is 10000 of 10600 volume, above the 70%
    target, so the walk stops as soon as it has claimed its bins.

    The shelf is wider than a bin (a 0.947-bin range cannot align with the bin
    grid), so it bleeds into two neighbouring bins, each carrying a quarter of
    the shelf. The area therefore extends one bin beyond the shelf on both
    sides — 104.2 to 105.2 — but never reaches the low-volume noise at 100-101
    or 109-110.
    """
    rows = [(100.0, 101.0, 100.0, 101.0, 5.0)] * 40
    rows += [(104.0, 105.0, 104.0, 105.0, 5000.0)] * 2
    rows += [(109.0, 110.0, 109.0, 110.0, 5.0)] * 20
    p = _profile(candles(rows))

    assert p is not None
    assert 104.0 <= p["poc"] <= 105.0
    assert 103.9 <= p["val"] <= 104.4
    assert 105.0 <= p["vah"] <= 105.4
    assert p["value_area_share"] >= 0.70
    assert p["vah"] - p["val"] <= 1.1
    # The shelf carries most of the window's volume, but the value area is held
    # down at 78% rather than 100%: the walk stops as soon as the target is met
    # and never widens into the low-volume noise at 100-101 or 109-110.
    assert p["value_area_share"] < 0.90
    assert p["valid"] is True
    assert p["warning"] == "volume is a range proxy, not traded volume"


def test_a_clustered_distribution_cannot_reach_the_target_and_is_invalid():
    """
    The same shelf against a far heavier background is detected as the POC, and
    the levels stay inside the traded range.

    But the value area CANNOT reach 70% here: the shelf sits in its own cluster
    of bins and the background volume is in two separate clusters at either end,
    so no contiguous band spans them. The best reachable band is the shelf's own
    cluster at 53% of the window.

    Reporting that as `valid: True` would be a correctness bug, not a courtesy:
    the confluence grader and `gateable` both key off this flag, so a 53% "value
    area" presented as a 70% one would silently widen every level the strategy
    trades. The profile is therefore marked invalid with the shortfall named.
    """
    rows = [(100.0, 101.0, 100.0, 101.0, 400.0)] * 40
    rows += [(104.0, 105.0, 104.0, 105.0, 3000.0)] * 2
    rows += [(109.0, 110.0, 109.0, 110.0, 400.0)] * 20
    p = _profile(candles(rows))

    assert p is not None
    assert 100.0 <= p["poc"] <= 105.0
    assert p["val"] < p["vah"]
    assert p["price_min"] <= p["val"] <= p["poc"] <= p["vah"] <= p["price_max"]
    # The band is contiguous, so it is far narrower than the full 100-110 range.
    assert p["vah"] - p["val"] < 5.0

    assert p["value_area_share"] < 0.70
    assert p["valid"] is False
    assert "below the requested" in p["warning"]

    ok, reason = vp.gateable(p)
    assert ok is False
    assert "below the requested" in reason


def test_a_short_value_area_is_reported_invalid_not_valid():
    """
    REGRESSION: a clustered histogram cannot reach the requested value area, and
    the profile must say so.

    The walk stops when it runs out of ADJACENT bins, so a distribution whose
    volume sits in separated clusters yields an area holding less than the
    requested share. Returning that with `valid: True` is a correctness bug, not
    a courtesy: the confluence grader and `gateable` both key off the flag, so a
    53% "value area" presented as a 70% one silently widens every level the
    strategy trades.

    The achieved share is still reported, so a caller can see the shortfall.
    """
    # Three separated clusters: the middle one is the POC and cannot reach 70%.
    rows = [(100.0, 100.5, 99.5, 100.0, 20.0)] * 10
    rows += [(102.0, 102.5, 101.5, 102.0, 80.0)] * 10
    rows += [(104.0, 104.5, 103.5, 104.0, 20.0)] * 10
    p = _profile(candles(rows))

    assert p is not None
    assert p["value_area_share"] < 0.70
    assert p["valid"] is False
    assert "below the requested" in p["warning"]

    ok, reason = vp.gateable(p)
    assert ok is False
    assert "below the requested" in reason


def test_a_valid_profile_always_reaches_the_requested_share():
    """
    The invariant the flag is supposed to guarantee: if `valid` is True, the
    value area really does hold at least the requested share.

    Checked across several requested shares, because the guarantee is about the
    requested target rather than about a fixed 70%.
    """
    for pct in (0.5, 0.7, 0.9):
        p = _profile(contiguous_peaked(count=60), value_area_pct=pct)
        assert p is not None
        if p["valid"]:
            assert p["value_area_share"] >= pct, (
                f"valid profile at {pct} holds only {p['value_area_share']}")


def test_the_shortfall_check_does_not_reject_a_reachable_area():
    """
    The new check must not make every profile invalid — a contiguous
    distribution still reaches the target and stays valid.
    """
    p = _profile(contiguous_peaked(count=60))
    assert p is not None
    assert p["value_area_share"] >= 0.70
    assert p["valid"] is True
    assert "below the requested" not in (p["warning"] or "")
    """
    When the distribution has no empty gaps and no over-dominant shelf, the walk
    really does reach 70% and the reported share says so. This is the ordinary
    case the strategy meets.

    The fixture is a gentle ramp of 50 candles with a moderately thickened
    middle. The near-flat ramp alone would be rejected as unpeaked, but this
    histogram has a real peak, and the concentration ceiling permits it — the
    peak here is 16% of the volume, well inside the equilibrium band.
    """
    rows = []
    for i in range(50):
        base = 100.0 + i * 0.2
        rows.append((base, base + 0.2, base, base + 0.2, 100.0))
    rows.append((105.0, 105.2, 105.0, 105.2, 1200.0))
    p = _profile(candles(rows), num_bins=50)

    assert p is not None
    assert p["valid"] is True
    assert p["value_area_share"] >= 0.70
    assert p["poc"] > 105.0
    assert p["price_min"] <= p["val"] <= p["poc"] <= p["vah"] <= p["price_max"]
    assert p["vah"] - p["val"] > 1.0

def test_single_candle_spike_marks_the_distribution_invalid():
    """A spike is reported, not silently returned as a meaningful POC."""
    rows = [(100.0, 101.0, 100.0, 101.0, 10.0)] * 30
    rows += [(105.0, 105.1, 105.0, 105.1, 900.0)]
    p = _profile(candles(rows))
    assert p is not None
    assert p["valid"] is False
    assert "non-equilibrium" in p["warning"]


# ── Volume handling ───────────────────────────────────────────────────────────

def test_missing_volume_falls_back_to_range_and_is_not_trusted():
    """
    No volume column at all must not crash, must still produce a profile, and
    must be labelled as a range proxy so a volume gate cannot pass on it.

    The fixture must be a CONTIGUOUS distribution, not two separated clusters:
    a clustered histogram cannot reach the 70% value area without spanning
    price that never traded, so it is reported invalid for a different reason
    and would make this test pass for the wrong one.
    """
    df = contiguous_range_weighted()
    assert "volume" not in df.columns

    p = _profile(df)
    assert p is not None
    assert p["volume_source"] == "range"
    assert p["source_trusted"] is False
    assert p["valid"] is True
    assert p["value_area_share"] >= 0.70

    ok, reason = vp.gateable(p)
    assert ok is False
    assert "proxy" in reason


def test_all_zero_volume_falls_back_to_range():
    """
    Zero volume everywhere is 'no volume information', not 'zero weight': the
    range proxy is used instead, so the reported total is range units, not the
    meaningless zeros that were in the column.
    """
    p = _profile(candles([(100.0, 101.0, 100.0, 101.0, 0.0)] * 30))
    assert p is not None
    assert p["volume_source"] == "range"
    assert p["total_volume"] == pytest.approx(30.0)   # 30 candles x 1.0 range
    assert p["source_trusted"] is False


def test_tick_volume_is_trusted_but_labelled_a_proxy():
    """
    Capital.com tick volume is a proxy for traded volume but it IS volume, so it
    is trusted for confluence; the proxy caveat travels with the profile.

    The fixture is a contiguous ramp, so the value area reaches the 70% target
    and the profile is valid — isolating the volume-source question from the
    distribution question.
    """
    p = _profile(contiguous_peaked(volume_source="tick"))
    assert p["volume_source"] == "tick"
    assert p["source_trusted"] is True
    assert p["valid"] is True
    assert vp.gateable(p) == (True, "ok")


def test_exchange_volume_is_trusted():
    p = _profile(contiguous_peaked(volume_source="exchange"))
    assert p["source_trusted"] is True


def test_volume_source_override_argument_wins():
    df = contiguous_peaked(volume_source="range")
    p = _profile(df, volume_source="tick")
    assert p["volume_source"] == "tick"


# ── Insufficient / invalid data ───────────────────────────────────────────────

def test_none_frame_returns_none():
    assert _profile(None) is None


def test_empty_frame_returns_none():
    assert _profile(pd.DataFrame()) is None


def test_too_few_candles_returns_none():
    """Nine candles is below MIN_CANDLES and has no distribution to describe."""
    df = candles([(100.0, 101.0, 99.0, 100.5, 10.0)] * (vp.MIN_CANDLES - 1))
    assert _profile(df) is None


def test_exactly_min_candles_is_accepted():
    df = candles([(100.0, 101.0, 99.0, 100.5, 10.0)] * vp.MIN_CANDLES)
    p = _profile(df)
    assert p is not None
    assert p["bins_used"] >= 1


def test_missing_high_low_columns_returns_none():
    df = pd.DataFrame({"close": [100.0] * 30})
    assert _profile(df) is None


def test_non_numeric_high_low_are_dropped():
    """Unparseable prices are dropped rather than coerced to zero."""
    rows = pd.DataFrame({
        "high": ["bad"] * 5 + [101.0] * 30,
        "low": ["bad"] * 5 + [99.0] * 30,
        "volume": [10.0] * 35,
        "timestamp": pd.date_range("2026-10-14", periods=35, freq="1h", tz="UTC"),
    })
    p = _profile(rows)
    assert p is not None
    assert p["price_min"] == 99.0


def test_zero_price_range_is_reported_degenerate_not_fabricated():
    """
    Every candle on the same price: there is no distribution, so the levels all
    collapse onto that price and the profile is flagged invalid rather than
    returned as a usable flat VAH/VAL.
    """
    p = _profile(flat_candles(100.0, 100.0, 30, volume=100.0))
    assert p is not None
    assert p["valid"] is False
    assert "degenerate" in p["warning"]
    assert p["poc"] == p["vah"] == p["val"] == 100.0


def test_inverted_high_low_is_repaired():
    """
    A feed that emits low > high must not produce a negative-span histogram.
    The pair is swapped, so the candle contributes over its true range and the
    reported extremes are the corrected ones.
    """
    rows = [(100.0, 99.0, 101.0, 100.5, 10.0)] * 5     # inverted: "high" 99 < "low" 101
    rows += [(100.0, 101.0, 99.0, 100.5, 10.0)] * 25
    p = _profile(candles(rows))
    assert p is not None
    assert p["price_min"] == 99.0
    assert p["price_max"] == 101.0
    assert p["price_min"] < p["price_max"]


def test_zero_range_candle_with_volume_is_not_dropped():
    """
    A doji with volume is still activity; it is placed in the bin it sits in
    rather than discarded.
    """
    rows = [(100.0, 100.0, 100.0, 100.0, 50.0)] * 20
    rows += [(100.0, 102.0, 100.0, 102.0, 10.0)] * 10
    p = _profile(candles(rows))
    assert p is not None
    assert p["bins_used"] >= 1


def test_nan_prices_are_dropped_not_treated_as_zero():
    rows = pd.DataFrame({
        "high": [float("nan")] * 5 + [101.0] * 30,
        "low": [float("nan")] * 5 + [99.0] * 30,
        "volume": [10.0] * 35,
        "timestamp": pd.date_range("2026-10-14", periods=35, freq="1h", tz="UTC"),
    })
    p = _profile(rows)
    assert p is not None
    assert p["price_min"] == 99.0


# ── Bin boundaries ────────────────────────────────────────────────────────────

def test_candle_clipping_a_bin_edge_is_clipped_not_over_counted():
    """
    Bin boundaries must clip each candle's contribution. With one candle
    covering the entire range, the histogram must reproduce that candle's volume
    exactly across the bins it covers — no bin may be credited a whole bin-width
    of volume it never traded.
    """
    df = candles([(100.0, 110.0, 100.0, 110.0, 1000.0)] * 20)
    p = _profile(df, num_bins=10)
    assert p is not None
    # 20 candles x 1000 over 10 bins, spread uniformly => 2000 per bin.
    assert p["total_volume"] == pytest.approx(20000.0, rel=1e-6)

    bins, total, _binned, _src = vp._build_histogram(df, 10, 100.0, 1.0)
    assert total == pytest.approx(20000.0, rel=1e-6)
    for value in bins.values():
        assert value == pytest.approx(2000.0, rel=1e-6)


def test_volumeless_bins_are_absent_not_zero_filled():
    """
    Gaps in a histogram are gaps. Filling them with zeros would let the value
    area 'expand' into empty price and report a wider area than was traded.
    """
    rows = [(100.0, 101.0, 100.0, 101.0, 100.0)] * 15
    rows += [(109.0, 110.0, 109.0, 110.0, 100.0)] * 15
    bins, _total, _binned, _src = vp._build_histogram(candles(rows), 10, 100.0, 1.0)
    assert set(bins) == {0, 9}


def test_value_area_never_spans_an_empty_gap():
    """
    Two separated clusters with an entirely empty gap between them must not be
    merged into one value area. The walk only ever steps to an ADJACENT bin, so
    it stays inside whichever cluster it was seeded in — the empty bins 1-8 are
    never entered, and the area never becomes the whole range.

    The restart scan seeds from the busiest bin and keeps the best contiguous
    band, so the empty bins 1-8 are never entered and the area never becomes a
    span across the gap.
    """
    area, vol = vp._expand_value_area({0: 100.0, 9: 100.0}, 130.0)
    assert len(area) == 1
    assert not set(range(1, 9)) & set(area)
    assert vol == pytest.approx(100.0)


def test_a_single_gap_bin_is_never_entered():
    """
    An empty bin inside the histogram is never entered by the walk, so the area
    never spans price that did not trade. Bin 1 is empty and absent, so no seed
    can cross from 0 to 2 and each reaches only its own bin.
    """
    area, vol = vp._expand_value_area({0: 100.0, 2: 100.0}, 150.0)
    assert 1 not in area
    assert len(area) == 1
    assert vol == pytest.approx(100.0)


def test_poc_ambiguity_detection():
    """A uniform histogram has no peak; a peaked one does."""
    assert vp.poc_is_ambiguous({0: 100.0, 1: 100.0, 2: 100.0, 3: 100.0}) is True
    assert vp.poc_is_ambiguous({0: 100.0, 1: 500.0, 2: 100.0}) is False
    assert vp.poc_is_ambiguous({}) is True


def test_poc_tie_break_prefers_the_middle_of_a_plateau():
    """
    With bins 0-4 tied at the peak and a low shelf on either side, the POC must
    be the middle of the tied plateau, not its lowest bin.
    """
    bins = {0: 10.0, 1: 10.0, 2: 10.0, 3: 10.0, 4: 10.0, 5: 100.0, 6: 100.0,
            7: 100.0, 8: 100.0, 9: 100.0, 10: 10.0}
    assert vp._poc_bin(bins) == 7

def test_num_bins_below_two_is_rejected():
    assert _profile(uniform_profile(100.0, 110.0, count=60), num_bins=1) is None
    assert _profile(uniform_profile(100.0, 110.0, count=60), num_bins=0) is None


def test_levels_stay_inside_the_traded_range():
    p = _profile(uniform_profile(100.0, 110.0, count=60))
    assert p["price_min"] <= p["val"] <= p["vah"] <= p["price_max"]
    assert p["price_min"] <= p["poc"] <= p["price_max"]


def test_value_area_walk_grows_symmetrically_on_a_uniform_histogram():
    """
    36 equal bins from a centred seed. Because every bin ties, the seed bin is
    the middle of the plateau, and every neighbour then ties as well, so the
    walk alternates outward: 17 bins down and 18 up. The area is therefore the
    middle of the range rather than a band at one end, which is what
    `up >= down` without a tie-break produces.
    """
    bins = {i: 10.0 for i in range(50)}
    area, vol = vp._expand_value_area(bins, 360.0, 25)
    assert len(area) == 36
    assert min(area) == 8
    assert max(area) == 43
    assert vol == pytest.approx(360.0)


def test_value_area_walk_stops_when_the_target_cannot_be_reached():
    """
    A target larger than the reachable volume must terminate and report the
    share it actually reached, not spin. This is the sparse-histogram case: a
    narrow shelf inside a mostly empty range, fenced in by absent bins.
    """
    area, vol = vp._expand_value_area({10: 100.0, 11: 100.0}, 10_000.0)
    assert area == [10, 11]
    assert vol == pytest.approx(200.0)


def test_value_area_walk_hugs_a_central_shelf_symmetrically():
    """
    When one bin really is the peak, the area grows outward from it and takes
    the fatter neighbour at each step. It must stay centred: 17 bins below and
    18 above the shelf, never all 36 on one side.
    """
    bins = {i: 10.0 for i in range(50)}
    bins[25] = 100.0
    area, vol = vp._expand_value_area(bins, 360.0, 25)

    assert min(area) == 17
    assert max(area) == 43
    assert len(area) == 27
    assert vol == pytest.approx(360.0)
    assert vp._poc_bin(bins) == 25


def test_value_area_walk_takes_the_fatter_side_when_neighbours_differ():
    """A clearly fatter neighbour is always taken, tie-break or not."""
    bins = {i: 10.0 for i in range(11)}
    bins[10] = 100.0
    area, _vol = vp._expand_value_area(bins, 100.0, 5)
    assert 10 in area


def test_repeated_calls_are_deterministic():
    """Same input, same output — the levels must not drift between scans."""
    df = uniform_profile(100.0, 110.0, count=60)
    first = _profile(df)
    second = _profile(df.copy())
    assert first == second


# ── gateable / confluence interaction ─────────────────────────────────────────

def test_gateable_rejects_a_missing_profile():
    ok, reason = vp.gateable(None)
    assert ok is False
    assert reason == "no profile"


def test_gateable_rejects_an_invalid_profile():
    p = _profile(candles([(100.0, 101.0, 100.0, 101.0, 10.0)] * 30 +
                         [(105.0, 105.1, 105.0, 105.1, 900.0)]))
    ok, reason = vp.gateable(p)
    assert ok is False
    assert "non-equilibrium" in reason


def test_gateable_can_opt_into_a_proxy():
    """
    A range-proxy profile is refused by default but can be opted into, which is
    the switch VP_REQUIRE_TRUSTED_VOLUME exposes. The profile must still be a
    valid distribution, so the fixture is a contiguous ramp rather than a
    clustered one.
    """
    p = _profile(contiguous_peaked())
    assert p["source_trusted"] is False
    assert p["valid"] is True
    ok, reason = vp.gateable(p)
    assert ok is False
    assert "proxy" in reason
    assert vp.gateable(p, require_trusted_volume=False) == (True, "ok")


def test_fvg_confluence_grades_a_poc_overlap():
    p = _profile(uniform_profile(100.0, 110.0, count=60, volume=100.0,
                                 volume_source="tick"))
    fvg = {"fvg_low": p["poc"] - 0.1, "fvg_high": p["poc"] + 0.1}
    grade = vp.check_fvg_confluence(fvg, p)
    assert grade["grade"] == "POC_OVERLAP"
    assert grade["size_multiplier"] == 1.0
    assert grade["source_trusted"] is True


def test_fvg_confluence_is_no_confluence_without_a_profile():
    grade = vp.check_fvg_confluence({"fvg_low": 1.0, "fvg_high": 2.0}, None)
    assert grade["grade"] == "NO_CONFLUENCE"
    assert grade["size_multiplier"] <= 1.0


# ── classify_price_position ───────────────────────────────────────────────────

def test_classify_price_position_covers_every_band():
    p = {"poc": 105.0, "vah": 108.0, "val": 102.0}
    assert vp.classify_price_position(110.0, p) == "ABOVE_VALUE"
    assert vp.classify_price_position(100.0, p) == "BELOW_VALUE"
    assert vp.classify_price_position(103.0, p) == "INSIDE_VALUE"
    assert vp.classify_price_position(105.0, p) == "AT_POC"


def test_classify_price_position_unknown_on_a_missing_profile():
    assert vp.classify_price_position(100.0, None) == "UNKNOWN"
    assert vp.classify_price_position(None, {"poc": 1, "vah": 2, "val": 0}) == "UNKNOWN"
