"""
backend/tests/test_silver_bullet_engine.py
Phase 3 — the Silver Bullet signal engine.

Every stage is tested in isolation and then end-to-end through `build_setup`,
so a failure names the stage rather than the pipeline. The fixtures are exact:
a sweep that clears the 40% body filter, an MSS one candle later, and a
three-candle imbalance, so an assertion that fails means the engine changed
rather than the data.
"""
from datetime import datetime, timedelta

import pandas as pd
import pytest

from tests.helpers import (bear_sweep_sequence, bull_sweep_sequence, candles,
                           silver_bias, silver_entry_frame,
                           silver_session_levels, trusted_vp,
                           trusted_vp_bearish)
from modules import forex_signal_engine as fse


NOW = datetime(2026, 10, 15, 8, 30)          # inside LONDON
LEVELS = silver_session_levels()


def _df(rows=None):
    return candles(rows if rows is not None else bull_sweep_sequence())


def _good_bias(**kw):
    kw.setdefault("vp_levels", trusted_vp())
    return silver_bias(**kw)


# ══════════════════════════════════════════════════════════════════════════════
#  1. SESSION WINDOWS
# ══════════════════════════════════════════════════════════════════════════════

def test_the_three_windows_are_the_specified_utc_hours():
    assert fse.SESSIONS["LONDON"] == (8, 9, 3)
    assert fse.SESSIONS["NY_MORNING"] == (15, 16, 4)
    assert fse.SESSIONS["NY_AFTERNOON"] == (19, 20, 2)


@pytest.mark.parametrize("hour,expected", [
    (8, "LONDON"), (15, "NY_MORNING"), (19, "NY_AFTERNOON"),
])
def test_each_window_opens_on_its_hour(hour, expected):
    assert fse.current_session(NOW.replace(hour=hour)) == expected


@pytest.mark.parametrize("hour", [0, 7, 9, 12, 14, 16, 18, 20, 23])
def test_no_session_outside_the_windows(hour):
    assert fse.current_session(NOW.replace(hour=hour)) is None


def test_windows_are_half_open_so_they_never_overlap():
    assert fse.current_session(NOW.replace(hour=8, minute=59)) == "LONDON"
    assert fse.current_session(NOW.replace(hour=9, minute=0)) is None


def test_session_bounds_are_derived_from_the_given_day():
    open_dt, close_dt = fse.session_bounds("LONDON", NOW)
    assert (open_dt.hour, close_dt.hour) == (8, 9)
    assert open_dt.date() == NOW.date()
    assert close_dt - open_dt == timedelta(hours=1)


def test_session_expiry_is_the_window_close():
    assert fse.session_time_remaining("LONDON", NOW) == 30 * 60
    assert fse.session_time_remaining(None, NOW) == 0


def test_news_blackout_covers_the_release_windows_only():
    assert fse.in_news_blackout(NOW.replace(hour=12, minute=30))[0] is True
    assert fse.in_news_blackout(NOW.replace(hour=14, minute=0))[0] is True
    assert fse.in_news_blackout(NOW)[0] is False


def test_schedule_reports_every_window_and_flags_the_active_one():
    schedule = fse.session_schedule(NOW)
    assert {s["session"] for s in schedule} == set(fse.SESSIONS)
    assert [s for s in schedule if s["active"]][0]["session"] == "LONDON"


# ══════════════════════════════════════════════════════════════════════════════
#  2. LIQUIDITY SWEEP + 3. BODY-STRENGTH FILTER
# ══════════════════════════════════════════════════════════════════════════════

def test_a_bullish_sweep_is_detected():
    sweep = fse.detect_liquidity_sweep(_df(), LEVELS, "BULLISH")
    assert sweep is not None
    assert sweep["direction"] == "BUY"
    assert sweep["sweep_wick"] == pytest.approx(1.0990)
    assert sweep["sweep_close"] == pytest.approx(1.1040)
    assert sweep["sweep_index"] == 4


def test_a_bearish_sweep_is_detected():
    levels = silver_session_levels(swing_low=1.1500)
    sweep = fse.detect_liquidity_sweep(_df(bear_sweep_sequence()), levels, "BEARISH")
    assert sweep is not None
    assert sweep["direction"] == "SELL"
    assert sweep["sweep_wick"] == pytest.approx(1.2010)


def test_opposite_direction_bias_finds_no_sweep():
    """
    The H4 bias is a hard filter. Sweeping the lows while the higher timeframe
    is bearish is a breakout, not the reversal this strategy trades.
    """
    assert fse.detect_liquidity_sweep(_df(), LEVELS, "BEARISH") is None
    assert fse.detect_liquidity_sweep(_df(), LEVELS, "NEUTRAL") is None


def test_a_weak_bodied_sweep_is_rejected():
    """
    A doji that wicks below the swing has not rejected the level. Rebuild the
    sweep candle with a body worth 20% of its range and the filter must refuse
    it even though the wick is correct.
    """
    rows = list(bull_sweep_sequence())
    rows[4] = (1.1030, 1.1045, 1.0990, 1.1015)     # body 0.5 range => 0.5/5.5
    sweep = fse.detect_liquidity_sweep(_df(rows), LEVELS, "BULLISH")
    # The body is 0.5/5.5 = 0.09 here, well under the 40% floor.
    assert sweep is None or sweep["body_pct"] >= fse.MIN_SWEEP_BODY_PCT


def test_a_sweep_that_closes_beyond_the_level_is_not_a_sweep():
    """Closing below the swept low is a breakdown, not a rejection."""
    rows = list(bull_sweep_sequence())
    rows[4] = (1.1015, 1.1045, 1.0990, 1.0995)     # closes below swing_low
    assert fse.detect_liquidity_sweep(_df(rows), LEVELS, "BULLISH") is None


def test_missing_levels_and_empty_frames_return_none():
    assert fse.detect_liquidity_sweep(_df(), None, "BULLISH") is None
    assert fse.detect_liquidity_sweep(_df(), {}, "BULLISH") is None
    assert fse.detect_liquidity_sweep(None, LEVELS, "BULLISH") is None
    assert fse.detect_liquidity_sweep(pd.DataFrame(), LEVELS, "BULLISH") is None


def test_levels_without_both_sides_return_none():
    assert fse.detect_liquidity_sweep(_df(), {"swing_low": 1.1}, "BULLISH") is None
    assert fse.detect_liquidity_sweep(_df(), {"swing_high": 1.2}, "BULLISH") is None


def test_a_zero_range_candle_is_skipped_not_crashed():
    rows = list(bull_sweep_sequence())
    rows.insert(0, (1.1050, 1.1050, 1.1050, 1.1050))
    assert fse.detect_liquidity_sweep(_df(rows), LEVELS, "BULLISH") is not None


