"""
backend/tests/test_daily_bias.py
Phase 2 — H4 market structure, the EMA50 condition, and daily bias storage.

`identify_h4_structure` is pure: it takes a frame and returns a label. That is
tested directly. `calculate_daily_bias` reaches the network through the candle
provider, so it is tested against a stubbed provider to pin the look-ahead
guards, the UTC date key and the cache behaviour.
"""
from datetime import datetime

import pandas as pd
import pytest

from tests.helpers import candles, staircase
from modules import silver_bullet as sb


UTC = "UTC"


def _h4_frame(rows, start="2026-10-01 00:00"):
    return candles(rows, start=start, freq="4h")


def _ohlcv(df):
    """The (o, h, l, c, v) tuples of a frame, so fixtures can be re-stitched."""
    return [tuple(r) for r in df[["open", "high", "low", "close", "volume"]].values]


def _strict_wave(count=80, step=1.0, pullback=1.2, up=True) -> list:
    """
    A trending series with unambiguous, strictly-ordered swing points.

    The detector's swing test is a STRICT inequality against the `lookback` (3)
    bars on each side, so:

      * a leg must run at least 5 bars, or its turning point has fewer than 3
        bars on one side and is never confirmed;
      * the peak bar must be strictly the highest of its neighbourhood, so the
        impulse excursion is widened on the last bar of the leg;
      * the retrace must stay strictly inside the leg's range on both sides, or
        it creates a second, competing extreme and the swing is lost.

    Getting any of these wrong makes the detector correctly return NEUTRAL, so
    they are spelled out here rather than left to a cleverer generator.
    """
    rows = []
    price = 100.0
    sign = 1 if up else -1

    def bar(o, h, l, c):
        rows.append((o, h, l, c, 100.0))

    while len(rows) < count:
        # Impulse: 5 bars in the trend direction. The last bar overshoots so it
        # is strictly the extreme of its neighbourhood — the swing test uses a
        # STRICT inequality, so a flat pair of extremes is not a swing.
        leg_high = price
        leg_low = price
        for k in range(5):
            nxt = price + sign * step
            hi = max(price, nxt) + (0.30 if (k == 4 and sign > 0) else 0.05)
            lo = min(price, nxt) - (0.30 if (k == 4 and sign < 0) else 0.05)
            bar(price, hi, lo, nxt)
            price = nxt
            leg_high = max(leg_high, hi)
            leg_low = min(leg_low, lo)

        # Retrace: 3 bars against the trend, kept strictly inside the impulse
        # range so it never creates a competing extreme. The final retrace bar
        # undershoots so the retrace extreme is itself strictly ordered.
        for k in range(3):
            nxt = price - sign * pullback
            if sign > 0:
                # Pulling back down: high stays under the impulse peak, the last
                # low undershoots to be strictly the lowest.
                hi = min(max(price, nxt) + 0.05, leg_high - 0.10)
                lo = min(price, nxt) - (0.30 if k == 2 else 0.05)
            else:
                # Pulling back up: low stays above the impulse trough, the last
                # high overshoots to be strictly the highest.
                hi = max(price, nxt) + (0.30 if k == 2 else 0.05)
                lo = max(min(price, nxt) - 0.05, leg_low + 0.10)
            bar(price, hi, lo, nxt)
            price = nxt
    return rows[:count]


def _strict(count=80, step=1.0, up=True):
    """The strict wave, wrapped as a 4h frame."""
    return _h4_frame(_strict_wave(count=count, step=step, up=up))
    """
    A trending series that actually contains confirmed swing points.

    A strictly monotonic staircase has NO swing high or low — every bar is
    higher than the last, so nothing has a lower bar on both sides — and the
    structure detector correctly returns NEUTRAL. A trend that can be read as
    higher-highs/higher-lows must therefore advance in legs with pullbacks
    between them, which is what this builds.
    """
    rows = []
    price = 100.0
    sign = 1 if up else -1
    while len(rows) < count:
        # Impulse leg: 3 bars of clean direction.
        for _ in range(3):
            nxt = price + sign * step
            rows.append((price, max(price, nxt) + 0.05,
                         min(price, nxt) - 0.05, nxt, 100.0))
            price = nxt
        # Pullback: smaller counter-move, so the swing is unambiguously confirmed.
        for _ in range(2):
            nxt = price - sign * pullback
            rows.append((price, max(price, nxt) + 0.05,
                         min(price, nxt) - 0.05, nxt, 100.0))
            price = nxt
    return rows[:count]


