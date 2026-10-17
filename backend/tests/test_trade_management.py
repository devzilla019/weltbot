"""
backend/tests/test_trade_management.py
Phase 4 — stops, targets, partials, trailing, session exits, reversals and the
daily halt.

The management rules are pure decisions over a trade record plus market inputs,
so they are tested directly. The broker-touching cycle is tested with the venue
stubbed, which is also how duplicate-order prevention is verified.
"""
from datetime import datetime, timedelta

import pytest

from modules import forex_executor as fx
from modules import forex_position_manager as pm


NOW = datetime(2026, 10, 15, 10, 0, 0)


class FakeTrade:
    """
    A stand-in for the ForexTrade row.

    Only the fields the rules read are present, so a rule that starts depending
    on a new field fails loudly here rather than silently reading None.
    """

    def __init__(self, **kw):
        self.symbol = "EURUSD"
        self.signal = "BUY"
        self.entry_price = 1.1000
        self.stop_loss = 1.0950
        self.initial_stop = 1.0950
        self.initial_risk = 0.0050
        self.take_profit = 1.1150
        self.tp1 = 1.1050
        self.tp2 = 1.1100
        self.tp3 = 1.1150
        self.lots = 10000.0
        self.original_lots = 10000.0
        self.tp1_done = False
        self.tp2_done = False
        self.tp3_done = False
        self.breakeven_done = False
        self.trailing_active = False
        self.partial_tp_hit = False
        self.peak_price = 1.1000
        self.session_name = "LONDON"
        self.session_expires_at = datetime(2026, 10, 15, 9, 0, 0)
        self.created_at = datetime(2026, 10, 15, 8, 30, 0)
        self.metaapi_position_id = "deal-1"
        self.outcome = "OPEN"
        self.pnl = None
        self.closed_at = None
        self.close_reason = None
        for k, v in kw.items():
            setattr(self, k, v)


# ══════════════════════════════════════════════════════════════════════════════
#  STOP AND TARGET CALCULATION
# ══════════════════════════════════════════════════════════════════════════════

def _stops(direction="BUY", entry=1.1000, wick=1.0990, atr=0.0020,
           confidence=93, target=None):
    return fx.calculate_stops_and_targets("EURUSD", direction, entry, wick,
                                          atr, confidence, target)


def test_the_stop_sits_beyond_the_sweep_wick_by_the_atr_buffer():
    out = _stops()
    # wick 1.0990 - 0.5 * 0.0020 = 1.0980, so risk = 1.1000 - 1.0980 = 0.0020
    assert out["stop_loss"] == pytest.approx(1.0980)
    assert out["risk"] == pytest.approx(0.0020)
    assert out["direction"] == "BUY"


def test_the_bearish_stop_sits_above_the_wick():
    out = _stops(direction="SELL", entry=1.1000, wick=1.1010)
    assert out["stop_loss"] == pytest.approx(1.1020)
    assert out["stop_loss"] > out["entry"]


def test_targets_are_one_two_and_three_r():
    out = _stops()
    risk = out["risk"]
    assert out["tp1"] == pytest.approx(1.1000 + risk)
    assert out["tp2"] == pytest.approx(1.1000 + risk * 2)
    assert out["tp3"] == pytest.approx(1.1000 + risk * 3)


def test_the_bearish_targets_mirror_the_bullish_ones():
    out = _stops(direction="SELL", entry=1.1000, wick=1.1010)
    risk = out["risk"]
    assert out["tp1"] == pytest.approx(1.1000 - risk)
    assert out["tp3"] == pytest.approx(1.1000 - risk * 3)


def test_a_liquidity_target_beyond_three_r_is_used_when_confidence_is_high():
    """The high-confidence extension: at 96+ a real target beyond 3R is honoured."""
    # risk is 0.0020, so 5R is 0.0100 away.
    target = 1.1100
    out = _stops(confidence=96, target=target)
    assert out["tp3"] == pytest.approx(target)
    assert out["tp3_extended"] is True
    assert out["tp3_r"] == pytest.approx(5.0)


def test_the_same_target_is_clipped_to_three_r_when_confidence_is_not_high():
    """Below the extension threshold a target beyond 3R is not reached for."""
    target = 1.1100
    out = _stops(confidence=93, target=target)
    assert out["tp3"] == pytest.approx(1.1000 + 0.0020 * 3)
    assert out["tp3_extended"] is False


def test_a_liquidity_target_within_three_r_is_always_used():
    target = 1.1000 + 0.0020 * 2.5
    for conf in (88, 93, 96):
        out = _stops(confidence=conf, target=target)
        assert out["tp3"] == pytest.approx(target)


def test_a_target_closer_than_two_r_falls_back_to_three_r():
    """A 'target' inside the noise is not a target."""
    target = 1.1000 + 0.0020 * 1.2
    out = _stops(confidence=96, target=target)
    assert out["tp3"] == pytest.approx(1.1000 + 0.0020 * 3)
    assert out["tp3_extended"] is False


def test_a_stale_target_beyond_the_ceiling_falls_back():
    target = 1.1000 + 0.0020 * 40
    out = _stops(confidence=96, target=target)
    assert out["tp3"] == pytest.approx(1.1000 + 0.0020 * 3)
    # The ceiling discarded the target, so it must not be reported as extended.
    assert out["tp3_extended"] is False


def test_a_stop_on_the_wrong_side_of_entry_is_rejected():
    """A BUY whose 'stop' is above entry has no risk to define."""
    assert _stops(entry=1.1000, wick=1.1010) is None