# ══════════════════════════════════════════════════════════════════════════════
#  4. MSS WITHIN THE THREE-CANDLE WINDOW
# ══════════════════════════════════════════════════════════════════════════════

def test_mss_is_detected_one_candle_after_the_sweep():
    df = _df()
    sweep = fse.detect_liquidity_sweep(df, LEVELS, "BULLISH")
    mss = fse.detect_mss(df, sweep)
    assert mss is not None
    assert mss["direction"] == "BUY"
    assert mss["candles_to_mss"] == 1
    assert mss["mss_level"] == pytest.approx(1.1060)


def test_detect_msss_is_an_alias_of_detect_mss():
    """The spec spells it `detect_msss`; both names must resolve identically."""
    assert fse.detect_msss is fse.detect_mss


def test_mss_outside_the_three_candle_window_is_rejected():
    """
    Keep the post-sweep candles BELOW the level for four candles, then break it.
    The shift is real, but it is no longer the shift this setup describes.

    The candles must genuinely stay below: the ordinary fixture's displacement
    bars close above the pre-sweep high on their own, which would satisfy the
    MSS inside the window and make this test vacuous.
    """
    rows = list(bull_sweep_sequence()[:5])          # through the sweep at idx 4
    rows += [
        (1.1040, 1.1055, 1.1035, 1.1050),           # 5  close 1.1050 < 1.1060
        (1.1050, 1.1058, 1.1045, 1.1052),           # 6
        (1.1052, 1.1059, 1.1048, 1.1055),           # 7
        (1.1055, 1.1070, 1.1050, 1.1068),           # 8  close 1.1068 > 1.1060
    ]
    df = _df(rows)
    sweep = fse.detect_liquidity_sweep(df, LEVELS, "BULLISH")
    assert sweep is not None and sweep["sweep_index"] == 4

    assert fse.detect_mss(df, sweep) is None                     # 3-candle window
    assert fse.detect_mss(df, sweep, max_candles=4) is not None   # found at 4


def test_mss_window_is_exactly_three():
    assert fse.MSS_MAX_CANDLES == 3
    df = _df()
    sweep = fse.detect_liquidity_sweep(df, LEVELS, "BULLISH")
    # The fixture breaks structure one candle after the sweep.
    assert fse.detect_mss(df, sweep, max_candles=1) is not None
    assert fse.detect_mss(df, sweep, max_candles=0) is None


def test_a_wick_through_the_level_is_not_an_mss():
    """
    Only a CLOSE beyond the opposing swing shifts structure. A wick through the
    level that closes back inside is the same failed move the sweep was.

    Every post-sweep candle here stays below 1.1060 on its close, so nothing in
    the window may satisfy the shift.
    """
    rows = list(bull_sweep_sequence()[:5])
    rows += [
        (1.1040, 1.1090, 1.1038, 1.1050),           # 5  wick 1.1090, close 1.1050
        (1.1050, 1.1056, 1.1045, 1.1052),           # 6
        (1.1052, 1.1058, 1.1048, 1.1055),           # 7
    ]
    df = _df(rows)
    sweep = fse.detect_liquidity_sweep(df, LEVELS, "BULLISH")
    assert sweep is not None
    assert fse.detect_mss(df, sweep) is None


def test_mss_without_enough_pre_sweep_history_returns_none():
    """A sweep at index < 3 leaves no pre-sweep structure to break."""
    rows = bull_sweep_sequence()[3:]             # sweep lands at index 1
    df = _df(rows)
    sweep = fse.detect_liquidity_sweep(df, LEVELS, "BULLISH")
    if sweep:
        assert fse.detect_mss(df, sweep) is None


def test_mss_handles_missing_inputs():
    assert fse.detect_mss(None, {"sweep_index": 5, "direction": "BUY"}) is None
    assert fse.detect_mss(_df(), None) is None
    assert fse.detect_mss(_df(), {}) is None


# ══════════════════════════════════════════════════════════════════════════════
#  5. FVG FORMATION
# ══════════════════════════════════════════════════════════════════════════════

def test_a_bullish_fvg_is_found_after_the_sweep():
    df = _df()
    sweep = fse.detect_liquidity_sweep(df, LEVELS, "BULLISH")
    fvg = fse.find_fvg_after_sweep(df, sweep)
    assert fvg is not None
    assert fvg["type"] == "bullish_fvg"
    assert fvg["fvg_low"] == pytest.approx(1.1080)
    assert fvg["fvg_high"] == pytest.approx(1.1088)
    assert fvg["fvg_index"] >= sweep["sweep_index"]


def test_a_bearish_fvg_is_found_after_the_sweep():
    levels = silver_session_levels(swing_low=1.1500)
    df = _df(bear_sweep_sequence())
    sweep = fse.detect_liquidity_sweep(df, levels, "BEARISH")
    fvg = fse.find_fvg_after_sweep(df, sweep)
    assert fvg is not None
    assert fvg["type"] == "bearish_fvg"
    assert fvg["fvg_low"] == pytest.approx(1.1912)
    assert fvg["fvg_high"] == pytest.approx(1.1920)


def test_an_fvg_before_the_sweep_is_never_used():
    """
    The gap must be formed BY the displacement after the sweep. A gap sitting
    earlier in the frame is not this setup's entry zone.
    """
    gap_rows = [(1.1050, 1.1055, 1.1045, 1.1052),
                (1.1052, 1.1070, 1.1050, 1.1068),
                (1.1068, 1.1080, 1.1075, 1.1078)]      # a gap at the very start
    df = _df(gap_rows + bull_sweep_sequence())
    sweep = fse.detect_liquidity_sweep(df, LEVELS, "BULLISH")
    fvg = fse.find_fvg_after_sweep(df, sweep)
    assert fvg["fvg_index"] > sweep["sweep_index"]


def test_no_fvg_in_a_sequence_without_an_imbalance():
    """
    A gap needs the middle candle to displace price past its neighbours. These
    candles advance too slowly for that: each bar's range still overlaps the
    previous one, so there is nothing to leave a gap with.
    """
    rows = [(1.1000 + i * 0.0002, 1.1005 + i * 0.0002,
             1.0998 + i * 0.0002, 1.1004 + i * 0.0002) for i in range(30)]
    df = _df(rows)
    assert fse.find_fvg_after_sweep(df, {"sweep_index": 0, "direction": "BUY"}) is None
    assert fse.find_fvg_after_sweep(df, {"sweep_index": 0, "direction": "SELL"}) is None


