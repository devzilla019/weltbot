"""
backend/tests/test_execution_sizing.py
Phase 4 — order validation, instrument specs and confidence-tier sizing.

No broker is contacted: the venue calls are stubbed and the assertions are about
the arithmetic and the validation gates, which is where the money is lost.
"""
import math

import pytest

from modules import forex_executor as fx


# ══════════════════════════════════════════════════════════════════════════════
#  INSTRUMENT SPECIFICATION — "lot" does not mean one thing
# ══════════════════════════════════════════════════════════════════════════════

def test_fx_contract_is_one_hundred_thousand_base_units():
    spec = fx.instrument_spec("EURUSD")
    assert spec["family"] == "fx"
    assert spec["contract_size"] == 100000.0
    assert spec["pip_size"] == 0.0001


def test_jpy_pairs_have_a_two_decimal_pip():
    spec = fx.instrument_spec("USDJPY")
    assert spec["pip_size"] == 0.01
    # A JPY pair is quoted in JPY, so the USD pip value is an approximation.
    assert spec["pip_value_per_lot"] == 7.0


def test_metals_use_their_own_contract_not_the_fx_one():
    """
    The whole point of the spec table: gold and silver are not 100,000-unit
    contracts, so a size computed for FX would be off by three orders of
    magnitude.
    """
    gold = fx.instrument_spec("XAUUSD")
    silver = fx.instrument_spec("XAGUSD")

    assert gold["family"] == silver["family"] == "metal"
    assert gold["contract_size"] == 100.0
    assert silver["contract_size"] == 5000.0
    assert gold["contract_size"] != fx.instrument_spec("EURUSD")["contract_size"]


def test_slash_and_case_do_not_change_the_spec():
    assert fx.instrument_spec("xau/usd") == fx.instrument_spec("XAUUSD")
    assert fx.instrument_spec("eurusd") == fx.instrument_spec("EURUSD")


def test_the_legacy_helpers_delegate_to_the_spec_table():
    """One source of truth: the old private helpers must not drift."""
    for symbol in ("EURUSD", "USDJPY", "XAUUSD", "XAGUSD"):
        spec = fx.instrument_spec(symbol)
        assert fx._pip_size(symbol) == spec["pip_size"]
        assert fx._pip_value_per_lot(symbol) == spec["pip_value_per_lot"]
        assert fx._contract_size(symbol) == spec["contract_size"]


def test_an_unknown_symbol_gets_the_fx_default():
    spec = fx.instrument_spec("SOMETHINGWEIRD")
    assert spec["family"] == "fx"
    assert spec["contract_size"] == 100000.0


# ══════════════════════════════════════════════════════════════════════════════
#  INSTRUMENT VALIDATION AGAINST BROKER RULES
# ══════════════════════════════════════════════════════════════════════════════

def test_a_known_symbol_validates():
    ok, reason, spec = fx.validate_instrument("EURUSD", {"min_deal_size": 1000})
    assert ok is True
    assert reason == "ok"
    assert spec["verified"] is True


def test_a_broker_minimum_at_or_above_a_full_lot_is_rejected():
    """
    If the broker's minimum order is a whole contract, our unit assumption is
    the wrong scale for that instrument. Sizing from it would be wrong by a
    factor of the contract size, so the instrument is refused rather than
    traded on a bad multiplier.
    """
    ok, reason, spec = fx.validate_instrument("EURUSD", {"min_deal_size": 100000})
    assert ok is False
    assert "unit assumption is wrong" in reason
    assert spec["contract_size"] == 100000.0


def test_an_empty_symbol_is_rejected():
    ok, reason, _ = fx.validate_instrument("", {})
    assert ok is False
    assert reason == "no symbol"


def test_missing_broker_rules_still_validate():
    ok, _, spec = fx.validate_instrument("XAUUSD", None)
    assert ok is True
    assert spec["family"] == "metal"


# ══════════════════════════════════════════════════════════════════════════════
#  ORDER VALIDATION
# ══════════════════════════════════════════════════════════════════════════════

RULES = {"min_deal_size": 1000.0, "min_increment": 100.0, "max_deal_size": 500000.0}


def test_a_well_formed_order_validates():
    assert fx.validate_order("EURUSD", 5000.0, 1.1000, RULES) == (True, "ok")


def test_a_size_below_the_broker_minimum_is_rejected():
    ok, reason = fx.validate_order("EURUSD", 500.0, 1.1000, RULES)
    assert ok is False
    assert "below broker minimum" in reason