# ── Structure: the three spec conditions ──────────────────────────────────────

def test_bullish_structure_needs_hh_and_hl_and_a_close_above_ema50():
    df = _strict(count=60, step=1.0, up=True)
    bias, strength = sb.identify_h4_structure(df)
    assert bias == "BULLISH"
    assert strength >= 2


def test_bearish_structure_needs_ll_and_lh_and_a_close_below_ema50():
    df = _strict(count=60, step=1.0, up=False)
    bias, strength = sb.identify_h4_structure(df)
    assert bias == "BEARISH"
    assert strength >= 2


def test_a_flat_market_is_neutral():
    df = _h4_frame([(100.0, 100.5, 99.5, 100.0, 10.0)] * 60)
    bias, strength = sb.identify_h4_structure(df)
    assert bias == "NEUTRAL"
    assert strength == 0


def test_too_few_candles_is_neutral():
    df = _h4_frame([(100.0, 101.0, 99.0, 100.5, 10.0)] * 10)
    assert sb.identify_h4_structure(df)[0] == "NEUTRAL"


def test_none_and_empty_frames_are_neutral():
    assert sb.identify_h4_structure(None)[0] == "NEUTRAL"
    assert sb.identify_h4_structure(pd.DataFrame())[0] == "NEUTRAL"


def test_ema50_is_the_boundary_not_the_trend_alone():
    """
    A cleanly rising staircase that has just been sold back below its own EMA50
    must NOT be bullish. This is the condition that stops the strategy buying a
    structure that has already broken.
    """
    rows = [(100.0 + i, 101.0 + i, 99.0 + i, 100.5 + i, 10.0) for i in range(60)]
    # Slam the final bars down hard, well under the EMA, leaving the earlier
    # higher-high/higher-low sequence intact.
    rows += [(100.0, 100.5, 60.0, 61.0, 10.0)] * 6
    df = _h4_frame(rows)
    bias, _ = sb.identify_h4_structure(df)
    assert bias != "BULLISH"


def test_structure_uses_only_the_most_recent_window():
    """
    A long history of the opposite trend must not vote. The 50-bar window means
    an old bearish run followed by a clean bullish one reads bullish.
    """
    old = _strict_wave(count=60, step=1.0, up=False)
    recent = _strict_wave(count=60, step=1.0, up=True)
    # Re-base the second leg so it continues from where the first ended.
    recent = [(o - 100.0 + 40.0, h - 100.0 + 40.0, l - 100.0 + 40.0,
               c - 100.0 + 40.0, v) for (o, h, l, c, v) in recent]
    df = _h4_frame(old + recent)
    bias, _ = sb.identify_h4_structure(df)
    assert bias == "BULLISH"


def test_one_higher_high_is_not_enough():
    """
    A single higher high without a second consecutive one must stay neutral: the
    spec asks for at least two.
    """
    rows = [(100.0, 100.6, 99.4, 100.0, 10.0)] * 40
    rows += [(100.0, 100.8, 99.2, 100.0, 10.0)] * 20
    rows += [(100.0, 101.5, 99.0, 100.2, 10.0)] * 20
    bias, strength = sb.identify_h4_structure(_h4_frame(rows))
    assert bias in ("NEUTRAL", "BULLISH")
    if bias == "NEUTRAL":
        assert strength == 0


def test_structure_is_robust_to_the_swing_lookback():
    """Both swing series must be findable, or the result is neutral."""
    df = _strict(count=60, step=2.0, up=True)
    bias, strength = sb.identify_h4_structure(df)
    assert bias == "BULLISH"
    assert strength >= 2


# ── Look-ahead: the still-forming candle must be dropped ──────────────────────

def test_closed_only_drops_the_bar_in_progress():
    """
    At 13:00 UTC the 12:00 H4 bar is still forming; it must be dropped so the
    H4 high/low/close are final. Using it makes the bias non-reproducible.
    """
    df = _h4_frame([(100.0, 101.0, 99.0, 100.5, 10.0)] * 6,
                   start="2026-10-15 00:00")
    now = datetime(2026, 10, 15, 13, 0, 0)
    closed = sb._closed_only(df, "4h", now)

    assert closed is not None
    # 00:00, 04:00 and 08:00 are closed; 12:00 is still running.
    assert len(closed) == 3
    assert closed["timestamp"].max() == pd.Timestamp("2026-10-15 08:00:00", tz=UTC)