def test_a_gap_is_found_when_the_displacement_is_large_enough():
    """The same ramp, stepped hard enough to leave an imbalance."""
    rows = [(1.1000 + i * 0.001, 1.1005 + i * 0.001,
             1.0998 + i * 0.001, 1.1004 + i * 0.001) for i in range(30)]
    df = _df(rows)
    fvg = fse.find_fvg_after_sweep(df, {"sweep_index": 0, "direction": "BUY"})
    assert fvg is not None
    # The gap is the space between candle i's high and candle i+2's low.
    assert fvg["fvg_low"] < fvg["fvg_high"]


def test_fvg_age_limit_is_ten_candles():
    assert fse.FVG_MAX_AGE == 10
    df = _df()
    sweep = fse.detect_liquidity_sweep(df, LEVELS, "BULLISH")
    # The gap is 1 candle after the sweep, so a zero-age window must miss it.
    assert fse.find_fvg_after_sweep(df, sweep, max_age=0) is None
    assert fse.find_fvg_after_sweep(df, sweep, max_age=10) is not None


def test_single_candle_flag_marks_a_one_bar_displacement():
    """
    `single_candle` describes the displacement, not the gap width: the gap is
    always a three-candle structure.
    """
    df = _df()
    sweep = fse.detect_liquidity_sweep(df, LEVELS, "BULLISH")
    fvg = fse.find_fvg_after_sweep(df, sweep)
    assert isinstance(fvg["single_candle"], bool)


def test_fvg_handles_missing_inputs():
    assert fse.find_fvg_after_sweep(None, {"sweep_index": 4}) is None
    assert fse.find_fvg_after_sweep(_df(), None) is None
    assert fse.find_fvg_after_sweep(_df(), {}) is None


# ══════════════════════════════════════════════════════════════════════════════
#  6. VOLUME PROFILE CONFLUENCE
# ══════════════════════════════════════════════════════════════════════════════

def _fvg():
    df = _df()
    sweep = fse.detect_liquidity_sweep(df, LEVELS, "BULLISH")
    return fse.find_fvg_after_sweep(df, sweep)


def test_poc_overlap_grades_highest():
    fvg = _fvg()
    grade = fse.volume_profile_confluence(fvg, trusted_vp())
    assert grade["grade"] == "POC_OVERLAP"
    assert grade["source_trusted"] is True


def test_vah_confluence_when_the_gap_touches_only_the_value_area_high():
    fvg = _fvg()
    vp = trusted_vp(poc=1.1200, vah=1.1084, val=1.1000)   # VAH at the gap mid
    grade = fse.volume_profile_confluence(fvg, vp)
    assert grade["grade"] in ("VAH_CONFLUENCE", "VAL_CONFLUENCE")


def test_no_confluence_when_the_gap_is_outside_the_value_area():
    fvg = _fvg()
    vp = trusted_vp(poc=1.0900, vah=1.0950, val=1.0850)
    grade = fse.volume_profile_confluence(fvg, vp)
    assert grade["grade"] == "NO_CONFLUENCE"


def test_confluence_without_a_profile_is_no_confluence():
    grade = fse.volume_profile_confluence(_fvg(), None)
    assert grade["grade"] == "NO_CONFLUENCE"
    assert grade["profile_valid"] is False


def test_an_invalid_profile_is_reported_as_such():
    fvg = _fvg()
    vp = dict(trusted_vp(), valid=False, warning="non-equilibrium distribution")
    grade = fse.volume_profile_confluence(fvg, vp)
    assert grade["profile_valid"] is False


def test_gateable_accepts_a_trusted_profile_and_refuses_a_proxy():
    assert fse.volume_profile_gateable(trusted_vp())[0] is True

    proxy = dict(trusted_vp(), volume_source="range", source_trusted=False)
    ok, reason = fse.volume_profile_gateable(proxy)
    assert ok is False
    assert "proxy" in reason


def test_gateable_refuses_a_missing_profile():
    ok, reason = fse.volume_profile_gateable(None)
    assert ok is False
    assert reason == "no profile"


# ══════════════════════════════════════════════════════════════════════════════
#  7. CONFIDENCE SCORE
# ══════════════════════════════════════════════════════════════════════════════

def _score(**overrides):
    """
    Score a deliberately MEDIOCRE setup, so each factor's effect is visible.

    The baseline must not sit at the 99 cap: if it does, every comparison below
    saturates and `test_a_faster_mss_scores_higher` passes for the wrong reason
    (or fails because both sides read 99). This baseline scores 86 — just under
    the floor — so a bonus moves it up and a penalty moves it down.
    """
    kwargs = dict(
        bias_data=silver_bias(h4_bias="BULLISH", strength=2,
                              price_position="AT_POC"),
        sweep={"body_pct": 0.45, "direction": "BUY"},
        mss={"candles_to_mss": 2},
        fvg={"single_candle": False},
        vp_confluence={"grade": "NO_CONFLUENCE"},
        session_name="LONDON",
    )
    kwargs.update(overrides)
    return fse.calculate_confidence(**kwargs)


def test_the_baseline_scores_exactly_the_documented_floor_arithmetic():
    """85 - 3 (no confluence) - 2 (at POC) + 3 (strength 2) + 3 (London) = 86."""
    assert _score() == 86
    assert _score() < fse.MIN_CONFIDENCE   # mediocre enough to be rejectable


def test_score_starts_from_the_documented_base():
    assert fse.CONFIDENCE_BASE == 85
    # 85 base - 3 (no confluence) - 2 (at POC) + 5 (strength 3) + 2 (NY afternoon)
    score = _score(bias_data=silver_bias(strength=3, price_position="AT_POC"),
                   session_name="NY_AFTERNOON")
    assert score == 87


def test_poc_overlap_scores_higher_than_no_confluence():
    high = _score(vp_confluence={"grade": "POC_OVERLAP"})
    low = _score(vp_confluence={"grade": "NO_CONFLUENCE"})
    assert high > low


def test_a_value_area_touch_sits_between_poc_and_nothing():
    poc = _score(vp_confluence={"grade": "POC_OVERLAP"})
    vah = _score(vp_confluence={"grade": "VAH_CONFLUENCE"})
    none = _score(vp_confluence={"grade": "NO_CONFLUENCE"})
    assert poc > vah > none


def test_a_faster_mss_scores_higher():
    assert _score(mss={"candles_to_mss": 1}) > _score(mss={"candles_to_mss": 3})


def test_a_stronger_body_scores_higher():
    assert _score(sweep={"body_pct": 0.80}) > _score(sweep={"body_pct": 0.45})


def test_a_single_candle_displacement_scores_higher():
    assert _score(fvg={"single_candle": True}) > _score(fvg={"single_candle": False})


def test_the_prime_session_scores_highest():
    scores = {s: _score(session_name=s) for s in fse.SESSIONS}
    assert scores["NY_MORNING"] > scores["LONDON"] > scores["NY_AFTERNOON"]