def test_a_stop_wider_than_the_atr_ceiling_is_rejected():
    """
    A stale wick far from price would imply an absurd stop. The ceiling is
    6 ATR, so a wick 10 ATR away (plus the buffer) must be refused.
    """
    assert _stops(entry=1.1000, wick=1.1000 - 0.0020 * 10, atr=0.0020) is None


def test_a_stop_just_inside_the_ceiling_is_accepted():
    """The ceiling is a ceiling, not a target — 5.5 ATR is still tradeable."""
    out = _stops(entry=1.1000, wick=1.1000 - 0.0020 * 5, atr=0.0020)
    assert out is not None
    assert out["risk_atr"] == pytest.approx(5.5)


def test_a_stop_inside_half_an_atr_is_widened_not_tightened():
    """
    A stop inside the instrument's own noise is widened to 0.5 ATR. Widening
    raises the R denominator rather than tightening the stop, which would raise
    the chance of being wicked out.

    With the default 0.5 ATR buffer the raw risk is always already above 0.5
    ATR, so the guard is only reachable with a smaller buffer — which is
    exactly the configuration it exists to protect.
    """
    out = fx.calculate_stops_and_targets("EURUSD", "BUY", 1.1000, 1.0999,
                                         0.0020, 93, atr_buffer=0.0)
    assert out is not None
    assert out["risk"] == pytest.approx(0.5 * 0.0020)
    assert out["stop_loss"] == pytest.approx(1.1000 - 0.0010)


def test_the_default_buffer_never_produces_a_sub_half_atr_stop():
    """With the configured buffer the stop is always at least 0.5 ATR away."""
    out = _stops(entry=1.1000, wick=1.0999, atr=0.0020)
    assert out["risk"] >= 0.5 * 0.0020


@pytest.mark.parametrize("atr", [0, -0.001])
def test_a_missing_atr_cannot_size_a_stop(atr):
    assert _stops(atr=atr) is None


@pytest.mark.parametrize("entry,wick", [(0, 1.0), (-1, 1.0), (1.1, 0), (1.1, -1)])
def test_non_positive_prices_are_rejected(entry, wick):
    assert _stops(entry=entry, wick=wick) is None


def test_non_finite_input_is_rejected():
    assert _stops(atr=float("nan")) is None
    assert _stops(entry=float("inf")) is None


def test_an_unknown_direction_is_rejected():
    assert _stops(direction="SIDEWAYS") is None


def test_the_risk_atr_ratio_is_reported():
    out = _stops(entry=1.1000, wick=1.0990, atr=0.0020)
    assert out["risk_atr"] == pytest.approx(1.0)   # 0.0020 / 0.0020


# ══════════════════════════════════════════════════════════════════════════════
#  PARTIAL TAKE-PROFIT SIZES
# ══════════════════════════════════════════════════════════════════════════════

def test_tp1_closes_half():
    assert fx.partial_close_size(10000.0, 1) == pytest.approx(5000.0)


def test_tp2_closes_a_quarter_of_the_original():
    assert fx.partial_close_size(10000.0, 2) == pytest.approx(2500.0)


def test_tp3_closes_the_remainder_not_a_fraction():
    """
    TP3 returns everything still open. A fraction would leave a sliver too small
    for the broker to accept, and the position would never fully close.
    """
    assert fx.partial_close_size(10000.0, 3, already_closed=7500.0) == pytest.approx(2500.0)
    assert fx.partial_close_size(10000.0, 3) == pytest.approx(10000.0)


def test_a_partial_never_exceeds_what_is_still_open():
    """Guards against a double-counted partial closing more than exists."""
    assert fx.partial_close_size(10000.0, 2, already_closed=9000.0) == pytest.approx(1000.0)


def test_no_size_remains_gives_zero():
    assert fx.partial_close_size(10000.0, 3, already_closed=10000.0) == 0.0
    assert fx.partial_close_size(10000.0, 1, already_closed=12000.0) == 0.0


def test_an_unknown_level_closes_nothing():
    assert fx.partial_close_size(10000.0, 9) == 0.0


def test_partial_sizes_survive_junk():
    assert fx.partial_close_size("bad", 1) == 0.0


def test_the_plan_totals_the_whole_position():
    """TP1 + TP2 + TP3 must account for exactly 100% of the original size."""
    original = 10000.0
    closed = 0.0
    for level in (1, 2, 3):
        size = fx.partial_close_size(original, level, closed)
        closed += size
    assert closed == pytest.approx(original)


# ══════════════════════════════════════════════════════════════════════════════
#  PARTIAL LEVEL SELECTION
# ══════════════════════════════════════════════════════════════════════════════

def test_no_level_is_reached_below_tp1():
    assert pm.next_partial_level(FakeTrade(), 1.1020) is None


def test_tp1_is_reached_at_the_target():
    assert pm.next_partial_level(FakeTrade(), 1.1050) == 1


def test_levels_are_sequential_and_do_not_skip():
    """
    A price that gaps past TP1 and TP2 in one tick must still book TP1 first,
    then TP2 on the next cycle — never jump straight to TP2.
    """
    trade = FakeTrade()
    # 1.1160 clears all three levels.
    assert pm.next_partial_level(trade, 1.1160) == 1

    trade.tp1_done = True
    assert pm.next_partial_level(trade, 1.1160) == 2

    trade.tp2_done = True
    assert pm.next_partial_level(trade, 1.1160) == 3

    trade.tp3_done = True
    assert pm.next_partial_level(trade, 1.1160) is None