def test_a_size_above_the_broker_maximum_is_rejected():
    ok, reason = fx.validate_order("EURUSD", 900000.0, 1.1000, RULES)
    assert ok is False
    assert "above broker maximum" in reason


def test_a_size_off_the_increment_grid_is_rejected():
    ok, reason = fx.validate_order("EURUSD", 5150.0, 1.1000, RULES)
    assert ok is False
    assert "increment" in reason


def test_a_size_on_the_increment_grid_is_accepted():
    assert fx.validate_order("EURUSD", 5100.0, 1.1000, RULES)[0] is True


@pytest.mark.parametrize("size", [0, -1, -0.5])
def test_non_positive_sizes_are_rejected(size):
    ok, reason = fx.validate_order("EURUSD", size, 1.1, RULES)
    assert ok is False
    assert "positive" in reason


@pytest.mark.parametrize("price", [0, -1])
def test_non_positive_prices_are_rejected(price):
    ok, reason = fx.validate_order("EURUSD", 5000.0, price, RULES)
    assert ok is False
    assert "positive" in reason


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), "abc", None])
def test_non_finite_or_unparseable_input_is_rejected(bad):
    ok, _ = fx.validate_order("EURUSD", bad, 1.1, RULES)
    assert ok is False
    ok, _ = fx.validate_order("EURUSD", 5000.0, bad, RULES)
    assert ok is False


def test_validation_without_rules_only_checks_the_arithmetic():
    assert fx.validate_order("EURUSD", 5000.0, 1.1, None) == (True, "ok")
    assert fx.validate_order("EURUSD", 0.0, 1.1, None)[0] is False


def test_an_empty_symbol_is_rejected():
    ok, reason = fx.validate_order("", 5000.0, 1.1, RULES)
    assert ok is False
    assert reason == "no symbol"


# ══════════════════════════════════════════════════════════════════════════════
#  INCREMENT SNAPPING
# ══════════════════════════════════════════════════════════════════════════════

def test_snapping_rounds_down_never_up():
    """
    Rounding UP could push a correctly-sized position past the risk cap and past
    the broker maximum. Rounding down only ever reduces exposure.
    """
    assert fx.snap_to_increment(5150.0, 100.0) == 5100.0
    assert fx.snap_to_increment(5199.9, 100.0) == 5100.0
    assert fx.snap_to_increment(5000.0, 100.0) == 5000.0


def test_snapping_below_one_increment_gives_zero():
    assert fx.snap_to_increment(50.0, 100.0) == 0.0


def test_snapping_with_no_increment_just_rounds():
    assert fx.snap_to_increment(1234.56789, 0) == 1234.5679


def test_snapping_survives_junk():
    assert fx.snap_to_increment("bad", 100.0) == 0.0


# ══════════════════════════════════════════════════════════════════════════════
#  CONFIDENCE TIERS
# ══════════════════════════════════════════════════════════════════════════════

def test_below_the_strategy_floor_the_multiplier_is_zero_not_the_smallest_tier():
    """
    "Below the floor" means "do not trade". Returning the smallest positive tier
    would let a caller that forgot its own gate open a position the engine had
    already rejected.
    """
    assert fx.confidence_size_multiplier(87.9) == 0.0
    assert fx.confidence_size_multiplier(0) == 0.0


def test_the_floor_band_is_sized_below_full():
    """88-89 is the marginal case, so it must get LESS than 1.0x."""
    assert fx.confidence_size_multiplier(88) == 0.75
    assert fx.confidence_size_multiplier(89) == 0.75


@pytest.mark.parametrize("score,expected", [
    (88, 0.75), (89.9, 0.75),
    (90, 1.00), (92.9, 1.00),
    (93, 1.25), (95.9, 1.25),
    (96, 1.50), (99, 1.50),
])
def test_each_tier_boundary(score, expected):
    assert fx.confidence_size_multiplier(score) == expected


def test_tier_boundaries_are_inclusive_at_the_bottom():
    """A score exactly on a threshold takes the higher tier."""
    assert fx.confidence_size_multiplier(90) > fx.confidence_size_multiplier(89.99)
    assert fx.confidence_size_multiplier(93) > fx.confidence_size_multiplier(92.99)
    assert fx.confidence_size_multiplier(96) > fx.confidence_size_multiplier(95.99)


def test_the_multiplier_never_decreases_as_confidence_rises():
    scores = [88 + i * 0.5 for i in range(0, 23)]
    mults = [fx.confidence_size_multiplier(s) for s in scores]
    assert mults == sorted(mults)


def test_no_tier_exceeds_the_hard_cap():
    for threshold, mult in fx.CONFIDENCE_SIZE_TIERS:
        assert mult <= fx.SILVER_MAX_SIZE_MULTIPLIER