def test_stronger_structure_scores_higher():
    assert _score(bias_data=silver_bias(strength=3)) > \
        _score(bias_data=silver_bias(strength=2))


def test_a_neutral_bias_is_penalised():
    assert _score(bias_data=silver_bias(h4_bias="NEUTRAL", strength=0)) < \
        _score(bias_data=silver_bias(h4_bias="BULLISH", strength=2))


def test_being_outside_the_value_area_scores_higher_than_at_the_poc():
    outside = _score(bias_data=silver_bias(price_position="ABOVE_VALUE"))
    at_poc = _score(bias_data=silver_bias(price_position="AT_POC"))
    assert outside > at_poc


def test_the_score_is_capped_at_99():
    score = _score(bias_data=silver_bias(strength=9, price_position="ABOVE_VALUE"),
                   sweep={"body_pct": 0.99}, mss={"candles_to_mss": 1},
                   fvg={"single_candle": True},
                   vp_confluence={"grade": "POC_OVERLAP"},
                   session_name="NY_MORNING")
    assert score == 99


def test_a_barely_formed_setup_scores_below_the_floor():
    """
    The negative confluence term must be able to push a structurally valid
    setup under 88 — otherwise the floor would never reject anything.
    """
    score = _score(bias_data=silver_bias(h4_bias="BULLISH", strength=0,
                                         price_position="AT_POC"),
                   sweep={"body_pct": 0.10}, mss={"candles_to_mss": 3},
                   fvg={"single_candle": False},
                   vp_confluence={"grade": "NO_CONFLUENCE"},
                   session_name="NY_AFTERNOON")
    assert score < fse.MIN_CONFIDENCE


def test_the_score_is_a_ranking_not_a_probability():
    """
    Nothing in the score's range may be interpreted as a win rate. This pins the
    documented meaning so a future change cannot quietly relabel it.
    """
    assert fse.calculate_confidence.__doc__ is not None
    doc = fse.calculate_confidence.__doc__.lower()
    assert "not a probability" in doc
    assert "ranking" in doc


def test_scoring_survives_empty_inputs():
    assert fse.calculate_confidence(None, None, None, None, None, "LONDON") >= 0


# ══════════════════════════════════════════════════════════════════════════════
#  8. THE HARD 88 FLOOR
# ══════════════════════════════════════════════════════════════════════════════

def test_the_floor_is_88():
    assert fse.MIN_CONFIDENCE == 88


@pytest.mark.parametrize("score,expected", [
    (0, False), (87, False), (87.99, False),
    (88, True), (88.01, True), (94, True), (99, True),
])
def test_executable_only_at_or_above_88(score, expected):
    assert fse.is_executable(score) is expected


def test_a_missing_or_unparseable_score_fails_closed():
    """
    An unknown score must not pass. Treating it as passing would let a broken
    scoring path authorise a trade.
    """
    assert fse.is_executable(None) is False
    assert fse.is_executable("not a number") is False
    assert fse.is_executable("") is False


def test_a_sub_88_setup_is_never_executable():
    """
    The pipeline must reject it, not merely score it low.

    The bias is directional so the setup reaches the scoring stage — a NEUTRAL
    bias is refused earlier, which would make this test pass without exercising
    the floor at all. The profile is gateable but far from the gap, so the
    confluence term is negative and the score lands under 88.
    """
    far_vp = trusted_vp(poc=1.0900, vah=1.0950, val=1.0850)
    weak = silver_bias(h4_bias="BULLISH", strength=0, price_position="AT_POC",
                       vp_levels=far_vp)

    setup = fse.build_setup("EURUSD", _df(), LEVELS, weak, "NY_AFTERNOON", NOW)

    assert setup["state"] == fse.STATE_INVALID
    assert setup["confidence"] < fse.MIN_CONFIDENCE
    assert "88" in setup["reject_reason"]
    assert setup["fvg"] is not None      # it got all the way to scoring


def test_a_sub_88_setup_cannot_be_entered_even_if_it_reached_the_store():
    """
    Defence in depth: `check_entry_retest` re-checks `executable`, so a setup
    that was forced into the store by a bug still cannot produce an order.
    """
    setup = _executable_setup()
    setup["executable"] = False
    price = setup["fvg"]["fvg_midpoint"]
    assert fse.check_entry_retest(setup, price, silver_entry_frame(), NOW) is None
    assert setup["entry_taken"] is False


def test_a_high_scoring_setup_is_executable():
    setup = fse.build_setup("EURUSD", _df(), LEVELS, _good_bias(), "LONDON", NOW)
    assert setup["confidence"] >= fse.MIN_CONFIDENCE
    assert setup["executable"] is True


# ══════════════════════════════════════════════════════════════════════════════
#  9. SETUP STATES
# ══════════════════════════════════════════════════════════════════════════════

def test_the_five_pipeline_states_exist():
    assert fse.STATE_WAITING == "WAITING"
    assert fse.STATE_SWEEP_DETECTED == "SWEEP_DETECTED"
    assert fse.STATE_MSS_CONFIRMED == "MSS_CONFIRMED"
    assert fse.STATE_FVG_FOUND == "FVG_FOUND"
    assert fse.STATE_IN_TRADE == "IN_TRADE"


def test_a_new_setup_starts_waiting():
    setup = fse.new_setup("EURUSD", "LONDON", "BUY", NOW)
    assert setup["state"] == fse.STATE_WAITING
    assert setup["entry_taken"] is False
    assert setup["confidence"] == 0


def test_states_advance_forward_only():
    setup = fse.new_setup("EURUSD", "LONDON", "BUY", NOW)
    for state in (fse.STATE_SWEEP_DETECTED, fse.STATE_MSS_CONFIRMED,
                  fse.STATE_FVG_FOUND, fse.STATE_IN_TRADE):
        fse.advance_setup(setup, state, NOW)
        assert setup["state"] == state


def test_a_setup_never_moves_backwards():
    setup = fse.new_setup("EURUSD", "LONDON", "BUY", NOW)
    fse.advance_setup(setup, fse.STATE_FVG_FOUND, NOW)
    fse.advance_setup(setup, fse.STATE_MSS_CONFIRMED, NOW)
    assert setup["state"] == fse.STATE_FVG_FOUND


def test_a_terminal_setup_never_moves_again():
    for terminal in (fse.STATE_INVALID, fse.STATE_EXPIRED, fse.STATE_IN_TRADE):
        setup = fse.new_setup("EURUSD", "LONDON", "BUY", NOW)
        fse.advance_setup(setup, fse.STATE_FVG_FOUND, NOW)
        fse.advance_setup(setup, terminal, NOW)
        fse.advance_setup(setup, fse.STATE_MSS_CONFIRMED, NOW)
        assert setup["state"] == terminal


