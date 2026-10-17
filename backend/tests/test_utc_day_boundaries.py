"""
backend/tests/test_utc_day_boundaries.py
Phase 2 — UTC day boundaries, the previous-day window, and daily cache resets.

Every daily artefact in this project (bias, previous-day profile, session
liquidity marks) is keyed on the UTC date. These tests pin the boundary
arithmetic, because an off-by-hours window is invisible until it silently
profiles the wrong day.
"""
import pandas as pd
import pytest

from tests.helpers import candles
from modules import volume_profile as vp


UTC = "UTC"


# ── utc_day_bounds ────────────────────────────────────────────────────────────

def test_day_bounds_are_midnight_to_midnight_tz_aware():
    start, end = vp.utc_day_bounds(pd.Timestamp("2026-10-15 13:45:22", tz=UTC))
    assert start == pd.Timestamp("2026-10-15 00:00:00", tz=UTC)
    assert end == pd.Timestamp("2026-10-16 00:00:00", tz=UTC)
    assert start.tzinfo is not None and end.tzinfo is not None


def test_day_bounds_accept_a_naive_timestamp_as_utc():
    """A naive timestamp must be read as UTC, not as local time."""
    start, end = vp.utc_day_bounds(pd.Timestamp("2026-10-15 23:59:59"))
    assert start == pd.Timestamp("2026-10-15 00:00:00", tz=UTC)
    assert end == pd.Timestamp("2026-10-16 00:00:00", tz=UTC)


def test_day_bounds_convert_a_non_utc_aware_timestamp():
    """
    01:30 in UTC+2 is 23:30 the PREVIOUS day in UTC. Deriving the boundary from
    the local wall clock is the classic way to profile the wrong day.
    """
    local = pd.Timestamp("2026-10-15 01:30:00", tz="Etc/GMT-2")
    start, _end = vp.utc_day_bounds(local)
    assert start == pd.Timestamp("2026-10-14 00:00:00", tz=UTC)


def test_day_bounds_are_exactly_24_hours():
    for ts in ("2026-03-29 12:00", "2026-10-25 12:00", "2026-01-01 00:00"):
        start, end = vp.utc_day_bounds(pd.Timestamp(ts, tz=UTC))
        assert end - start == pd.Timedelta(days=1)


def test_previous_day_bounds_immediately_precede_today():
    now = pd.Timestamp("2026-10-15 09:00:00", tz=UTC)
    today_start, _ = vp.utc_day_bounds(now)
    prev_start, prev_end = vp.previous_day_bounds(now)

    assert prev_end == today_start
    assert prev_start == pd.Timestamp("2026-10-14 00:00:00", tz=UTC)
    assert prev_end - prev_start == pd.Timedelta(days=1)


def test_boundaries_roll_at_midnight_not_at_the_session_open():
    just_before = pd.Timestamp("2026-10-15 23:59:59", tz=UTC)
    just_after = pd.Timestamp("2026-10-16 00:00:01", tz=UTC)

    assert vp.utc_date_key(just_before) == "2026-10-15"
    assert vp.utc_date_key(just_after) == "2026-10-16"

    # The previous day flips with it.
    assert vp.previous_day_bounds(just_before)[0] == \
        pd.Timestamp("2026-10-14 00:00:00", tz=UTC)
    assert vp.previous_day_bounds(just_after)[0] == \
        pd.Timestamp("2026-10-15 00:00:00", tz=UTC)


def test_date_key_is_a_sortable_iso_date():
    key = vp.utc_date_key(pd.Timestamp("2026-03-07 05:00:00", tz=UTC))
    assert key == "2026-03-07"
    assert len(key) == 10
    assert key == str(pd.Timestamp("2026-03-07").date())


# ── slice_utc_window ──────────────────────────────────────────────────────────

def test_slice_window_is_half_open():
    """[start, end) — the end bar belongs to the NEXT window."""
    df = candles([(100.0 + i, 101.0 + i, 99.0 + i, 100.5 + i, 10.0) for i in range(24)])
    start = pd.Timestamp("2026-10-14 00:00:00", tz=UTC)
    end = pd.Timestamp("2026-10-15 00:00:00", tz=UTC)

    window = vp.slice_utc_window(df, start, end)
    assert window is not None
    assert len(window) == 24
    assert window["timestamp"].min() >= start
    assert window["timestamp"].max() < end


def test_slice_window_excludes_a_bar_exactly_on_the_end():
    df = candles([(100.0, 101.0, 99.0, 100.5, 10.0)],
                 start="2026-10-15 00:00", freq="1h")
    start = pd.Timestamp("2026-10-14 00:00:00", tz=UTC)
    end = pd.Timestamp("2026-10-15 00:00:00", tz=UTC)
    assert vp.slice_utc_window(df, start, end) is None


def test_slice_window_without_a_timestamp_column_is_refused():
    """
    Silently profiling "whatever the caller passed" is how a profile ends up
    built from a window that is not the one that was asked for, so a frame with
    no timestamp column is refused rather than accepted.
    """
    df = candles([(100.0, 101.0, 99.0, 100.5, 10.0)] * 30, with_timestamp=False)
    assert "timestamp" not in df.columns
    assert vp.slice_utc_window(
        df,
        pd.Timestamp("2026-10-14 00:00:00", tz=UTC),
        pd.Timestamp("2026-10-15 00:00:00", tz=UTC),
    ) is None