def test_an_unparseable_confidence_is_refused():
    assert fx.confidence_size_multiplier(None) == 0.0
    assert fx.confidence_size_multiplier("abc") == 0.0


# ══════════════════════════════════════════════════════════════════════════════
#  COMBINED MULTIPLIER AND THE HARD CAP
# ══════════════════════════════════════════════════════════════════════════════

def test_a_healthy_account_gets_the_full_tier():
    mult, detail = fx.effective_size_multiplier(96, 10000)
    assert mult == 1.5
    assert detail["guard"] == 1.0
    assert detail["capped"] is False


def test_the_combined_multiplier_never_exceeds_the_cap(monkeypatch):
    """
    The cap must be applied AFTER the drawdown multiplier. Applying it first
    would let a capped tier be scaled back up by the guard, or exceeded outright
    if the guard ever returned more than 1.0.
    """
    import modules.risk_manager as rm
    monkeypatch.setattr(rm, "get_drawdown_guard", lambda _b: 4.0)

    mult, detail = fx.effective_size_multiplier(96, 1000)
    assert mult == fx.SILVER_MAX_SIZE_MULTIPLIER
    assert detail["guard"] == 1.0        # a guard above 1.0 is clamped
    assert mult <= fx.SILVER_MAX_SIZE_MULTIPLIER


def test_a_drawdown_guard_reduces_the_multiplier(monkeypatch):
    import modules.risk_manager as rm
    monkeypatch.setattr(rm, "get_drawdown_guard", lambda _b: 0.5)

    mult, detail = fx.effective_size_multiplier(96, 1000)
    assert mult == pytest.approx(0.75)   # 1.5 x 0.5
    assert detail["capped"] is False


def test_the_multiplier_has_a_floor_so_a_deep_drawdown_does_not_zero_a_trade(monkeypatch):
    import modules.risk_manager as rm
    monkeypatch.setattr(rm, "get_drawdown_guard", lambda _b: 0.05)

    mult, _ = fx.effective_size_multiplier(88, 1000)
    assert mult == fx.SILVER_MIN_SIZE_MULTIPLIER


def test_a_broken_drawdown_guard_does_not_halve_every_position(monkeypatch):
    """An unavailable risk manager must not silently change sizing."""
    import modules.risk_manager as rm

    def boom(_b):
        raise RuntimeError("risk manager down")

    monkeypatch.setattr(rm, "get_drawdown_guard", boom)
    mult, detail = fx.effective_size_multiplier(93, 1000)
    assert detail["guard"] == 1.0
    assert mult == 1.25


def test_a_sub_floor_score_yields_no_position_even_with_a_perfect_guard():
    mult, detail = fx.effective_size_multiplier(87, 100000)
    assert mult == 0.0
    assert "floor" in detail["reason"]


# ══════════════════════════════════════════════════════════════════════════════
#  SIZING END-TO-END
# ══════════════════════════════════════════════════════════════════════════════

@pytest.fixture
def broker(monkeypatch):
    """
    Stub the broker's dealing rules so sizing is deterministic.

    The rules are per-FAMILY because the broker's minimums are: an FX minimum
    of 1000 units is 1000 base-currency units, whereas a gold minimum of 0.1 is
    0.1 troy ounces. A single stub for both would make the metals tests pass
    for the wrong reason — or, as it did here at first, fail because a
    1000-ounce minimum implies a $2.4M position.
    """
    import modules.market_data_forex as mdf

    rules_by_family = {
        "fx": {"min_deal_size": 1000.0, "min_increment": 100.0,
               "max_deal_size": 500000.0},
        "metal": {"min_deal_size": 0.1, "min_increment": 0.1,
                  "max_deal_size": 50000.0},
    }

    def fake_rules(symbol):
        from modules.forex_executor import instrument_spec
        return dict(rules_by_family[instrument_spec(symbol)["family"]])

    monkeypatch.setattr(mdf, "get_dealing_rules", fake_rules)
    return rules_by_family["fx"]


def _broker_rules(symbol):
    from modules.forex_executor import instrument_spec
    if instrument_spec(symbol)["family"] == "metal":
        return {"min_deal_size": 0.1, "min_increment": 0.1,
                "max_deal_size": 50000.0}
    return {"min_deal_size": 1000.0, "min_increment": 100.0,
            "max_deal_size": 500000.0}


def test_sizing_produces_a_valid_grid_aligned_quantity(broker):
    size = fx.calculate_position_size("EURUSD", 1.1000, 1.0950, 93, 10000)
    assert size > 0
    assert fx.validate_order("EURUSD", size, 1.1000, broker)[0] is True