def test_a_level_below_the_next_unmet_target_is_not_reported():
    """
    Levels are reported in order, so a price that has reached TP2 but not TP1
    reports TP1 — the sequence never skips ahead of an unmet level.
    """
    trade = FakeTrade()
    assert pm.next_partial_level(trade, 1.1100) == 1
    assert pm.next_partial_level(trade, 1.1040) is None


def test_a_missing_earlier_target_does_not_block_a_later_one():
    """
    With no TP1 recorded there is no level 1 to take, so level 2 is the next
    reachable one rather than nothing at all.
    """
    trade = FakeTrade(tp1=None)
    assert pm.next_partial_level(trade, 1.1120) == 2


def test_the_bearish_levels_trigger_on_a_fall():
    trade = FakeTrade(signal="SELL", entry_price=1.1000, stop_loss=1.1050,
                      initial_stop=1.1050, tp1=1.0950, tp2=1.0900, tp3=1.0850)
    assert pm.next_partial_level(trade, 1.0960) is None
    assert pm.next_partial_level(trade, 1.0950) == 1


def test_a_trade_with_no_target_levels_never_reports_a_level():
    """
    Every level is None, so nothing can be reached. This must not raise, and it
    must not report level 0 or a phantom level either.
    """
    trade = FakeTrade(tp1=None, tp2=None, tp3=None)
    assert pm.next_partial_level(trade, 1.1120) is None


def test_no_price_means_no_level():
    assert pm.next_partial_level(FakeTrade(), None) is None


# ══════════════════════════════════════════════════════════════════════════════
#  RULE 1 — BREAKEVEN
# ══════════════════════════════════════════════════════════════════════════════

def test_breakeven_does_not_apply_before_tp1():
    assert pm.breakeven_stop(FakeTrade(tp1_done=False)) is None


def test_breakeven_moves_the_stop_to_entry():
    assert pm.breakeven_stop(FakeTrade(tp1_done=True)) == pytest.approx(1.1000)


def test_breakeven_does_not_move_a_stop_that_is_already_better():
    """A stop already beyond entry is left alone — never moved backwards."""
    trade = FakeTrade(tp1_done=True, stop_loss=1.1020)
    assert pm.breakeven_stop(trade) is None


def test_breakeven_does_not_re_send_when_already_at_entry():
    trade = FakeTrade(tp1_done=True, stop_loss=1.1000)
    assert pm.breakeven_stop(trade) is None


def test_breakeven_for_a_short_moves_the_stop_down():
    trade = FakeTrade(signal="SELL", entry_price=1.1000, stop_loss=1.1050,
                      tp1_done=True)
    assert pm.breakeven_stop(trade) == pytest.approx(1.1000)


def test_breakeven_survives_junk_prices():
    assert pm.breakeven_stop(FakeTrade(tp1_done=True, entry_price="bad")) is None


# ══════════════════════════════════════════════════════════════════════════════
#  RULE 2 — TRAILING
# ══════════════════════════════════════════════════════════════════════════════

def test_trailing_does_not_apply_before_tp1():
    assert pm.trail_stop(FakeTrade(tp1_done=False), 1.1200, 0.0020) is None


def test_trailing_follows_price_for_a_long():
    trade = FakeTrade(tp1_done=True, stop_loss=1.1000)
    trail = pm.trail_stop(trade, 1.1200, 0.0020)
    assert trail == pytest.approx(1.1180)      # 1.1200 - 1.0 * 0.0020
    assert trail > trade.stop_loss


def test_trailing_follows_price_for_a_short():
    """
    A short's stop trails ABOVE price. The starting stop must already be at or
    better than entry, because breakeven owns the move from the losing side.
    """
    trade = FakeTrade(signal="SELL", entry_price=1.1000, stop_loss=1.0980,
                      initial_stop=1.1050, tp1_done=True)
    trail = pm.trail_stop(trade, 1.0800, 0.0020)
    assert trail == pytest.approx(1.0820)      # 1.0800 + 1.0 * 0.0020
    assert trail < trade.stop_loss


def test_trailing_will_not_act_while_the_stop_is_still_on_the_losing_side():
    """
    Breakeven owns that case. If the trail ran first it could move the stop to a
    level better than entry without the position ever having been protected —
    and on a short that means the stop would jump from above entry to below it.
    """
    trade = FakeTrade(signal="SELL", entry_price=1.1000, stop_loss=1.1050,
                      tp1_done=True)
    assert pm.trail_stop(trade, 1.0800, 0.0020) is None


def test_trailing_will_not_act_for_a_long_whose_stop_is_above_entry_either():
    trade = FakeTrade(signal="BUY", entry_price=1.1000, stop_loss=1.0950,
                      tp1_done=True)
    assert pm.trail_stop(trade, 1.1200, 0.0020) is None


def test_the_trailing_stop_never_moves_backwards():
    """
    A pullback must not widen risk back out. This is the property that makes a
    trailing stop a ratchet rather than a second opinion.
    """
    trade = FakeTrade(tp1_done=True, stop_loss=1.1150)
    # Price has fallen back below the stop's implied level.
    assert pm.trail_stop(trade, 1.1100, 0.0020) is None