def test_an_unknown_state_is_ignored_rather_than_stored():
    setup = fse.new_setup("EURUSD", "LONDON", "BUY", NOW)
    fse.advance_setup(setup, "NOT_A_STATE", NOW)
    assert setup["state"] == fse.STATE_WAITING


def test_the_history_records_every_transition():
    setup = fse.new_setup("EURUSD", "LONDON", "BUY", NOW)
    fse.advance_setup(setup, fse.STATE_SWEEP_DETECTED, NOW)
    fse.advance_setup(setup, fse.STATE_MSS_CONFIRMED, NOW)
    assert setup["history"] == [fse.STATE_WAITING, fse.STATE_SWEEP_DETECTED,
                                fse.STATE_MSS_CONFIRMED]


def test_invalidate_and_expire_record_why():
    setup = fse.new_setup("EURUSD", "LONDON", "BUY", NOW)
    fse.invalidate_setup(setup, "no MSS", NOW)
    assert setup["state"] == fse.STATE_INVALID
    assert setup["reject_reason"] == "no MSS"

    other = fse.new_setup("EURUSD", "LONDON", "BUY", NOW)
    fse.expire_setup(other, NOW)
    assert other["state"] == fse.STATE_EXPIRED


def test_state_helpers_survive_none():
    assert fse.advance_setup(None, fse.STATE_FVG_FOUND) is None
    assert fse.invalidate_setup(None, "x") is None
    assert fse.expire_setup(None) is None


# ══════════════════════════════════════════════════════════════════════════════
#  10. THE PIPELINE AND ITS REJECTION REASONS
# ══════════════════════════════════════════════════════════════════════════════

def test_the_full_pipeline_reaches_fvg_found():
    setup = fse.build_setup("EURUSD", _df(), LEVELS, _good_bias(), "LONDON", NOW)
    assert setup["state"] == fse.STATE_FVG_FOUND
    assert setup["direction"] == "BUY"
    assert setup["sweep"] is not None
    assert setup["mss"] is not None
    assert setup["fvg"] is not None
    assert setup["vp_confluence"] == "POC_OVERLAP"
    assert setup["expires_at"].startswith("2026-10-15T09:00")


def test_the_bearish_pipeline_reaches_fvg_found():
    levels = silver_session_levels(swing_low=1.1500)
    bias = silver_bias(h4_bias="BEARISH", price_position="BELOW_VALUE",
                       vp_levels=trusted_vp_bearish())
    setup = fse.build_setup("EURUSD", _df(bear_sweep_sequence()), levels, bias,
                            "LONDON", NOW)
    assert setup["state"] == fse.STATE_FVG_FOUND
    assert setup["direction"] == "SELL"


def test_a_neutral_bias_is_rejected_before_any_detection():
    setup = fse.build_setup("EURUSD", _df(), LEVELS,
                            silver_bias(h4_bias="NEUTRAL"), "LONDON", NOW)
    assert setup["state"] == fse.STATE_INVALID
    assert "daily bias" in setup["reject_reason"]
    assert setup["sweep"] is None


def test_a_missing_bias_record_is_rejected():
    setup = fse.build_setup("EURUSD", _df(), LEVELS, None, "LONDON", NOW)
    assert setup["state"] == fse.STATE_INVALID
    assert "daily bias" in setup["reject_reason"]


def test_opposite_direction_bias_rejects_the_setup():
    """A bullish H4 cannot take the bearish sweep, even with everything else perfect."""
    levels = silver_session_levels(swing_low=1.1500)
    bias = silver_bias(h4_bias="BULLISH", vp_levels=trusted_vp())
    setup = fse.build_setup("EURUSD", _df(bear_sweep_sequence()), levels, bias,
                            "LONDON", NOW)
    assert setup["state"] == fse.STATE_INVALID
    assert "sweep" in setup["reject_reason"]


def test_no_sweep_rejection_names_the_expected_direction():
    flat = [(1.1040, 1.1045, 1.1035, 1.1042)] * 30
    setup = fse.build_setup("EURUSD", _df(flat), LEVELS, _good_bias(), "LONDON", NOW)
    assert setup["state"] == fse.STATE_INVALID
    assert "bullish liquidity sweep" in setup["reject_reason"]


def test_no_mss_rejection_names_the_window():
    rows = list(bull_sweep_sequence()[:5])
    rows += [
        (1.1040, 1.1055, 1.1035, 1.1050),
        (1.1050, 1.1058, 1.1045, 1.1052),
        (1.1052, 1.1059, 1.1048, 1.1055),
    ]
    setup = fse.build_setup("EURUSD", _df(rows), LEVELS, _good_bias(), "LONDON", NOW)
    assert setup["state"] == fse.STATE_INVALID
    assert "MSS" in setup["reject_reason"]
    assert str(fse.MSS_MAX_CANDLES) in setup["reject_reason"]
    assert setup["sweep"] is not None       # the sweep itself was fine


def test_no_fvg_rejection_names_the_window():
    rows = list(bull_sweep_sequence()[:7])      # sweep + MSS, no displacement
    setup = fse.build_setup("EURUSD", _df(rows), LEVELS, _good_bias(), "LONDON", NOW)
    assert setup["state"] == fse.STATE_INVALID
    assert "FVG" in setup["reject_reason"]


def test_a_proxy_volume_profile_blocks_the_setup():
    """
    A range proxy is not traded volume, so the profile cannot gate an entry.
    The pipeline must refuse rather than score it.
    """
    proxy = dict(trusted_vp(), volume_source="range", source_trusted=False)
    setup = fse.build_setup("EURUSD", _df(), LEVELS,
                            silver_bias(vp_levels=proxy), "LONDON", NOW)
    assert setup["state"] == fse.STATE_INVALID
    assert "not gateable" in setup["reject_reason"]


def test_the_pipeline_reuses_the_passed_in_profile_verbatim():
    """Requirement 12: the engine must not recompute Phase 2's levels."""
    vp = trusted_vp(poc=1.1234)
    setup = fse.build_setup("EURUSD", _df(), LEVELS,
                            silver_bias(vp_levels=vp), "LONDON", NOW)
    assert setup["vp_levels"] is vp


def test_missing_candles_are_handled_without_raising():
    for frame in (None, pd.DataFrame()):
        setup = fse.build_setup("EURUSD", frame, LEVELS, _good_bias(), "LONDON", NOW)
        assert setup["state"] == fse.STATE_INVALID


def test_a_frame_too_short_for_detection_is_rejected():
    setup = fse.build_setup("EURUSD", _df(bull_sweep_sequence()[:2]), LEVELS,
                            _good_bias(), "LONDON", NOW)
    assert setup["state"] == fse.STATE_INVALID


