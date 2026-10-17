"""
backend/tests/test_session_liquidity.py
Phase 2 — pre-session liquidity levels and the session clock.

These are the pools the session is expected to sweep. The window matters: taking
the newest candles instead of the candles strictly BEFORE the open samples the
move already in progress, which makes the sweep test partly circular.
"""
from datetime import datetime, timedelta

import pandas as pd
import pytest

from tests.helpers import candles
from modules import silver_bullet as sb


UTC = "UTC"
DAY = "2026-10-15"


@pytest.fixture(autouse=True)
def clean_state():
    sb.reset_daily_cache("test")
    yield
    sb.reset_daily_cache("test")


def _frame(rows, start, freq="5min"):
    return candles(rows, start=start, freq=freq)


def _flat(count=100, start="2026-10-15 00:00"):
    return _frame([(1.1, 1.1005, 1.0995, 1.1, 10.0)] * count, start)


# ── Session clock ─────────────────────────────────────────────────────────────

def test_session_windows_match_the_configured_utc_hours():
    assert sb.current_session(datetime(2026, 10, 15, 8, 30)) == "LONDON"
    assert sb.current_session(datetime(2026, 10, 15, 15, 30)) == "NY_MORNING"
    assert sb.current_session(datetime(2026, 10, 15, 19, 30)) == "NY_AFTERNOON"


def test_outside_every_window_there_is_no_session():
    for hour in (0, 3, 7, 10, 12, 14, 17, 18, 21, 23):
        assert sb.current_session(datetime(2026, 10, 15, hour, 30)) is None


def test_session_windows_are_half_open():
    """08:00 belongs to LONDON; 09:00 does not."""
    assert sb.current_session(datetime(2026, 10, 15, 8, 0)) == "LONDON"
    assert sb.current_session(datetime(2026, 10, 15, 8, 59)) == "LONDON"
    assert sb.current_session(datetime(2026, 10, 15, 9, 0)) is None


def test_session_bounds_land_on_the_configured_hours():
    start, end = sb.session_bounds("LONDON")
    assert start.hour == 8 and end.hour == 9
    assert end - start == timedelta(hours=1)


def test_minutes_until_open_is_positive_before_and_negative_inside():
    before = datetime(2026, 10, 15, 7, 50)
    assert 0 < sb.session_minutes_until_open("LONDON", before) <= 10

    inside = datetime(2026, 10, 15, 8, 30)
    assert sb.session_minutes_until_open("LONDON", inside) < 0


def test_sessions_opening_within_finds_the_imminent_window():
    now = datetime(2026, 10, 15, 7, 57)
    assert "LONDON" in sb.sessions_opening_within(5, now)
    assert "NY_MORNING" not in sb.sessions_opening_within(5, now)


def test_sessions_opening_within_excludes_a_window_already_open():
    now = datetime(2026, 10, 15, 8, 30)
    assert sb.sessions_opening_within(5, now) == []


def test_news_blackout_covers_the_us_release_windows():
    blocked, label = sb.in_news_blackout(datetime(2026, 10, 15, 12, 30))
    assert blocked is True
    assert label is not None

    blocked, _ = sb.in_news_blackout(datetime(2026, 10, 15, 14, 0))
    assert blocked is True


def test_news_blackout_is_clear_outside_those_windows():
    blocked, label = sb.in_news_blackout(datetime(2026, 10, 15, 8, 30))
    assert blocked is False
    assert label is None


def test_session_schedule_reports_every_window():
    schedule = sb.session_schedule()
    assert {s["session"] for s in schedule} == set(sb.SESSIONS)


# ── mark_session_liquidity ────────────────────────────────────────────────────

def test_liquidity_marks_come_from_the_window_before_the_open(monkeypatch):
    """
    The 30 minutes before 08:00 is 07:30-08:00. Only those candles may define
    the swing, so the 08:00 spike must not appear in the levels.
    """
    rows = [(1.1, 1.1005, 1.0995, 1.1, 10.0)] * 90          # 00:00-07:30
    rows += [(1.1, 1.1050, 1.0990, 1.1, 10.0)] * 6          # 07:30-08:00: the pool
    rows += [(1.1, 1.2000, 1.0500, 1.1, 10.0)] * 12         # 08:00+ : the session
    df = _frame(rows, "2026-10-15 00:00")

    import modules.candle_provider as cp
    monkeypatch.setattr(cp, "get_candles", lambda *a, **k: df)

    levels = sb.mark_session_liquidity("EURUSD", "LONDON",
                                       datetime(2026, 10, 15, 7, 59))
    assert levels is not None
    assert levels["swing_high"] == pytest.approx(1.1050)
    assert levels["swing_low"] == pytest.approx(1.0990)
    assert levels["session"] == "LONDON"
    assert levels["date"] == sb.utc_date_key(datetime(2026, 10, 15, 7, 59))