def test_the_trailing_stop_never_moves_backwards_for_a_short():
    trade = FakeTrade(signal="SELL", entry_price=1.1000, stop_loss=1.0820,
                      tp1_done=True)
    # Price has risen back above the stop's implied level.
    assert pm.trail_stop(trade, 1.0850, 0.0020) is None


def test_a_negligible_trail_move_is_skipped():
    """
    Moving a stop for a fraction of an ATR burns API calls and invites rejects.
    The threshold is 0.05 ATR, so a candidate only 0.04 ATR away is skipped.
    """
    # Candidate would be 1.1200 - 0.0020 = 1.1180; current 1.11792 is 0.04 ATR away.
    trade = FakeTrade(tp1_done=True, stop_loss=1.11792)
    assert pm.trail_stop(trade, 1.1200, 0.0020) is None

    # 0.10 ATR away clears the threshold and is applied.
    trade2 = FakeTrade(tp1_done=True, stop_loss=1.1178)
    assert pm.trail_stop(trade2, 1.1200, 0.0020) == pytest.approx(1.1180)


def test_trailing_needs_a_usable_atr():
    trade = FakeTrade(tp1_done=True)
    assert pm.trail_stop(trade, 1.1200, 0) is None
    assert pm.trail_stop(trade, 1.1200, -1) is None
    assert pm.trail_stop(trade, 1.1200, None) is None
    assert pm.trail_stop(trade, None, 0.0020) is None


def test_the_trail_distance_is_the_documented_multiple():
    assert fx.TRAIL_ATR_MULTIPLE == pm.TRAIL_ATR_MULTIPLE == 1.0


# ══════════════════════════════════════════════════════════════════════════════
#  RULE 3 — SESSION / TIME EXITS
# ══════════════════════════════════════════════════════════════════════════════

def test_a_trade_inside_its_session_is_not_due():
    trade = FakeTrade(session_expires_at=datetime(2026, 10, 15, 12, 0, 0),
                      created_at=datetime(2026, 10, 15, 10, 0, 0))
    due, _ = pm.session_exit_due(trade, NOW)
    assert due is False


def test_a_trade_past_its_session_close_is_due():
    trade = FakeTrade(session_expires_at=datetime(2026, 10, 15, 9, 0, 0),
                      created_at=datetime(2026, 10, 15, 8, 30, 0))
    due, why = pm.session_exit_due(trade, NOW)
    assert due is True
    assert "closed" in why


def test_a_trade_past_the_holding_limit_is_due_even_without_a_session():
    """Catches a position whose session is long past — e.g. one opened Friday."""
    trade = FakeTrade(session_expires_at=None,
                      created_at=NOW - timedelta(hours=pm.MAX_HOLDING_HOURS + 1))
    due, why = pm.session_exit_due(trade, NOW)
    assert due is True
    assert "limit" in why


def test_the_holding_limit_boundary():
    trade = FakeTrade(session_expires_at=None,
                      created_at=NOW - timedelta(hours=pm.MAX_HOLDING_HOURS - 0.5))
    assert pm.session_exit_due(trade, NOW)[0] is False


def test_a_trade_with_no_expiry_and_no_age_is_not_due():
    trade = FakeTrade(session_expires_at=None, created_at=None)
    assert pm.session_exit_due(trade, NOW)[0] is False


def test_a_naive_aware_mismatch_does_not_crash_the_exit_check():
    """
    A timezone-aware expiry against a naive `now` raises on comparison. That
    must degrade to the holding-time check, never skip the exit entirely.
    """
    trade = FakeTrade(
        session_expires_at=datetime(2026, 10, 15, 9, 0, 0, tzinfo=None),
        created_at=NOW - timedelta(hours=1),
    )
    due, _ = pm.session_exit_due(trade, NOW)
    assert isinstance(due, bool)


# ══════════════════════════════════════════════════════════════════════════════
#  RULE 4 — OPPOSING STRUCTURE
# ══════════════════════════════════════════════════════════════════════════════

def test_a_bearish_flip_against_a_long_is_a_reversal():
    due, why = pm.reversal_detected(FakeTrade(signal="BUY"), {"h4_bias": "BEARISH"})
    assert due is True
    assert "BEARISH" in why


def test_a_bullish_flip_against_a_short_is_a_reversal():
    due, why = pm.reversal_detected(FakeTrade(signal="SELL"), {"h4_bias": "BULLISH"})
    assert due is True
    assert "BULLISH" in why


def test_a_flip_in_the_trade_direction_is_not_a_reversal():
    assert pm.reversal_detected(FakeTrade(signal="BUY"), {"h4_bias": "BULLISH"})[0] is False
    assert pm.reversal_detected(FakeTrade(signal="SELL"), {"h4_bias": "BEARISH"})[0] is False


def test_neutral_is_not_a_reversal():
    """
    NEUTRAL means the day has no direction — a reason not to OPEN a trade, not a
    reason to close one. Exiting on it would close every position the moment the
    bias was recomputed at the day boundary.
    """
    assert pm.reversal_detected(FakeTrade(signal="BUY"), {"h4_bias": "NEUTRAL"})[0] is False
    assert pm.reversal_detected(FakeTrade(signal="SELL"), {"h4_bias": "NEUTRAL"})[0] is False


def test_a_missing_bias_is_not_a_reversal():
    assert pm.reversal_detected(FakeTrade(), None)[0] is False
    assert pm.reversal_detected(FakeTrade(), {})[0] is False


# ══════════════════════════════════════════════════════════════════════════════
#  THE COMBINED DECISION AND ITS PRECEDENCE
# ══════════════════════════════════════════════════════════════════════════════