def test_closed_only_keeps_the_bar_on_the_period_boundary():
    """
    A bar opening exactly at the current period start is the live bar. At 12:00
    the 12:00-16:00 H4 bar has only just opened, so it must be dropped.
    """
    df = _h4_frame([(100.0, 101.0, 99.0, 100.5, 10.0)] * 3,
                   start="2026-10-15 08:00")
    now = datetime(2026, 10, 15, 12, 0, 0)
    closed = sb._closed_only(df, "4h", now)
    assert len(closed) == 1
    assert closed["timestamp"].iloc[0] == pd.Timestamp("2026-10-15 08:00:00", tz=UTC)


def test_closed_only_floors_h4_bars_on_the_epoch_not_the_hour():
    """
    4-hour bars open at 00/04/08/12/16/20 UTC. At 13:00 the live bar is the one
    that opened at 12:00 — flooring to the current HOUR would leave it in the
    frame and the bias would read a candle still in progress.
    """
    df = _h4_frame([(100.0, 101.0, 99.0, 100.5, 10.0)] * 6,
                   start="2026-10-15 00:00")
    closed = sb._closed_only(df, "4h", datetime(2026, 10, 15, 13, 0, 0))
    assert [str(t) for t in closed["timestamp"].tolist()] == [
        "2026-10-15 00:00:00+00:00",
        "2026-10-15 04:00:00+00:00",
        "2026-10-15 08:00:00+00:00",
    ]


def test_closed_only_accepts_a_timezone_aware_now():
    df = _h4_frame([(100.0, 101.0, 99.0, 100.5, 10.0)] * 6,
                   start="2026-10-15 00:00")
    from datetime import timezone as tz
    aware = datetime(2026, 10, 15, 15, 0, 0, tzinfo=tz.utc)   # 13:00 UTC
    closed = sb._closed_only(df, "4h", aware)
    assert len(closed) == 3


def test_closed_only_uses_the_clock_not_the_data():
    """
    A feed that is missing recent bars must still drop nothing extra: the cutoff
    comes from the wall clock, not from the newest row present.
    """
    df = _h4_frame([(100.0, 101.0, 99.0, 100.5, 10.0)] * 2,
                   start="2026-10-15 00:00")
    now = datetime(2026, 10, 15, 9, 0, 0)
    closed = sb._closed_only(df, "4h", now)
    assert len(closed) == 2


def test_closed_only_passes_through_a_frame_it_cannot_bound():
    df = candles([(100.0, 101.0, 99.0, 100.5, 10.0)] * 5, with_timestamp=False)
    assert sb._closed_only(df, "4h", datetime(2026, 10, 15, 13, 0)) is not None


def test_closed_only_handles_none_and_empty():
    assert sb._closed_only(None, "4h") is None
    assert len(sb._closed_only(pd.DataFrame(), "4h")) == 0


def test_closed_only_ignores_an_unknown_timeframe():
    df = _h4_frame([(100.0, 101.0, 99.0, 100.5, 10.0)] * 6)
    assert len(sb._closed_only(df, "7h", datetime(2026, 10, 15, 13, 0))) == 6


def test_closed_only_5m_uses_the_five_minute_boundary():
    df = candles([(100.0, 101.0, 99.0, 100.5, 10.0)] * 6,
                 start="2026-10-15 12:00", freq="5min")
    now = datetime(2026, 10, 15, 12, 17, 0)
    closed = sb._closed_only(df, "5m", now)
    # 12:00, 12:05, 12:10 are closed; 12:15 is live.
    assert len(closed) == 3
    assert closed["timestamp"].max() == pd.Timestamp("2026-10-15 12:10:00", tz=UTC)


# ── EMA helper ────────────────────────────────────────────────────────────────

def test_ema_returns_zero_when_there_is_too_little_history():
    assert sb._ema(pd.Series([1.0, 2.0, 3.0]), period=50) == 0.0


def test_ema_of_a_constant_series_is_that_constant():
    assert sb._ema(pd.Series([5.0] * 100), period=50) == pytest.approx(5.0)


def test_ema_returns_zero_for_none():
    assert sb._ema(None) == 0.0


# ── Daily bias record, date key and reset ─────────────────────────────────────