def test_liquidity_marks_are_keyed_to_the_utc_day(monkeypatch):
    import modules.candle_provider as cp
    monkeypatch.setattr(cp, "get_candles",
                        lambda *a, **k: _frame(
                            [(1.1, 1.1005, 1.0995, 1.1, 10.0)] * 100,
                            "2026-10-15 00:00"))

    levels = sb.mark_session_liquidity("EURUSD", "LONDON",
                                       datetime(2026, 10, 15, 7, 59))
    assert levels["date"] == "2026-10-15"


def test_insufficient_candles_yield_no_levels(monkeypatch):
    import modules.candle_provider as cp
    monkeypatch.setattr(cp, "get_candles",
                        lambda *a, **k: _frame(
                            [(1.1, 1.1005, 1.0995, 1.1, 10.0)] * 3,
                            "2026-10-15 07:58"))

    assert sb.mark_session_liquidity("EURUSD", "LONDON",
                                     datetime(2026, 10, 15, 7, 59)) is None


def test_a_failed_feed_yields_no_levels(monkeypatch):
    import modules.candle_provider as cp
    monkeypatch.setattr(cp, "get_candles", lambda *a, **k: None)
    assert sb.mark_session_liquidity("EURUSD", "LONDON") is None


def test_a_degenerate_range_is_refused(monkeypatch):
    """
    A flat pre-session window gives swing_high == swing_low, which is not a
    liquidity pool. It is refused rather than stored as a zero-width level.
    """
    import modules.candle_provider as cp
    monkeypatch.setattr(cp, "get_candles",
                        lambda *a, **k: _frame(
                            [(1.1, 1.1, 1.1, 1.1, 10.0)] * 100,
                            "2026-10-15 00:00"))

    assert sb.mark_session_liquidity("EURUSD", "LONDON",
                                     datetime(2026, 10, 15, 7, 59)) is None


def test_a_feed_short_of_the_lookback_falls_back_to_the_newest_candles(monkeypatch):
    """
    If the 30-minute pre-session window is empty the feed is short, so the newest
    closed candles are used rather than marking nothing.
    """
    import modules.candle_provider as cp
    # Only 07:55 onwards exists, so the 07:30-08:00 window holds 1 candle.
    monkeypatch.setattr(cp, "get_candles",
                        lambda *a, **k: _frame(
                            [(1.1, 1.1005, 1.0995, 1.1, 10.0)] * 20,
                            "2026-10-15 07:55"))

    levels = sb.mark_session_liquidity("EURUSD", "LONDON",
                                       datetime(2026, 10, 15, 7, 59))
    assert levels is not None
    assert levels["source_candles"] == sb.SWING_LOOKBACK


def test_levels_are_retrievable_for_the_same_day(monkeypatch):
    import modules.candle_provider as cp
    monkeypatch.setattr(cp, "get_candles",
                        lambda *a, **k: _frame(
                            [(1.1, 1.1005, 1.0995, 1.1, 10.0)] * 100,
                            "2026-10-15 00:00"))

    now = datetime(2026, 10, 15, 7, 59)
    sb.mark_session_liquidity("EURUSD", "LONDON", now)
    got = sb.get_session_levels("EURUSD", "LONDON", now)
    assert got is not None
    assert got["swing_high"] == pytest.approx(1.1005)


def test_levels_from_a_previous_day_are_treated_as_absent(monkeypatch):
    """
    A stale pool must not be swept against today's candles.
    """
    import modules.candle_provider as cp
    monkeypatch.setattr(cp, "get_candles",
                        lambda *a, **k: _frame(
                            [(1.1, 1.1005, 1.0995, 1.1, 10.0)] * 100,
                            "2026-10-15 00:00"))

    sb.mark_session_liquidity("EURUSD", "LONDON", datetime(2026, 10, 15, 7, 59))
    tomorrow = datetime(2026, 10, 16, 7, 59)
    assert sb.get_session_levels("EURUSD", "LONDON", tomorrow) is None