def test_a_higher_confidence_produces_a_larger_size(broker):
    low = fx.calculate_position_size("EURUSD", 1.1000, 1.0950, 88, 10000)
    high = fx.calculate_position_size("EURUSD", 1.1000, 1.0950, 96, 10000)
    assert high > low


def test_a_sub_floor_confidence_produces_no_size(broker):
    assert fx.calculate_position_size("EURUSD", 1.1000, 1.0950, 87, 10000) == 0.0


def test_a_stop_too_tight_to_size_is_refused(broker):
    assert fx.calculate_position_size("EURUSD", 1.1000, 1.09995, 93, 10000) == 0.0


def test_no_balance_is_refused(broker):
    assert fx.calculate_position_size("EURUSD", 1.1000, 1.0950, 93, 0) == 0.0


def test_a_balance_below_the_tradeable_minimum_is_refused(broker, monkeypatch):
    import config
    monkeypatch.setattr(config, "FOREX_MIN_TRADEABLE_BALANCE", 500.0)
    assert fx.calculate_position_size("EURUSD", 1.1000, 1.0950, 93, 100) == 0.0


def test_the_broker_minimum_raising_size_past_the_risk_ceiling_is_refused(
        broker, monkeypatch):
    """
    On a small account the broker's minimum order can imply far more risk than
    the target. The trade must be refused, not opened oversized.
    """
    import config
    monkeypatch.setattr(config, "FOREX_MAX_IMPLIED_RISK_PCT", 0.005)

    size = fx.calculate_position_size("EURUSD", 1.1000, 1.0500, 93, 200)
    assert size == 0.0


def test_metals_are_sized_on_their_own_contract(broker):
    """
    Gold is 100 oz per lot, so the same risk must produce a very different unit
    count from an FX pair. If both used the 100,000-unit FX contract the gold
    position would be three orders of magnitude too large.
    """
    fx_size = fx.calculate_position_size("EURUSD", 1.1000, 1.0950, 93, 10000)
    gold_size = fx.calculate_position_size("XAUUSD", 2400.0, 2390.0, 93, 10000)

    assert fx_size > 0
    assert gold_size > 0
    assert gold_size < fx_size


def test_metals_are_validated_against_metal_rules(broker):
    """The gold order must pass the metal minimum, not the FX one."""
    size = fx.calculate_position_size("XAUUSD", 2400.0, 2390.0, 93, 10000)
    assert fx.validate_order("XAUUSD", size, 2400.0, _broker_rules("XAUUSD"))[0] is True
    # The same size would be far below an FX minimum, which is exactly why the
    # rules have to come from the instrument rather than a shared default.
    assert fx.validate_order("EURUSD", size, 1.1, _broker_rules("EURUSD"))[0] is False


def test_sizing_never_exceeds_the_symbol_risk_cap(broker, monkeypatch):
    """
    A fixed tier must not silently override the hard risk limit. Whatever the
    tier and the guard, the implied risk stays under the ceiling.
    """
    import config
    from modules.market_data_forex import get_dealing_rules

    balance = 10000.0
    for confidence in (88, 90, 93, 96, 99):
        size = fx.calculate_position_size("EURUSD", 1.1000, 1.0950,
                                          confidence, balance)
        if size <= 0:
            continue
        spec = fx.instrument_spec("EURUSD")
        risk_pips = abs(1.1000 - 1.0950) / spec["pip_size"]
        implied = (size / spec["contract_size"]) * risk_pips * spec["pip_value_per_lot"]
        assert implied / balance <= config.FOREX_MAX_IMPLIED_RISK_PCT + 1e-9


def test_sizing_survives_a_broker_rule_failure(broker, monkeypatch):
    """Unavailable dealing rules must not crash sizing."""
    import modules.market_data_forex as mdf
    monkeypatch.setattr(mdf, "get_dealing_rules", lambda _s: {})
    size = fx.calculate_position_size("EURUSD", 1.1000, 1.0950, 93, 10000)
    assert size >= 0


# ══════════════════════════════════════════════════════════════════════════════
#  CRYPTO SIZING (base-asset units, not lots)
# ══════════════════════════════════════════════════════════════════════════════