def _decide(trade, price, atr=0.0020, bias=None, now=NOW):
    return pm.decide_trade_action(trade, price, atr, bias, now)


def test_a_quiet_trade_holds():
    trade = FakeTrade(session_expires_at=datetime(2026, 10, 15, 12, 0, 0),
                      created_at=datetime(2026, 10, 15, 9, 30, 0))
    assert _decide(trade, 1.1020)["action"] == "HOLD"


def test_a_session_exit_beats_a_profit_action():
    """
    A trade that is due to leave must not first be amended — the amend would be
    wasted, and the position would be left with a new stop and no time left.
    """
    trade = FakeTrade(session_expires_at=datetime(2026, 10, 15, 9, 0, 0),
                      created_at=datetime(2026, 10, 15, 8, 30, 0))
    decision = _decide(trade, 1.1120)      # price is past TP2
    assert decision["action"] == "CLOSE"
    assert decision["trigger"] == "SESSION_EXIT"


def test_a_reversal_beats_a_profit_action():
    trade = FakeTrade(session_expires_at=datetime(2026, 10, 15, 12, 0, 0),
                      created_at=datetime(2026, 10, 15, 9, 30, 0))
    decision = _decide(trade, 1.1120, bias={"h4_bias": "BEARISH"})
    assert decision["action"] == "CLOSE"
    assert decision["trigger"] == "REVERSAL"


def test_a_partial_beats_a_stop_move():
    """Taking the profit is what makes the subsequent breakeven stop meaningful."""
    trade = FakeTrade(session_expires_at=datetime(2026, 10, 15, 12, 0, 0),
                      created_at=datetime(2026, 10, 15, 9, 30, 0))
    decision = _decide(trade, 1.1050)
    assert decision["action"] == "PARTIAL"
    assert decision["level"] == 1
    assert decision["size"] == pytest.approx(5000.0)


def test_a_partial_carries_the_size_and_level():
    trade = FakeTrade(session_expires_at=datetime(2026, 10, 15, 12, 0, 0),
                      created_at=datetime(2026, 10, 15, 9, 30, 0),
                      tp1_done=True, lots=5000.0)
    decision = _decide(trade, 1.1100)
    assert decision["action"] == "PARTIAL"
    assert decision["level"] == 2
    assert decision["size"] == pytest.approx(2500.0)


def test_a_trailing_stop_move_fires_after_tp1():
    trade = FakeTrade(session_expires_at=datetime(2026, 10, 15, 12, 0, 0),
                      created_at=datetime(2026, 10, 15, 9, 30, 0),
                      tp1_done=True, tp2_done=True, tp3_done=True,
                      stop_loss=1.1000)
    decision = _decide(trade, 1.1200)
    assert decision["action"] == "MOVE_STOP"
    assert decision["stop"] == pytest.approx(1.1180)


def test_a_missing_price_holds_rather_than_acting():
    trade = FakeTrade(session_expires_at=datetime(2026, 10, 15, 12, 0, 0),
                      created_at=datetime(2026, 10, 15, 9, 30, 0))
    assert _decide(trade, None)["action"] == "HOLD"
    assert _decide(trade, 0)["action"] == "HOLD"


def test_no_trade_holds():
    assert pm.decide_trade_action(None, 1.1, 0.002, None, NOW)["action"] == "HOLD"


def test_a_level_with_no_size_left_is_marked_rather_than_looped():
    """Otherwise a fully-reduced position would re-evaluate TP1 forever."""
    trade = FakeTrade(session_expires_at=datetime(2026, 10, 15, 12, 0, 0),
                      created_at=datetime(2026, 10, 15, 9, 30, 0),
                      lots=0.0, original_lots=10000.0)
    decision = _decide(trade, 1.1050)
    assert decision["action"] == "MARK_LEVEL"
    assert decision["level"] == 1


# ══════════════════════════════════════════════════════════════════════════════
#  RULE 5 — DAILY DRAWDOWN HALT
# ══════════════════════════════════════════════════════════════════════════════

def test_the_halt_is_clear_when_the_budget_is_intact(monkeypatch):
    monkeypatch.setattr(pm, "forex_daily_loss_check", lambda: (True, "OK"))
    halted, reason = pm.daily_halt_active()
    assert halted is False
    assert reason == "OK"


def test_the_halt_engages_when_the_budget_is_spent(monkeypatch):
    monkeypatch.setattr(pm, "forex_daily_loss_check",
                        lambda: (False, "daily forex loss limit hit"))
    halted, reason = pm.daily_halt_active()
    assert halted is True
    assert "loss limit" in reason


def test_the_halt_fails_closed_when_the_check_breaks(monkeypatch):
    """
    An unknown budget must not authorise new risk. This is the one place where
    failing open would be actively dangerous.
    """
    def boom():
        raise RuntimeError("db down")

    monkeypatch.setattr(pm, "forex_daily_loss_check", boom)
    halted, reason = pm.daily_halt_active()
    assert halted is True
    assert "unavailable" in reason


def test_the_halt_blocks_a_new_trade(monkeypatch):
    monkeypatch.setattr(pm, "forex_daily_loss_check", lambda: (True, "OK"))
    monkeypatch.setattr(pm, "daily_halt_active",
                        lambda: (True, "daily forex loss limit hit"))

    import modules.market_data_forex as mdf
    monkeypatch.setattr(mdf, "get_open_positions", lambda: [])

    allowed, reason = pm.can_open_forex_trade("EURUSD")
    assert allowed is False
    assert "halt" in reason