def test_levels_are_scoped_per_session(monkeypatch):
    import modules.candle_provider as cp
    monkeypatch.setattr(cp, "get_candles",
                        lambda *a, **k: _frame(
                            [(1.1, 1.1005, 1.0995, 1.1, 10.0)] * 100,
                            "2026-10-15 00:00"))

    now = datetime(2026, 10, 15, 7, 59)
    sb.mark_session_liquidity("EURUSD", "LONDON", now)
    assert sb.get_session_levels("EURUSD", "NY_MORNING", now) is None


def test_unknown_symbols_and_sessions_return_none():
    assert sb.get_session_levels("NOPE", "LONDON") is None
    assert sb.get_session_levels("EURUSD", "NOPE") is None


def test_clear_session_levels_drops_one_or_all(monkeypatch):
    import modules.candle_provider as cp
    monkeypatch.setattr(cp, "get_candles",
                        lambda *a, **k: _frame(
                            [(1.1, 1.1005, 1.0995, 1.1, 10.0)] * 100,
                            "2026-10-15 00:00"))

    now = datetime(2026, 10, 15, 7, 59)
    sb.mark_session_liquidity("EURUSD", "LONDON", now)
    sb.mark_session_liquidity("EURUSD", "NY_MORNING", now)

    assert sb.clear_session_levels("LONDON") == 1
    assert sb.get_session_levels("EURUSD", "LONDON", now) is None
    assert sb.get_session_levels("EURUSD", "NY_MORNING", now) is not None

    assert sb.clear_session_levels() == 1
    assert sb.get_session_levels("EURUSD", "NY_MORNING", now) is None


def test_re_marking_rewrites_the_levels_for_the_same_day(monkeypatch):
    import modules.candle_provider as cp

    wide = _frame([(1.1, 1.1100, 1.0900, 1.1, 10.0)] * 100, "2026-10-15 00:00")
    tight = _frame([(1.1, 1.1005, 1.0995, 1.1, 10.0)] * 100, "2026-10-15 00:00")

    monkeypatch.setattr(cp, "get_candles", lambda *a, **k: wide)
    now = datetime(2026, 10, 15, 7, 59)
    sb.mark_session_liquidity("EURUSD", "LONDON", now)
    assert sb.get_session_levels("EURUSD", "LONDON", now)["swing_high"] == \
        pytest.approx(1.1100)

    monkeypatch.setattr(cp, "get_candles", lambda *a, **k: tight)
    sb.mark_session_liquidity("EURUSD", "LONDON", now)
    assert sb.get_session_levels("EURUSD", "LONDON", now)["swing_high"] == \
        pytest.approx(1.1005)


# ── pre_session_mark_liquidity ────────────────────────────────────────────────

def test_pre_session_marking_covers_every_instrument(monkeypatch):
    import modules.candle_provider as cp
    monkeypatch.setattr("config.SILVER_BULLET_INSTRUMENTS",
                        ["EURUSD", "GBPUSD", "XAUUSD"])
    monkeypatch.setattr(cp, "get_candles",
                        lambda *a, **k: _frame(
                            [(1.1, 1.1005, 1.0995, 1.1, 10.0)] * 100,
                            "2026-10-15 00:00"))

    assert sb.pre_session_mark_liquidity("LONDON",
                                         datetime(2026, 10, 15, 7, 59)) == 3


def test_pre_session_marking_survives_one_bad_symbol(monkeypatch):
    import modules.candle_provider as cp
    monkeypatch.setattr("config.SILVER_BULLET_INSTRUMENTS",
                        ["BAD", "GOOD"])

    def selective(symbol, *a, **k):
        if symbol == "BAD":
            raise RuntimeError("feed exploded")
        return _frame([(1.1, 1.1005, 1.0995, 1.1, 10.0)] * 100,
                      "2026-10-15 00:00")

    monkeypatch.setattr(cp, "get_candles", selective)
    assert sb.pre_session_mark_liquidity("LONDON",
                                         datetime(2026, 10, 15, 7, 59)) == 1


def test_daily_reset_clears_marked_levels(monkeypatch):
    import modules.candle_provider as cp
    monkeypatch.setattr(cp, "get_candles",
                        lambda *a, **k: _frame(
                            [(1.1, 1.1005, 1.0995, 1.1, 10.0)] * 100,
                            "2026-10-15 00:00"))

    now = datetime(2026, 10, 15, 7, 59)
    sb.mark_session_liquidity("EURUSD", "LONDON", now)
    assert sb.get_session_levels("EURUSD", "LONDON", now) is not None

    sb.reset_daily_cache("test")
    assert sb.get_session_levels("EURUSD", "LONDON", now) is None