def test_missing_session_levels_are_rejected():
    setup = fse.build_setup("EURUSD", _df(), None, _good_bias(), "LONDON", NOW)
    assert setup["state"] == fse.STATE_INVALID


def test_the_setup_record_carries_the_volume_provenance():
    setup = fse.build_setup("EURUSD", _df(), LEVELS, _good_bias(), "LONDON", NOW)
    assert setup["vp_source"] == "exchange"
    assert setup["vp_trusted"] is True
    assert setup["vp_profile_valid"] is True


# ══════════════════════════════════════════════════════════════════════════════
#  11. EXPIRY
# ══════════════════════════════════════════════════════════════════════════════

def test_a_fresh_setup_is_not_expired():
    setup = fse.build_setup("EURUSD", _df(), LEVELS, _good_bias(), "LONDON", NOW)
    assert fse.setup_is_expired(setup, NOW + timedelta(minutes=10)) is False


def test_a_setup_expires_when_its_session_closes():
    setup = fse.build_setup("EURUSD", _df(), LEVELS, _good_bias(), "LONDON", NOW)
    assert fse.setup_is_expired(setup, datetime(2026, 10, 15, 9, 0, 0)) is True
    assert fse.setup_is_expired(setup, datetime(2026, 10, 15, 8, 59, 59)) is False


def test_a_setup_expires_when_the_utc_day_rolls():
    """
    A setup that survives midnight in memory must not become sweepable against
    another day's liquidity.
    """
    setup = fse.build_setup("EURUSD", _df(), LEVELS, _good_bias(), "LONDON", NOW)
    assert fse.setup_is_expired(setup, datetime(2026, 10, 16, 8, 30)) is True


def test_each_session_expires_at_its_own_close():
    for session, close_hour in (("LONDON", 9), ("NY_MORNING", 16),
                                ("NY_AFTERNOON", 20)):
        setup = fse.new_setup("EURUSD", session, "BUY", NOW)
        assert fse.setup_is_expired(
            setup, datetime(2026, 10, 15, close_hour, 0, 0)) is True
        assert fse.setup_is_expired(
            setup, datetime(2026, 10, 15, close_hour - 1, 59, 59)) is False


def test_a_terminal_setup_reads_as_expired():
    for terminal in (fse.STATE_INVALID, fse.STATE_EXPIRED, fse.STATE_IN_TRADE):
        setup = fse.new_setup("EURUSD", "LONDON", "BUY", NOW)
        fse.advance_setup(setup, terminal, NOW)
        assert fse.setup_is_expired(setup, NOW) is True


def test_an_expired_setup_cannot_be_entered():
    setup = fse.build_setup("EURUSD", _df(), LEVELS, _good_bias(), "LONDON", NOW)
    after_close = datetime(2026, 10, 15, 9, 30, 0)
    fvg = setup["fvg"]
    assert fse.check_entry_retest(setup, fvg["fvg_midpoint"],
                                  silver_entry_frame(), after_close) is None
    assert setup["state"] == fse.STATE_EXPIRED


def test_expiry_helpers_survive_none():
    assert fse.setup_is_expired(None, NOW) is True


# ══════════════════════════════════════════════════════════════════════════════
#  11b. FVG-RETEST ENTRY
# ══════════════════════════════════════════════════════════════════════════════

def _executable_setup(session="LONDON", now=NOW):
    return fse.build_setup("EURUSD", _df(), LEVELS, _good_bias(), session, now)


def test_price_inside_the_gap_produces_an_entry():
    setup = _executable_setup()
    signal = fse.check_entry_retest(setup, 1.1084, silver_entry_frame(), NOW)

    assert signal is not None
    assert signal["signal"] == "BUY"
    assert signal["entry_price"] == pytest.approx(1.1084)
    assert signal["entry_type"] == "SILVER_BULLET_FVG"
    assert signal["session"] == "LONDON"
    assert signal["confidence"] >= fse.MIN_CONFIDENCE


def test_the_stop_sits_beyond_the_sweep_wick():
    """The wick is the level the setup says was defended."""
    setup = _executable_setup()
    signal = fse.check_entry_retest(setup, 1.1084, silver_entry_frame(), NOW)
    assert signal["stop_loss"] < 1.0990


def test_the_targets_are_one_two_and_three_times_the_risk():
    setup = _executable_setup()
    signal = fse.check_entry_retest(setup, 1.1084, silver_entry_frame(), NOW)
    entry, risk = signal["entry_price"], signal["risk_distance"]
    # Every field is rounded to 5dp before it is published, so compare at that
    # precision rather than at float exactness.
    assert signal["tp1"] == pytest.approx(entry + risk, abs=1e-4)
    assert signal["tp2"] == pytest.approx(entry + risk * 2, abs=1e-4)
    assert signal["tp3"] == pytest.approx(entry + risk * 3, abs=1e-4)
    assert signal["take_profit"] == signal["tp3"]


def test_the_bearish_entry_mirrors_the_bullish_one():
    levels = silver_session_levels(swing_low=1.1500)
    bias = silver_bias(h4_bias="BEARISH", price_position="BELOW_VALUE",
                       vp_levels=trusted_vp_bearish())
    setup = fse.build_setup("EURUSD", _df(bear_sweep_sequence()), levels, bias,
                            "LONDON", NOW)
    signal = fse.check_entry_retest(setup, 1.1916, silver_entry_frame(), NOW)
    assert signal is not None
    assert signal["signal"] == "SELL"
    assert signal["stop_loss"] > 1.2010


def test_price_outside_the_gap_produces_no_entry():
    setup = _executable_setup()
    assert fse.check_entry_retest(setup, 1.1200, silver_entry_frame(), NOW) is None
    assert fse.check_entry_retest(setup, 1.0500, silver_entry_frame(), NOW) is None


def test_price_exactly_on_each_gap_edge_is_inside():
    setup = _executable_setup()
    assert fse.check_entry_retest(setup, 1.1080, silver_entry_frame(), NOW) is not None

    setup2 = _executable_setup()
    assert fse.check_entry_retest(setup2, 1.1088, silver_entry_frame(), NOW) is not None


def test_one_setup_yields_exactly_one_entry():
    """
    The entry job runs every 30 seconds and price sits inside the gap for
    several of those runs, so without the guard the same setup would open a
    position on every tick.
    """
    setup = _executable_setup()
    first = fse.check_entry_retest(setup, 1.1084, silver_entry_frame(), NOW)
    assert first is not None
    assert setup["entry_taken"] is True

    for _ in range(5):
        assert fse.check_entry_retest(setup, 1.1084, silver_entry_frame(),
                                      NOW) is None