# ══════════════════════════════════════════════════════════════════════════════
#  DUPLICATE-ORDER PREVENTION AND IDEMPOTENCY
# ══════════════════════════════════════════════════════════════════════════════

@pytest.fixture
def stub_venue(monkeypatch):
    """
    Stub the Capital.com calls and capture what the management cycle does.

    No network is touched and no order is sent: the "broker" is a dict.
    """
    import modules.market_data_forex as mdf

    calls = {"close": [], "amend": []}
    positions = [{"id": "deal-1", "symbol": "EURUSD", "size": 10000.0,
                  "unrealized_pnl": 0.0}]
    price = {"value": 1.1020}

    def fake_close(deal_id, size=None):
        calls["close"].append({"deal_id": deal_id, "size": size})
        held = 10000.0
        if size is None:
            return {"success": True, "pnl": 0.0, "symbol": "EURUSD",
                    "size": held, "remaining": 0.0, "partial": False}
        return {"success": True, "pnl": 0.0, "symbol": "EURUSD",
                "size": size, "remaining": held - size, "partial": True}

    def fake_amend(deal_id, sl=None, tp=None):
        calls["amend"].append({"deal_id": deal_id, "sl": sl, "tp": tp})
        return {"success": True, "deal_id": deal_id, "stop_loss": sl}

    monkeypatch.setattr(mdf, "get_open_positions", lambda: list(positions))
    monkeypatch.setattr(mdf, "get_current_price", lambda _s: price["value"])
    monkeypatch.setattr(mdf, "close_position", fake_close)
    monkeypatch.setattr(mdf, "amend_position", fake_amend)
    monkeypatch.setattr(mdf, "get_capital_balance",
                        lambda: {"balance": 10000.0, "connected": True})

    # ATR is read from 5m candles. Without a feed the management cycle sees
    # atr=0 and the trailing rule correctly declines to move the stop, so the
    # venue stub must supply a usable ATR too.
    monkeypatch.setattr("modules.candle_provider.get_candles",
                        lambda *a, **k: _atr_frame())

    return calls, positions, price


def _atr_frame(price: float = 1.1000, atr: float = 0.0020):
    """Candles whose ATR comes out at `atr`, for the trailing rule."""
    import pandas as pd
    from tests.helpers import candles

    rows = []
    for i in range(20):
        base = price + (i % 2) * atr
        rows.append((base, base + atr, base - atr, base, 100.0))
    return candles(rows)


@pytest.fixture
def open_trade(monkeypatch):
    """Put one live trade in the DB and return it, wired to the stub broker."""
    import modules.forex_position_manager as pm_mod

    db = pm_mod.SessionLocal()
    from models import ForexTrade
    trade = ForexTrade(
        symbol="EURUSD", signal="BUY", confidence=93.0,
        entry_price=1.1000, stop_loss=1.0950, take_profit=1.1150,
        tp1=1.1050, tp2=1.1100, tp3=1.1150,
        lots=10000.0, original_lots=10000.0,
        initial_stop=1.0950, initial_risk=0.0050,
        peak_price=1.1000,
        session_name="LONDON",
        session_expires_at=datetime(2026, 10, 15, 23, 0, 0),
        metaapi_position_id="deal-1", outcome="OPEN",
    )
    db.add(trade)
    db.commit()
    db.refresh(trade)
    tid = trade.id
    db.close()

    yield tid

    db = pm_mod.SessionLocal()
    db.query(ForexTrade).filter(ForexTrade.id == tid).delete()
    db.commit()
    db.close()


def _reload(tid):
    import modules.forex_position_manager as pm_mod
    from models import ForexTrade
    db = pm_mod.SessionLocal()
    try:
        t = db.query(ForexTrade).filter(ForexTrade.id == tid).first()
        if t:
            db.expunge(t)
        return t
    finally:
        db.close()


def test_a_quiet_position_is_left_alone(stub_venue, open_trade, monkeypatch):
    calls, _pos, price = stub_venue
    price["value"] = 1.1020
    monkeypatch.setattr(pm, "decide_trade_action",
                        lambda *a, **k: {"action": "HOLD", "reason": "test"})

    stats = pm.manage_open_positions(NOW)
    assert stats["checked"] == 1
    assert calls["close"] == []
    assert calls["amend"] == []


def test_the_same_partial_is_never_taken_twice(stub_venue, open_trade):
    """
    The entry job runs on a timer and price sits past TP1 for several cycles.
    Without the durable flag the same partial would be closed on every cycle.
    """
    calls, _pos, price = stub_venue
    price["value"] = 1.1050

    first = pm.manage_open_positions(NOW)
    assert first["partials"] == 1
    assert len(calls["close"]) == 1

    trade = _reload(open_trade)
    assert trade.tp1_done is True
    assert trade.lots == pytest.approx(5000.0)

    for _ in range(4):
        pm.manage_open_positions(NOW)

    assert len(calls["close"]) == 1, "TP1 was closed more than once"


def test_a_failed_partial_is_retried_rather_than_skipped(
        stub_venue, open_trade, monkeypatch):
    """
    If the broker call fails the level flag is rolled back, so the level is
    retried next cycle instead of being silently marked as taken.
    """
    import modules.market_data_forex as mdf
    calls, _pos, price = stub_venue
    price["value"] = 1.1050

    monkeypatch.setattr(mdf, "close_position",
                        lambda _d, size=None: {"success": False, "error": "rejected"})

    stats = pm.manage_open_positions(NOW)
    assert stats["partials"] == 1          # attempted
    trade = _reload(open_trade)
    assert trade.tp1_done is False         # rolled back, so it will retry
    assert trade.lots == pytest.approx(10000.0)