@pytest.fixture
def stub_provider(monkeypatch):
    """
    Replace the candle provider seam with a deterministic fixture.

    `calculate_daily_bias` imports `modules.candle_provider.get_candles` inside
    the function, so patching the module attribute is enough.
    """
    import modules.candle_provider as cp

    frames = {}

    def fake_get_candles(symbol, timeframe="1h", limit=400):
        return frames.get((symbol, timeframe))

    monkeypatch.setattr(cp, "get_candles", fake_get_candles)
    return frames


def _bullish_h4(days=12, start="2026-09-20 00:00"):
    return _h4_frame(_strict_wave(count=days * 6, step=1.0, up=True), start=start)


def _prior_day_h1():
    return candles([(100.0, 101.0, 100.0, 101.0, 100.0)] * 24,
                   start="2026-10-14 00:00", freq="1h")


def test_bias_record_is_keyed_to_the_current_utc_date(stub_provider, monkeypatch):
    monkeypatch.setattr(sb, "utc_date_key", lambda *a, **k: "2026-10-15")

    stub_provider[("EURUSD", "4h")] = _bullish_h4()
    stub_provider[("EURUSD", "1h")] = _prior_day_h1()

    rec = sb.calculate_daily_bias("EURUSD")
    assert rec is not None
    assert rec["session_date"] == "2026-10-15"
    assert rec["h4_bias"] in ("BULLISH", "BEARISH", "NEUTRAL")


def test_neutral_bias_is_stored_and_has_no_vp_levels(stub_provider):
    stub_provider[("EURUSD", "4h")] = _h4_frame(
        [(100.0, 100.5, 99.5, 100.0, 10.0)] * 60)
    rec = sb.calculate_daily_bias("EURUSD")

    assert rec is not None
    assert rec["h4_bias"] == "NEUTRAL"
    assert rec["vp_levels"] is None
    assert rec["vp_levels_valid"] is False
    assert rec["vp_levels_trusted"] is False


def test_bias_is_none_when_the_h4_feed_fails(stub_provider):
    """No H4 data at all: the bias cannot be computed, so it is reported absent."""
    stub_provider[("EURUSD", "4h")] = None
    rec = sb.calculate_daily_bias("EURUSD")
    # A missing feed reads as a flat structure, which is NEUTRAL, and the record
    # still carries a date key so the caller can see it was attempted.
    assert rec is not None
    assert rec["h4_bias"] == "NEUTRAL"


def test_bias_survives_a_missing_h1_profile(stub_provider):
    """H4 is bullish but the prior-day 1h feed is empty: bias survives, VP does not."""
    stub_provider[("EURUSD", "4h")] = _bullish_h4()
    stub_provider[("EURUSD", "1h")] = None

    rec = sb.calculate_daily_bias("EURUSD")
    assert rec is not None
    assert rec["h4_bias"] == "BULLISH"
    assert rec["vp_levels"] is None
    assert rec["vp_gateable"] is False


def test_stale_bias_is_not_returned(monkeypatch):
    """
    A record computed yesterday must read as absent, so a stale NEUTRAL cannot
    block trading and a stale BULLISH cannot authorise it.
    """
    sb.reset_daily_cache("test")
    sb._daily_bias["EURUSD"] = {
        "symbol": "EURUSD",
        "h4_bias": "BULLISH",
        "session_date": "2026-10-14",
    }
    monkeypatch.setattr(sb, "utc_date_key", lambda *a, **k: "2026-10-15")
    assert sb.get_daily_bias("EURUSD") is None


def test_todays_bias_is_returned(monkeypatch):
    sb.reset_daily_cache("test")
    sb._daily_bias["EURUSD"] = {
        "symbol": "EURUSD",
        "h4_bias": "BULLISH",
        "session_date": "2026-10-15",
    }
    monkeypatch.setattr(sb, "utc_date_key", lambda *a, **k: "2026-10-15")
    assert sb.get_daily_bias("EURUSD")["h4_bias"] == "BULLISH"


def test_unknown_symbol_has_no_bias():
    sb.reset_daily_cache("test")
    assert sb.get_daily_bias("NOPE") is None


def test_get_all_daily_bias_filters_by_date(monkeypatch):
    sb.reset_daily_cache("test")
    sb._daily_bias["A"] = {"session_date": "2026-10-15", "h4_bias": "BULLISH"}
    sb._daily_bias["B"] = {"session_date": "2026-10-14", "h4_bias": "BEARISH"}
    monkeypatch.setattr(sb, "utc_date_key", lambda *a, **k: "2026-10-15")

    today = sb.get_all_daily_bias()
    assert set(today) == {"A"}