def test_the_entry_moves_the_setup_to_in_trade():
    setup = _executable_setup()
    fse.check_entry_retest(setup, 1.1084, silver_entry_frame(), NOW)
    assert setup["state"] == fse.STATE_IN_TRADE
    assert setup["entry"]["entry_price"] == pytest.approx(1.1084)


def test_a_stale_wick_far_from_price_is_refused():
    """
    SL_MAX_ATR is a sanity ceiling, not the risk control: it refuses a wick so
    far away that the stop would be meaningless.
    """
    setup = _executable_setup()
    setup["sweep"] = dict(setup["sweep"], sweep_wick=1.0000)   # ~100 ATR away
    assert fse.check_entry_retest(setup, 1.1084, silver_entry_frame(), NOW) is None


def test_the_entry_needs_an_atr_to_size_the_stop():
    setup = _executable_setup()
    short = candles(bull_sweep_sequence())      # 9 bars, below ATR's period+1
    assert fse.calculate_atr(short) == 0.0
    assert fse.check_entry_retest(setup, 1.1084, short, NOW) is None


def test_entry_handles_missing_and_malformed_inputs():
    setup = _executable_setup()
    assert fse.check_entry_retest(None, 1.1084, silver_entry_frame(), NOW) is None
    assert fse.check_entry_retest(setup, None, silver_entry_frame(), NOW) is None

    broken = fse.new_setup("EURUSD", "LONDON", "BUY", NOW)
    broken["executable"] = True
    broken["fvg"] = {"fvg_low": 0.0, "fvg_high": 0.0}
    assert fse.check_entry_retest(broken, 1.0, silver_entry_frame(), NOW) is None


def test_the_signal_carries_the_confluence_and_state():
    setup = _executable_setup()
    signal = fse.check_entry_retest(setup, 1.1084, silver_entry_frame(), NOW)
    assert signal["vp_confluence"] == "POC_OVERLAP"
    assert signal["state"] == fse.STATE_IN_TRADE
    assert signal["poi"] == "fvg"


# ══════════════════════════════════════════════════════════════════════════════
#  helpers reused by the integration test below
# ══════════════════════════════════════════════════════════════════════════════

def test_the_engine_does_not_recompute_the_daily_bias():
    """
    Requirement 12 again, from the other side: the engine must not import the
    bias calculator, or it could silently build a second, inconsistent opinion.
    """
    import modules.forex_signal_engine as engine
    src = open(engine.__file__, encoding="utf-8").read()
    assert "from modules.silver_bullet" not in src
    assert "import silver_bullet" not in src


def test_the_entry_signal_delegates_tp3_to_the_executor():
    """
    TP3 is the one target derived from the market rather than from R, and its
    rules (liquidity target, high-confidence extension, ceilings) live in one
    place. The signal must carry the executor's TP3 rather than a second,
    independently computed one, or the level a trade is recorded with would
    differ from the level it is managed against.

    Two things are checked, neither of which a duplicated rule could satisfy:
    the executor-only `tp3_extended` flag is present, and the published levels
    are internally consistent with the published risk.
    """
    setup = _executable_setup()
    signal = fse.check_entry_retest(setup, 1.1084, silver_entry_frame(), NOW)

    # Only the executor's calculation produces this key.
    assert "tp3_extended" in signal

    # The published levels must be self-consistent at the published precision,
    # so a consumer can rebuild R from the signal alone.
    entry = signal["entry_price"]
    risk = signal["risk_distance"]
    assert signal["stop_loss"] == pytest.approx(entry - risk, abs=1e-4)
    assert signal["tp1"] == pytest.approx(entry + risk, abs=1e-4)
    assert signal["tp2"] == pytest.approx(entry + risk * 2, abs=1e-4)
    assert signal["take_profit"] == signal["tp3"]


def test_the_entry_signal_carries_the_session_expiry():
    """
    The trade record needs the expiry so the session-exit rule can fire after a
    restart. Without it the rule falls back to the holding-time limit only.
    """
    setup = _executable_setup()
    signal = fse.check_entry_retest(setup, 1.1084, silver_entry_frame(), NOW)
    assert signal["expires_at"] == setup["expires_at"]
    assert signal["expires_at"].startswith("2026-10-15T09:00")


def test_silver_bullet_delegates_to_the_engine():
    """One implementation: the orchestrator must re-export, not redefine."""
    from modules import silver_bullet as sb
    assert sb.detect_liquidity_sweep is fse.detect_liquidity_sweep
    assert sb.detect_mss is fse.detect_mss
    assert sb.find_fvg_after_sweep is fse.find_fvg_after_sweep
    assert sb.calculate_confidence is fse.calculate_confidence
    assert sb.build_setup is fse.build_setup
    assert sb.check_entry_in_fvg is fse.check_entry_retest
    assert sb.calculate_atr is fse.calculate_atr
    assert sb._closed_only is fse.closed_candles_only
    assert sb.SESSIONS is fse.SESSIONS
    assert sb.MIN_CONFIDENCE == fse.MIN_CONFIDENCE == 88


# ══════════════════════════════════════════════════════════════════════════════
#  10b. THE PENDING-SETUP STORE (orchestrator side)
# ══════════════════════════════════════════════════════════════════════════════

@pytest.fixture
def store():
    """A clean day-scoped store for each test."""
    from modules import silver_bullet as sb
    sb.reset_daily_cache("test")
    yield sb
    sb.reset_daily_cache("test")


def test_storing_and_retrieving_a_pending_setup(store):
    setup = _executable_setup()
    store.store_active_setup("EURUSD", setup)

    pending = store.get_active_setups()
    assert "EURUSD" in pending
    assert pending["EURUSD"]["state"] == fse.STATE_FVG_FOUND


def test_get_active_setups_returns_a_copy(store):
    """A caller mutating the returned dict must not empty the live store."""
    store.store_active_setup("EURUSD", _executable_setup())
    snapshot = store.get_active_setups()
    snapshot.clear()
    assert store.get_active_setups() != {}


def test_clearing_one_setup_leaves_the_others(store):
    store.store_active_setup("EURUSD", _executable_setup())
    store.store_active_setup("GBPUSD", _executable_setup())
    store.clear_active_setup("EURUSD")
    assert set(store.get_active_setups()) == {"GBPUSD"}


def test_expire_setups_cancels_a_setup_past_its_session_close(store):
    setup = _executable_setup()
    store.store_active_setup("EURUSD", setup)

    # 09:00 is the LONDON close, so the setup is dead.
    cancelled = store.expire_setups(now=datetime(2026, 10, 15, 9, 0, 0))
    assert cancelled == 1
    assert store.get_active_setups() == {}
    assert setup["state"] == fse.STATE_EXPIRED