def test_slice_window_handles_unparseable_timestamps():
    df = candles([(100.0, 101.0, 99.0, 100.5, 10.0)] * 30)
    # Assign as object dtype so a bad value can actually be stored, which is what
    # a feed returning a malformed stamp produces.
    df["timestamp"] = df["timestamp"].astype(object)
    df.loc[0, "timestamp"] = "not a timestamp"
    window = vp.slice_utc_window(
        df,
        pd.Timestamp("2026-10-13 00:00:00", tz=UTC),
        pd.Timestamp("2026-10-16 00:00:00", tz=UTC),
    )
    assert window is not None
    assert len(window) == 29


def test_slice_window_accepts_naive_timestamps_in_the_frame():
    """A frame whose timestamps are naive is read as UTC, not rejected."""
    df = candles([(100.0, 101.0, 99.0, 100.5, 10.0)] * 24)
    df["timestamp"] = df["timestamp"].dt.tz_localize(None)
    window = vp.slice_utc_window(
        df,
        pd.Timestamp("2026-10-14 00:00:00", tz=UTC),
        pd.Timestamp("2026-10-15 00:00:00", tz=UTC),
    )
    assert window is not None
    assert len(window) == 24


def test_slice_window_on_none_and_empty():
    start = pd.Timestamp("2026-10-14 00:00:00", tz=UTC)
    end = pd.Timestamp("2026-10-15 00:00:00", tz=UTC)
    assert vp.slice_utc_window(None, start, end) is None
    assert vp.slice_utc_window(pd.DataFrame(), start, end) is None


# ── previous_day_profile ──────────────────────────────────────────────────────

def _two_day_frame():
    """
    48 hourly candles: day 1 (2026-10-14) sits at 100-101, day 2 (2026-10-15)
    sits at 200-201. A profile of the previous day must describe 100-101.
    """
    rows = [(100.0, 101.0, 100.0, 101.0, 100.0)] * 24
    rows += [(200.0, 201.0, 200.0, 201.0, 100.0)] * 24
    return candles(rows, start="2026-10-14 00:00", freq="1h")


def test_previous_day_profile_covers_only_the_previous_day():
    now = pd.Timestamp("2026-10-15 09:00:00", tz=UTC)
    p = vp.previous_day_profile(_two_day_frame(), now)

    assert p is not None
    assert p["window_start"] == "2026-10-14T00:00:00+00:00"
    assert p["window_end"] == "2026-10-15T00:00:00+00:00"
    assert p["window_candles"] == 24
    # Only the 100-101 day, never the 200-201 day.
    assert p["price_min"] == pytest.approx(100.0)
    assert p["price_max"] == pytest.approx(101.0)


def test_previous_day_profile_does_not_drift_with_the_scan_time():
    """
    The levels must be a function of the DATE, not of when the scan ran. The old
    trailing-window approach returned different levels at 09:00 and at 20:00 on
    the same day.
    """
    df = _two_day_frame()
    morning = vp.previous_day_profile(df, pd.Timestamp("2026-10-15 09:00:00", tz=UTC))
    evening = vp.previous_day_profile(df, pd.Timestamp("2026-10-15 20:00:00", tz=UTC))

    assert morning is not None and evening is not None
    assert morning == evening


def test_previous_day_profile_is_none_when_the_window_is_empty():
    now = pd.Timestamp("2026-10-20 09:00:00", tz=UTC)   # days away from the data
    assert vp.previous_day_profile(_two_day_frame(), now) is None


def test_previous_day_profile_is_none_below_the_candle_minimum():
    """
    Nine hourly candles is below MIN_CANDLES, so no profile is built even though
    the window is correctly bounded.
    """
    rows = [(100.0, 101.0, 100.0, 101.0, 100.0)] * (vp.MIN_CANDLES - 1)
    df = candles(rows, start="2026-10-14 00:00", freq="1h")
    now = pd.Timestamp("2026-10-15 09:00:00", tz=UTC)
    assert vp.previous_day_profile(df, now) is None


def test_previous_day_profile_accepts_exactly_the_candle_minimum():
    rows = [(100.0, 101.0, 100.0, 101.0, 100.0)] * vp.MIN_CANDLES
    df = candles(rows, start="2026-10-14 00:00", freq="1h")
    now = pd.Timestamp("2026-10-15 09:00:00", tz=UTC)
    p = vp.previous_day_profile(df, now)
    assert p is not None
    assert p["window_candles"] == vp.MIN_CANDLES


def test_previous_day_profile_is_none_for_an_unbounded_frame():
    df = candles([(100.0, 101.0, 100.0, 101.0, 100.0)] * 48, with_timestamp=False)
    assert vp.previous_day_profile(df, pd.Timestamp("2026-10-15 09:00", tz=UTC)) is None


def test_previous_day_profile_accepts_a_naive_now():
    naive = pd.Timestamp("2026-10-15 09:00:00")
    p = vp.previous_day_profile(_two_day_frame(), naive)
    assert p is not None
    assert p["window_candles"] == 24