def test_breakeven_is_applied_once_after_tp1(stub_venue, open_trade):
    calls, _pos, price = stub_venue
    price["value"] = 1.1050

    # Cycle 1 books the TP1 partial; the stop is not moved in the same cycle,
    # so the partial is never skipped because the stop amend failed.
    pm.manage_open_positions(NOW)
    assert calls["amend"] == []

    # Cycle 2 moves the stop to entry.
    pm.manage_open_positions(NOW)
    assert len(calls["amend"]) == 1
    assert calls["amend"][0]["sl"] == pytest.approx(1.1000)

    trade = _reload(open_trade)
    assert trade.breakeven_done is True
    assert trade.stop_loss == pytest.approx(1.1000)


def test_the_stop_is_not_re_amended_once_it_is_at_entry(stub_venue, open_trade):
    """
    After breakeven the stop sits at entry, and the trailing rule is what moves
    it further. At a price that does not justify a trail, no further amend is
    sent — the cycle must not re-send the same breakeven stop on every tick.
    """
    calls, _pos, price = stub_venue
    price["value"] = 1.1050

    # Two cycles: TP1 partial, then the breakeven stop move.
    pm.manage_open_positions(NOW)
    pm.manage_open_positions(NOW)
    assert len(calls["amend"]) == 1

    # Price holds just above entry: 1.1010 - 1 ATR = 1.0990, which is WORSE than
    # the stop at entry, so the trail correctly declines and nothing is sent.
    price["value"] = 1.1010
    for _ in range(4):
        pm.manage_open_positions(NOW)

    assert len(calls["amend"]) == 1, "the stop was re-sent after reaching entry"


def test_a_trailed_stop_is_persisted_and_not_reverted(stub_venue, open_trade):
    """
    The trailed stop must survive to the next cycle. If it did not, a restart
    or a later cycle would revert it and widen risk back out.
    """
    calls, _pos, price = stub_venue
    price["value"] = 1.1050
    pm.manage_open_positions(NOW)          # TP1 partial
    pm.manage_open_positions(NOW)          # stop to entry

    trade = _reload(open_trade)
    assert trade.stop_loss == pytest.approx(1.1000)

    # Clear the remaining levels so only the trailing rule can fire.
    import modules.forex_position_manager as pm_mod
    from models import ForexTrade
    db = pm_mod.SessionLocal()
    db.query(ForexTrade).filter(ForexTrade.id == open_trade).update(
        {"tp2_done": True, "tp3_done": True})
    db.commit()
    db.close()

    before = len(calls["amend"])
    price["value"] = 1.1200
    pm.manage_open_positions(NOW)

    trade = _reload(open_trade)
    assert trade.stop_loss > 1.1000, "the trailed stop was not persisted"
    assert len(calls["amend"]) > before

    # And a second cycle at the same price must not re-send it.
    settled = len(calls["amend"])
    pm.manage_open_positions(NOW)
    assert len(calls["amend"]) == settled


def test_a_session_expiry_closes_the_position(stub_venue, open_trade):
    import modules.forex_position_manager as pm_mod
    from models import ForexTrade

    calls, _pos, price = stub_venue
    price["value"] = 1.1020

    db = pm_mod.SessionLocal()
    db.query(ForexTrade).filter(ForexTrade.id == open_trade).update(
        {"session_expires_at": datetime(2026, 10, 15, 9, 0, 0)})
    db.commit()
    db.close()

    stats = pm.manage_open_positions(NOW)
    assert stats["closed"] == 1
    assert len(calls["close"]) == 1

    trade = _reload(open_trade)
    assert trade.outcome in ("WIN", "LOSS")
    assert "session" in (trade.close_reason or "").lower()


def test_an_unreachable_broker_skips_management_entirely(monkeypatch, open_trade):
    """An empty position list is indistinguishable from 'gone'; never guess."""
    import modules.market_data_forex as mdf
    monkeypatch.setattr(mdf, "get_open_positions", lambda: None)

    stats = pm.manage_open_positions(NOW)
    assert stats["checked"] == 0
    assert "broker unavailable" in stats.get("skipped", "")

    trade = _reload(open_trade)
    assert trade.outcome == "OPEN", "an unreachable broker closed a live trade"


def test_management_never_raises(monkeypatch, open_trade):
    """A management failure must not take the monitor job down."""
    import modules.market_data_forex as mdf

    def boom():
        raise RuntimeError("venue exploded")

    monkeypatch.setattr(mdf, "get_open_positions", boom)
    stats = pm.manage_open_positions(NOW)
    assert isinstance(stats, dict)
    assert stats["errors"] >= 1


# ══════════════════════════════════════════════════════════════════════════════
#  PERSISTENCE ACROSS A RESTART
# ══════════════════════════════════════════════════════════════════════════════

def test_the_management_state_is_persisted_on_the_trade_row():
    """
    A restart must resume from the stored flags. They are read from the DB row
    rather than held in memory, so a process restart loses nothing.
    """
    from models import ForexTrade
    for field in ("tp1_done", "tp2_done", "tp3_done", "breakeven_done",
                  "trailing_active", "peak_price", "initial_stop",
                  "initial_risk", "original_lots", "session_name",
                  "session_expires_at", "close_reason"):
        assert hasattr(ForexTrade, field), f"ForexTrade is missing {field}"