def test_reset_daily_cache_clears_every_day_scoped_store():
    sb._daily_bias["A"] = {"session_date": "2026-10-15"}
    sb._session_levels["LONDON"] = {"A": {"swing_high": 1.0}}
    sb._session_levels_date["LONDON"] = "2026-10-15"
    sb._active_setups["A"] = {"symbol": "A"}

    sb.reset_daily_cache("test")

    assert sb._daily_bias == {}
    assert sb._session_levels == {}
    assert sb._active_setups == {}


def test_ensure_current_day_resets_only_when_the_day_actually_rolls(monkeypatch):
    sb.reset_daily_cache("test")

    monkeypatch.setattr(sb, "utc_date_key", lambda *a, **k: "2026-10-15")
    assert sb.ensure_current_day() is False        # first sighting: nothing to reset

    sb._daily_bias["A"] = {"session_date": "2026-10-15"}
    assert sb.ensure_current_day() is False        # same day
    assert "A" in sb._daily_bias

    monkeypatch.setattr(sb, "utc_date_key", lambda *a, **k: "2026-10-16")
    assert sb.ensure_current_day() is True         # rolled
    assert sb._daily_bias == {}


def test_ensure_current_day_is_not_fooled_by_an_all_neutral_day(monkeypatch):
    """
    The guard is a stored date key, not the contents of the dicts, so a day where
    every symbol came back NEUTRAL is not mistaken for "never computed".
    """
    sb.reset_daily_cache("test")
    monkeypatch.setattr(sb, "utc_date_key", lambda *a, **k: "2026-10-15")

    sb._daily_bias["A"] = {"session_date": "2026-10-15", "h4_bias": "NEUTRAL"}
    assert sb.ensure_current_day() is False
    assert "A" in sb._daily_bias


def test_calculate_daily_bias_all_pairs_skips_todays_records(stub_provider, monkeypatch):
    """A restart mid-session must not re-poll every symbol for data that cannot have changed."""
    sb.reset_daily_cache("test")
    monkeypatch.setattr(sb, "utc_date_key", lambda *a, **k: "2026-10-15")
    monkeypatch.setattr("config.SILVER_BULLET_INSTRUMENTS", ["EURUSD", "GBPUSD"])

    calls = []

    def counting_get_candles(symbol, timeframe="1h", limit=400):
        calls.append((symbol, timeframe))
        if timeframe == "4h":
            return _bullish_h4()
        return _prior_day_h1()

    import modules.candle_provider as cp
    monkeypatch.setattr(cp, "get_candles", counting_get_candles)

    first = sb.calculate_daily_bias_all_pairs()
    assert first == 2
    # Both symbols were asked for their H4 structure frame.
    assert ("EURUSD", "4h") in calls and ("GBPUSD", "4h") in calls

    calls.clear()
    second = sb.calculate_daily_bias_all_pairs()
    assert second == 0
    assert calls == []


def test_calculate_daily_bias_all_pairs_force_recomputes(stub_provider, monkeypatch):
    sb.reset_daily_cache("test")
    monkeypatch.setattr(sb, "utc_date_key", lambda *a, **k: "2026-10-15")
    monkeypatch.setattr("config.SILVER_BULLET_INSTRUMENTS", ["EURUSD"])

    import modules.candle_provider as cp
    monkeypatch.setattr(cp, "get_candles",
                        lambda s, timeframe="1h", limit=400:
                        _bullish_h4() if timeframe == "4h" else _prior_day_h1())

    sb.calculate_daily_bias_all_pairs()
    assert sb.calculate_daily_bias_all_pairs(force=True) == 1


def test_one_bad_symbol_does_not_abort_the_sweep(stub_provider, monkeypatch):
    sb.reset_daily_cache("test")
    monkeypatch.setattr(sb, "utc_date_key", lambda *a, **k: "2026-10-15")
    monkeypatch.setattr("config.SILVER_BULLET_INSTRUMENTS", ["BAD", "GOOD"])

    import modules.candle_provider as cp

    def raising_get_candles(symbol, timeframe="1h", limit=400):
        if symbol == "BAD":
            raise RuntimeError("feed exploded")
        return _bullish_h4() if timeframe == "4h" else _prior_day_h1()

    monkeypatch.setattr(cp, "get_candles", raising_get_candles)

    assert sb.calculate_daily_bias_all_pairs() == 1
    assert sb.get_daily_bias("GOOD") is not None