def test_crypto_sizing_returns_base_asset_units():
    """
    The quantity is base-asset units, derived as risk / stop-distance and then
    snapped to the exchange step. The expected value is computed from config
    rather than hardcoded, so a risk-percentage change does not silently break
    the test — but the RELATIONSHIP is what is being asserted.
    """
    from modules.executor import calculate_silver_bullet_crypto_size
    from modules.forex_executor import confidence_size_multiplier
    from config import MAX_RISK_PCT

    balance, entry, stop, conf = 10000.0, 60000.0, 59000.0, 93
    out = calculate_silver_bullet_crypto_size("BTC/USDT", entry, stop, conf, balance)

    assert out["ok"] is True
    expected_risk = balance * MAX_RISK_PCT * confidence_size_multiplier(conf)
    assert out["risk_quote"] == pytest.approx(expected_risk, rel=1e-6)
    assert out["qty"] == pytest.approx(expected_risk / (entry - stop), rel=1e-3)
    assert out["notional"] > 0


def test_crypto_quantity_is_snapped_to_the_exchange_step():
    from modules.executor import calculate_silver_bullet_crypto_size
    out = calculate_silver_bullet_crypto_size("BTC/USDT", 60000.0, 59500.0, 93, 10000)
    assert out["ok"] is True
    step = out["step"]
    assert step > 0
    assert abs(round(out["qty"] / step) - out["qty"] / step) < 1e-9


def test_crypto_uses_the_same_tiers_as_fx():
    """A 93 must be worth the same fraction of risk on BTC as on EURUSD."""
    from modules.executor import calculate_silver_bullet_crypto_size
    from modules.forex_executor import confidence_size_multiplier

    for conf in (88, 90, 93, 96):
        out = calculate_silver_bullet_crypto_size("BTC/USDT", 60000.0, 59000.0,
                                                  conf, 100000)
        assert out["multiplier"] == confidence_size_multiplier(conf)


def test_crypto_below_the_floor_is_refused():
    from modules.executor import calculate_silver_bullet_crypto_size
    out = calculate_silver_bullet_crypto_size("BTC/USDT", 60000.0, 59000.0, 87, 10000)
    assert out["ok"] is False
    assert "floor" in out["reason"]


def test_crypto_below_the_minimum_notional_is_refused():
    """A sub-minimum order is rejected by Binance, and upsizing would exceed the risk."""
    from modules.executor import calculate_silver_bullet_crypto_size
    out = calculate_silver_bullet_crypto_size("BTC/USDT", 60000.0, 59000.0, 88, 20)
    assert out["ok"] is False
    assert "notional" in out["reason"] or "step" in out["reason"]


def test_crypto_refuses_a_zero_stop_distance():
    from modules.executor import calculate_silver_bullet_crypto_size
    out = calculate_silver_bullet_crypto_size("BTC/USDT", 60000.0, 60000.0, 93, 10000)
    assert out["ok"] is False
    assert "stop distance" in out["reason"]


def test_crypto_refuses_non_finite_input():
    from modules.executor import calculate_silver_bullet_crypto_size
    assert calculate_silver_bullet_crypto_size("BTC/USDT", float("nan"), 1.0,
                                               93, 10000)["ok"] is False
    assert calculate_silver_bullet_crypto_size("BTC/USDT", 100.0, 1.0,
                                               93, 0)["ok"] is False


def test_crypto_falls_back_to_known_step_rules_when_the_exchange_is_unreachable(
        monkeypatch):
    import modules.market_data as md
    monkeypatch.setattr(md, "get_lot_size_rules",
                        lambda _s: (_ for _ in ()).throw(RuntimeError("offline")))
    from modules.executor import crypto_step_and_min
    step, min_notional = crypto_step_and_min("BTC/USDT")
    assert step == 0.001
    assert min_notional == 5.0


def test_the_smc_crypto_path_signature_is_preserved():
    """
    `executor.place_order` gained a `strategy` parameter so the shared guard can
    deny an unidentifiable caller. The original parameters must survive in
    order, because the retired SMC path is still the reference for how that
    function is called.
    """
    import inspect
    from modules import executor
    sig = inspect.signature(executor.place_order)
    assert list(sig.parameters)[:6] == [
        "symbol", "signal", "position_units", "stop_loss", "take_profit",
        "confidence",
    ]
    # The new parameter must be optional, or every existing caller breaks.
    assert sig.parameters["strategy"].default is None


def test_the_crypto_executor_refuses_an_unidentified_order(monkeypatch):
    """The chokepoint denies before any exchange call."""
    from modules import executor
    import modules.market_data as md

    reached = []
    monkeypatch.setattr(md, "place_order_raw",
                        lambda *a, **k: reached.append(a) or {"success": True})

    result = executor.place_order("BTC/USDT", "BUY", 0.01, 59000, 61000, 95)
    assert result["success"] is False
    assert result.get("blocked") is True
    assert reached == [], "an unidentified order reached the exchange"