def test_the_light_migration_covers_every_new_column():
    """A deployed database must gain the columns, not crash on first read."""
    import re
    src = open("database.py", encoding="utf-8").read()
    block = src.split('"forex_trades": [', 1)[1].split("],", 1)[0]
    for col in ("tp3", "original_lots", "initial_stop", "initial_risk",
                "tp1_done", "tp2_done", "tp3_done", "breakeven_done",
                "trailing_active", "peak_price", "session_name",
                "session_expires_at", "management_state", "close_reason"):
        assert f'"{col}"' in block, f"migration is missing forex_trades.{col}"


# ══════════════════════════════════════════════════════════════════════════════
#  BROKER CAPABILITY — PARTIAL CLOSE AND AMEND
# ══════════════════════════════════════════════════════════════════════════════

def test_partial_close_sends_a_size_body(monkeypatch):
    """A bare DELETE closes everything; the size body is what makes it partial."""
    import modules.market_data_forex as mdf

    captured = {}

    class FakeResp:
        status_code = 200

        def json(self):
            return {}

    def fake_delete(path, body=None):
        captured["path"] = path
        captured["body"] = body
        return FakeResp()

    monkeypatch.setattr(mdf._session, "delete", fake_delete)
    monkeypatch.setattr(mdf, "get_open_positions",
                        lambda: [{"id": "deal-9", "symbol": "EURUSD",
                                  "size": 10000.0, "unrealized_pnl": 5.0}])

    result = mdf.close_position("deal-9", size=5000.0)
    assert result["success"] is True
    assert result["partial"] is True
    assert result["remaining"] == pytest.approx(5000.0)
    assert captured["body"] == {"size": 5000.0}
    assert captured["path"].endswith("/positions/deal-9")


def test_a_full_close_sends_no_body(monkeypatch):
    import modules.market_data_forex as mdf

    captured = {}

    class FakeResp:
        status_code = 200

        def json(self):
            return {}

    def fake_delete(path, body=None):
        captured["body"] = body
        return FakeResp()

    monkeypatch.setattr(mdf._session, "delete", fake_delete)
    monkeypatch.setattr(mdf, "get_open_positions",
                        lambda: [{"id": "deal-9", "symbol": "EURUSD",
                                  "size": 10000.0, "unrealized_pnl": 5.0}])

    result = mdf.close_position("deal-9")
    assert result["partial"] is False
    assert captured["body"] is None


def test_a_partial_that_equals_the_whole_position_is_sent_as_a_full_close(monkeypatch):
    """
    Asking to close everything must not be sent as a partial, or the downstream
    remaining-size bookkeeping would be wrong.
    """
    import modules.market_data_forex as mdf

    captured = {}

    class FakeResp:
        status_code = 200

        def json(self):
            return {}

    def fake_delete(path, body=None):
        captured["body"] = body
        return FakeResp()

    monkeypatch.setattr(mdf._session, "delete", fake_delete)
    monkeypatch.setattr(mdf, "get_open_positions",
                        lambda: [{"id": "deal-9", "symbol": "EURUSD",
                                  "size": 10000.0, "unrealized_pnl": 5.0}])

    result = mdf.close_position("deal-9", size=10000.0)
    assert result["partial"] is False
    assert captured["body"] is None


def test_a_partial_with_a_non_positive_size_is_refused(monkeypatch):
    import modules.market_data_forex as mdf
    monkeypatch.setattr(mdf, "get_open_positions", lambda: [])
    result = mdf.close_position("deal-9", size=0.0)
    assert result["success"] is False


def test_amend_position_sends_only_the_levels_given(monkeypatch):
    """Amending the stop must not disturb the target."""
    import modules.market_data_forex as mdf

    captured = {}

    class FakeResp:
        status_code = 200

        def json(self):
            return {}

    def fake_put(path, body):
        captured["path"] = path
        captured["body"] = body
        return FakeResp()

    monkeypatch.setattr(mdf._session, "put", fake_put)

    result = mdf.amend_position("deal-9", sl=1.1000)
    assert result["success"] is True
    assert captured["body"] == {"stopLevel": 1.1}
    assert "profitLevel" not in captured["body"]


def test_amend_position_with_nothing_to_change_is_refused():
    import modules.market_data_forex as mdf
    assert mdf.amend_position("deal-9")["success"] is False


def test_amend_position_survives_a_broker_failure(monkeypatch):
    import modules.market_data_forex as mdf
    monkeypatch.setattr(mdf._session, "put", lambda path, body: None)
    result = mdf.amend_position("deal-9", sl=1.1)
    assert result["success"] is False
    assert "error" in result


# ══════════════════════════════════════════════════════════════════════════════
#  THE OLD CLOSE-AND-REOPEN PARTIAL IS GONE
# ══════════════════════════════════════════════════════════════════════════════

def test_the_partial_tp_no_longer_closes_and_reopens(monkeypatch):
    """
    The previous implementation closed the whole position and reopened half.
    If the reopen failed the trade was destroyed, and between the two calls the
    account held nothing. A partial is now one atomic call.
    """
    import inspect
    src = inspect.getsource(pm._check_partial_tp)
    assert "place_order" not in src, "the close-and-reopen workaround is back"
    assert "close_position" in src
    assert "size=size" in src