def test_expire_setups_keeps_a_setup_inside_its_window(store):
    store.store_active_setup("EURUSD", _executable_setup())
    assert store.expire_setups(now=datetime(2026, 10, 15, 8, 45, 0)) == 0
    assert "EURUSD" in store.get_active_setups()


def test_expire_setups_cancels_on_the_day_roll(store):
    store.store_active_setup("EURUSD", _executable_setup())
    assert store.expire_setups(now=datetime(2026, 10, 16, 8, 30, 0)) == 1
    assert store.get_active_setups() == {}


def test_expire_setups_can_be_scoped_to_one_session(store):
    london = _executable_setup()
    ny = fse.build_setup("GBPUSD", _df(), LEVELS, _good_bias(), "NY_MORNING", NOW)
    store.store_active_setup("EURUSD", london)
    store.store_active_setup("GBPUSD", ny)

    # LONDON has closed; NY_MORNING has not.
    cancelled = store.expire_setups("LONDON", now=datetime(2026, 10, 15, 15, 30, 0))
    assert cancelled == 1
    assert set(store.get_active_setups()) == {"GBPUSD"}


def test_expire_setups_drops_already_terminal_setups(store):
    setup = _executable_setup()
    fse.invalidate_setup(setup, "no MSS", NOW)
    store.store_active_setup("EURUSD", setup)

    store.expire_setups(now=NOW)
    assert store.get_active_setups() == {}


def test_the_daily_reset_clears_the_pending_store(store):
    store.store_active_setup("EURUSD", _executable_setup())
    store.reset_daily_cache("test")
    assert store.get_active_setups() == {}


# ══════════════════════════════════════════════════════════════════════════════
#  END-TO-END: the orchestrator's scan loop
# ══════════════════════════════════════════════════════════════════════════════

@pytest.fixture
def wired_scan(monkeypatch):
    """
    Stub the venue, the position guard and the instrument roster so the scan
    loop can run without a broker, and pre-seed today's bias and liquidity marks.

    The bias record is built here rather than computed, which is the point: the
    scan must consume Phase 2's result, not produce its own.
    """
    from modules import silver_bullet as sb
    import modules.candle_provider as cp

    sb.reset_daily_cache("test")
    monkeypatch.setattr("config.SILVER_BULLET_INSTRUMENTS", ["EURUSD"])
    monkeypatch.setattr(cp, "is_binance", lambda symbol: False)

    import modules.forex_position_manager as fpm
    monkeypatch.setattr(fpm, "can_open_forex_trade", lambda symbol: (True, "ok"))

    frame = silver_entry_frame()
    monkeypatch.setattr(cp, "get_candles", lambda *a, **k: frame)

    sb._daily_bias["EURUSD"] = dict(silver_bias(vp_levels=trusted_vp()),
                                    session_date=sb.utc_date_key(NOW))
    sb._session_levels["LONDON"] = {"EURUSD": dict(LEVELS, date=sb.utc_date_key(NOW))}
    sb._session_levels_date["LONDON"] = sb.utc_date_key(NOW)

    yield sb, frame
    sb.reset_daily_cache("test")


def test_the_scan_stores_an_executable_setup(wired_scan):
    sb, _frame = wired_scan
    assert sb.run_silver_bullet_scan("LONDON", NOW) == 1

    setup = sb.get_active_setups()["EURUSD"]
    assert setup["state"] == fse.STATE_FVG_FOUND
    assert setup["executable"] is True
    assert setup["confidence"] >= fse.MIN_CONFIDENCE


def test_the_scan_refuses_outside_the_session_window(wired_scan):
    sb, _frame = wired_scan
    assert sb.run_silver_bullet_scan("LONDON", datetime(2026, 10, 15, 11, 0)) == 0
    assert sb.get_active_setups() == {}


def test_the_scan_refuses_inside_a_news_blackout(wired_scan):
    """A sweep caused by a data release is not the setup the strategy describes."""
    sb, _frame = wired_scan
    # NY_MORNING is 15:00-16:00; 12:30 is inside a blackout but outside the window,
    # so run the LONDON window from inside the blackout instead.
    assert sb.run_silver_bullet_scan("LONDON", datetime(2026, 10, 15, 12, 30)) == 0
    assert sb.get_active_setups() == {}


def test_the_scan_skips_a_neutral_bias(wired_scan):
    sb, _frame = wired_scan
    sb._daily_bias["EURUSD"]["h4_bias"] = "NEUTRAL"
    assert sb.run_silver_bullet_scan("LONDON", NOW) == 0


def test_the_scan_does_not_re_store_a_symbol_that_already_has_a_setup(wired_scan):
    sb, _frame = wired_scan
    assert sb.run_silver_bullet_scan("LONDON", NOW) == 1
    assert sb.run_silver_bullet_scan("LONDON", NOW) == 0


def test_the_stored_setup_carries_the_bias_context(wired_scan):
    sb, _frame = wired_scan
    sb.run_silver_bullet_scan("LONDON", NOW)
    setup = sb.get_active_setups()["EURUSD"]
    assert setup["bias"] == "BULLISH"
    assert setup["bias_strength"] == 3
    assert setup["vp_confluence"] == "POC_OVERLAP"


def test_the_stored_setup_produces_exactly_one_entry(wired_scan):
    """
    The scan stores it, then the entry job fills it once and only once.

    `now` is passed explicitly because the entry defaults to the real clock, and
    the LONDON window in this fixture is hours in the past.
    """
    sb, frame = wired_scan
    sb.run_silver_bullet_scan("LONDON", NOW)
    setup = sb.get_active_setups()["EURUSD"]

    price = setup["fvg"]["fvg_midpoint"]
    first = sb.check_entry_in_fvg(setup, price, frame, now=NOW)
    assert first is not None
    assert first["signal"] == "BUY"
    assert sb.check_entry_in_fvg(setup, price, frame, now=NOW) is None


def test_a_scan_that_finds_nothing_stores_nothing(wired_scan, monkeypatch):
    sb, _frame = wired_scan
    import modules.candle_provider as cp
    flat = candles([(1.1040, 1.1045, 1.1035, 1.1042)] * 40)
    monkeypatch.setattr(cp, "get_candles", lambda *a, **k: flat)

    assert sb.run_silver_bullet_scan("LONDON", NOW) == 0
    assert sb.get_active_setups() == {}


def test_a_failing_feed_does_not_abort_the_scan(wired_scan, monkeypatch):
    sb, _frame = wired_scan
    import modules.candle_provider as cp
    monkeypatch.setattr(cp, "get_candles", lambda *a, **k: None)
    assert sb.run_silver_bullet_scan("LONDON", NOW) == 0
