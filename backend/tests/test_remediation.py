"""
backend/tests/test_remediation.py
Phase 5 remediation — the 20:30 profitable-position policy and the legacy
strategy entry lock.

Every broker interaction is stubbed. No live order is sent, and no network call
is made: `market_data_forex`'s position fetch and close are replaced, so these
tests exercise the decision logic and the audit trail rather than the venue.
"""
from datetime import datetime

import pytest

from modules import forex_executor as fx
from modules import forex_position_manager as pm
from modules import market_data_forex as mdf
from models import ForexTrade


EOD_NOW = datetime(2026, 10, 15, 20, 30, 0)


@pytest.fixture
def broker(monkeypatch):
    """
    A stub Capital.com book: open positions with their unrealised P&L, plus a
    recorded close log.

    `clear_caches` is stubbed to a no-op so the policy's forced refresh does not
    reach the real cache-clearing code, and `get_open_positions` is replaced so
    no HTTP request is attempted.
    """
    state = {
        "positions": [],
        "positions_ok": True,
        "close_results": {},        # deal_id -> result dict
        "close_calls": [],
    }

    def fake_positions():
        if not state["positions_ok"]:
            return None
        return list(state["positions"])

    def fake_close(deal_id, size=None):
        state["close_calls"].append({"deal_id": deal_id, "size": size})
        return state["close_results"].get(
            deal_id, {"success": True, "pnl": 0.0, "symbol": "?", "partial": False})

    monkeypatch.setattr(mdf, "clear_caches", lambda: None)
    monkeypatch.setattr(mdf, "get_open_positions", fake_positions)
    monkeypatch.setattr(mdf, "close_position", fake_close)
    return state


@pytest.fixture
def make_trade():
    """Create an OPEN ForexTrade row and delete it afterwards."""
    created = []

    def _make(symbol="EURUSD", signal="BUY", deal_id="deal-1", **kw):
        db = pm.SessionLocal()
        trade = ForexTrade(
            symbol=symbol, signal=signal, confidence=kw.pop("confidence", 93.0),
            entry_price=kw.pop("entry_price", 1.1000),
            stop_loss=kw.pop("stop_loss", 1.0950),
            take_profit=kw.pop("take_profit", 1.1150),
            lots=kw.pop("lots", 10000.0),
            original_lots=kw.pop("original_lots", 10000.0),
            metaapi_position_id=deal_id, outcome="OPEN",
            **kw,
        )
        db.add(trade)
        db.commit()
        tid = trade.id
        db.close()
        created.append(tid)
        return tid

    yield _make

    db = pm.SessionLocal()
    for tid in created:
        db.query(ForexTrade).filter(ForexTrade.id == tid).delete()
    db.commit()
    db.close()


def _reload(tid):
    db = pm.SessionLocal()
    try:
        t = db.query(ForexTrade).filter(ForexTrade.id == tid).first()
        if t:
            db.expunge(t)
        return t
    finally:
        db.close()


def _pos(deal_id, upl, symbol="EURUSD"):
    return {"id": deal_id, "symbol": symbol, "unrealized_pnl": upl,
            "size": 10000.0, "entry_price": 1.1, "current_price": 1.1}


# ══════════════════════════════════════════════════════════════════════════════
#  THE PROFITABILITY RULE (pure)
# ══════════════════════════════════════════════════════════════════════════════

class _T:
    """Minimal trade stand-in; the rule only needs the row to exist."""
    symbol = "EURUSD"


def test_a_profitable_position_is_eligible():
    ok, reason = pm.eod_close_eligibility(_T(), 25.0)
    assert ok is True
    assert "profitable" in reason


def test_a_losing_position_is_not_eligible():
    ok, reason = pm.eod_close_eligibility(_T(), -25.0)
    assert ok is False
    assert "losing" in reason


def test_a_flat_position_is_not_eligible():
    """Zero is not profit, and the rule was specified for profitable positions."""
    ok, reason = pm.eod_close_eligibility(_T(), 0.0)
    assert ok is False
    assert "flat" in reason


def test_an_unreadable_pnl_is_not_eligible():
    """
    An unknown P&L must not be guessed at. The asymmetry is deliberate: holding
    a position a few hours longer is recoverable, closing one by mistake is not.
    """
    ok, reason = pm.eod_close_eligibility(_T(), None)
    assert ok is False
    assert "unavailable" in reason


def test_a_tiny_profit_still_counts():
    ok, _ = pm.eod_close_eligibility(_T(), 0.01)
    assert ok is True


def test_the_strict_profitability_flag_is_on_by_default():
    assert pm.EOD_REQUIRE_STRICTLY_PROFITABLE is True


# ══════════════════════════════════════════════════════════════════════════════
#  P&L LOOKUP FROM THE BROKER
# ══════════════════════════════════════════════════════════════════════════════

def test_pnl_is_read_from_the_broker_position():
    assert pm._position_pnl_from_broker("d1", [_pos("d1", 12.5)]) == pytest.approx(12.5)


def test_a_missing_deal_gives_none_not_zero():
    """
    The deal is not in the broker's book, so its P&L is unknown. Returning 0.0
    would make it look flat rather than unknown.
    """
    assert pm._position_pnl_from_broker("d9", [_pos("d1", 12.5)]) is None


def test_a_missing_pnl_field_gives_none():
    assert pm._position_pnl_from_broker("d1", [{"id": "d1"}]) is None


def test_an_unparseable_pnl_gives_none():
    assert pm._position_pnl_from_broker("d1", [{"id": "d1", "unrealized_pnl": "x"}]) is None


def test_no_deal_id_gives_none():
    assert pm._position_pnl_from_broker("", [_pos("d1", 1.0)]) is None
    assert pm._position_pnl_from_broker(None, [_pos("d1", 1.0)]) is None


# ══════════════════════════════════════════════════════════════════════════════
#  THE 20:30 JOB — CLOSING PROFITABLE POSITIONS
# ══════════════════════════════════════════════════════════════════════════════

def test_the_job_closes_an_eligible_profitable_position(broker, make_trade):
    tid = make_trade(symbol="GBPUSD", deal_id="p1")
    broker["positions"] = [_pos("p1", 60.0, "GBPUSD")]
    broker["close_results"]["p1"] = {"success": True, "pnl": 58.4, "symbol": "GBPUSD"}

    result = pm.end_of_day_policy(now=EOD_NOW)

    assert result["eligible"] == 1
    assert result["closed_positions"] == 1
    assert result["failed_closes"] == 0
    assert result["pnl"] == pytest.approx(58.4)
    assert broker["close_calls"] == [{"deal_id": "p1", "size": None}]

    trade = _reload(tid)
    assert trade.outcome == "WIN"
    assert trade.pnl == pytest.approx(58.4)
    assert trade.closed_at is not None


def test_the_job_uses_the_brokers_realised_pnl_not_its_own_estimate(broker, make_trade):
    """
    The UPL read at decision time and the realised P&L differ — the close moves
    the price and applies costs. The RECORDED figure must be the broker's.
    """
    tid = make_trade(deal_id="p1")
    broker["positions"] = [_pos("p1", 100.0)]
    broker["close_results"]["p1"] = {"success": True, "pnl": 96.5}

    pm.end_of_day_policy(now=EOD_NOW)

    trade = _reload(tid)
    assert trade.pnl == pytest.approx(96.5)
    assert trade.pnl != pytest.approx(100.0)


def test_the_job_records_the_upl_it_decided_on(broker, make_trade):
    """The audit trail must show what the decision was based on."""
    make_trade(deal_id="p1")
    broker["positions"] = [_pos("p1", 42.0)]
    broker["close_results"]["p1"] = {"success": True, "pnl": 41.0}

    result = pm.end_of_day_policy(now=EOD_NOW)
    assert result["closed"][0]["upl_at_decision"] == pytest.approx(42.0)
    assert "profitable" in result["closed"][0]["reason"]


def test_the_job_does_not_close_a_losing_position(broker, make_trade):
    tid = make_trade(deal_id="l1")
    broker["positions"] = [_pos("l1", -75.0)]

    result = pm.end_of_day_policy(now=EOD_NOW)

    assert result["closed_positions"] == 0
    assert result["eligible"] == 0
    assert broker["close_calls"] == []
    assert result["held_positions"] == 1
    assert "losing" in result["held"][0]["reason"]

    assert _reload(tid).outcome == "OPEN"


def test_the_job_does_not_close_a_flat_position(broker, make_trade):
    tid = make_trade(deal_id="f1")
    broker["positions"] = [_pos("f1", 0.0)]

    result = pm.end_of_day_policy(now=EOD_NOW)

    assert result["closed_positions"] == 0
    assert "flat" in result["held"][0]["reason"]
    assert _reload(tid).outcome == "OPEN"


def test_the_job_does_not_close_a_position_whose_pnl_is_unknown(broker, make_trade):
    """
    A position the broker did not report a P&L for must be held, not guessed at
    in either direction.
    """
    tid = make_trade(deal_id="u1")
    broker["positions"] = [{"id": "u1", "symbol": "EURUSD"}]   # no unrealized_pnl

    result = pm.end_of_day_policy(now=EOD_NOW)

    assert result["closed_positions"] == 0
    assert "unavailable" in result["held"][0]["reason"]
    assert _reload(tid).outcome == "OPEN"


def test_a_mixed_book_closes_only_the_profitable_side(broker, make_trade):
    """The rule must partition the book, not apply to it wholesale."""
    win = make_trade(symbol="EURUSD", deal_id="w1")
    loss = make_trade(symbol="GBPUSD", deal_id="l1")
    flat = make_trade(symbol="USDJPY", deal_id="f1")

    broker["positions"] = [_pos("w1", 50.0), _pos("l1", -30.0, "GBPUSD"),
                           _pos("f1", 0.0, "USDJPY")]
    broker["close_results"]["w1"] = {"success": True, "pnl": 49.0}

    result = pm.end_of_day_policy(now=EOD_NOW)

    assert result["closed_positions"] == 1
    assert result["held_positions"] == 2
    assert broker["close_calls"] == [{"deal_id": "w1", "size": None}]

    assert _reload(win).outcome == "WIN"
    assert _reload(loss).outcome == "OPEN"
    assert _reload(flat).outcome == "OPEN"


# ══════════════════════════════════════════════════════════════════════════════
#  FAILURE HANDLING
# ══════════════════════════════════════════════════════════════════════════════

def test_a_rejected_close_is_not_reported_as_a_close(broker, make_trade):
    """
    The most important assertion in this file: a broker rejection must not
    settle the trade or be counted as a successful close.
    """
    tid = make_trade(deal_id="p1")
    broker["positions"] = [_pos("p1", 80.0)]
    broker["close_results"]["p1"] = {"success": False, "error": "market closed"}

    result = pm.end_of_day_policy(now=EOD_NOW)

    assert result["closed_positions"] == 0
    assert result["failed_closes"] == 1
    assert result["pnl"] == 0.0
    assert result["failed"][0]["error"] == "market closed"

    trade = _reload(tid)
    assert trade.outcome == "OPEN", "a rejected close settled the trade"
    assert trade.pnl is None
    assert "failed" in (trade.close_reason or "")


def test_a_failed_close_is_retried_on_the_next_run(broker, make_trade):
    """The row stays OPEN, so the next invocation tries again."""
    tid = make_trade(deal_id="p1")
    broker["positions"] = [_pos("p1", 80.0)]
    broker["close_results"]["p1"] = {"success": False, "error": "timeout"}

    first = pm.end_of_day_policy(now=EOD_NOW)
    assert first["failed_closes"] == 1
    assert _reload(tid).outcome == "OPEN"

    # The broker recovers.
    broker["close_results"]["p1"] = {"success": True, "pnl": 79.0}
    second = pm.end_of_day_policy(now=EOD_NOW)

    assert second["closed_positions"] == 1
    assert _reload(tid).outcome == "WIN"


def test_an_unreachable_broker_closes_nothing(broker, make_trade):
    """
    An empty position list is indistinguishable from 'the broker is down'. No
    decision may be taken on either, so the profitable position is HELD rather
    than closed blind.
    """
    tid = make_trade(deal_id="p1")
    broker["positions_ok"] = False

    result = pm.end_of_day_policy(now=EOD_NOW)

    assert result["closed_positions"] == 0
    assert broker["close_calls"] == []
    assert result["errors"] >= 1
    assert "broker unavailable" in result["held"][0]["reason"]
    assert _reload(tid).outcome == "OPEN"


def test_a_position_with_no_deal_id_is_reported_not_closed(broker, make_trade):
    """Without a deal id there is nothing to close, and guessing is not an option."""
    tid = make_trade(deal_id=None)
    broker["positions"] = []

    result = pm.end_of_day_policy(now=EOD_NOW)

    assert result["closed_positions"] == 0
    assert result["errors"] >= 1
    assert "no broker deal id" in result["failed"][0]["reason"]
    assert _reload(tid).outcome == "OPEN"


def test_a_crash_during_the_close_does_not_settle_the_trade(broker, make_trade, monkeypatch):
    tid = make_trade(deal_id="p1")
    broker["positions"] = [_pos("p1", 80.0)]

    def boom(deal_id, size=None):
        raise RuntimeError("socket exploded")

    monkeypatch.setattr(mdf, "close_position", boom)

    result = pm.end_of_day_policy(now=EOD_NOW)

    assert result["closed_positions"] == 0
    assert result["errors"] >= 1
    assert _reload(tid).outcome == "OPEN"


def test_the_policy_never_raises(broker, monkeypatch):
    monkeypatch.setattr(mdf, "get_open_positions",
                        lambda: (_ for _ in ()).throw(RuntimeError("boom")))
    result = pm.end_of_day_policy(now=EOD_NOW)
    assert isinstance(result, dict)


# ══════════════════════════════════════════════════════════════════════════════
#  DUPLICATE EXECUTION
# ══════════════════════════════════════════════════════════════════════════════

def test_a_second_run_does_not_close_the_same_position_twice(broker, make_trade):
    """
    APScheduler's coalesce and a manual trigger can both fire this job. Once the
    trade row is settled it is no longer OPEN, so the second run cannot see it.
    """
    tid = make_trade(deal_id="p1")
    broker["positions"] = [_pos("p1", 60.0)]
    broker["close_results"]["p1"] = {"success": True, "pnl": 59.0}

    first = pm.end_of_day_policy(now=EOD_NOW)
    second = pm.end_of_day_policy(now=EOD_NOW)

    assert first["closed_positions"] == 1
    assert second["closed_positions"] == 0
    assert len(broker["close_calls"]) == 1, "the position was closed twice"
    assert _reload(tid).pnl == pytest.approx(59.0)


def test_a_duplicate_run_does_not_double_count_the_pnl(broker, make_trade):
    make_trade(deal_id="p1")
    broker["positions"] = [_pos("p1", 60.0)]
    broker["close_results"]["p1"] = {"success": True, "pnl": 59.0}

    pm.end_of_day_policy(now=EOD_NOW)
    second = pm.end_of_day_policy(now=EOD_NOW)

    assert second["pnl"] == 0.0


def test_the_policy_cancels_setups_once_even_if_run_twice(broker, monkeypatch):
    from modules import silver_bullet as sb

    sb.reset_daily_cache("test")
    sb._active_setups["EURUSD"] = {"symbol": "EURUSD", "session": "NY_AFTERNOON"}

    first = pm.end_of_day_policy(now=EOD_NOW)
    second = pm.end_of_day_policy(now=EOD_NOW)

    assert first["cancelled_setups"] == 1
    assert second["cancelled_setups"] == 0
    sb.reset_daily_cache("test")


# ══════════════════════════════════════════════════════════════════════════════
#  PARTIAL-CLOSE STATE
# ══════════════════════════════════════════════════════════════════════════════

def test_a_partially_closed_position_is_judged_on_its_remaining_size(broker, make_trade):
    """
    The broker's UPL already reflects the reduced size, so a position that has
    taken TP1 and is still net positive on the remainder is closable, and one
    that has given the profit back is not. Nothing is re-derived from `lots`.
    """
    tid = make_trade(deal_id="p1", lots=5000.0, original_lots=10000.0,
                     tp1_done=True, partial_close_pct=50.0)
    broker["positions"] = [_pos("p1", 5.0)]
    broker["close_results"]["p1"] = {"success": True, "pnl": 4.5}

    result = pm.end_of_day_policy(now=EOD_NOW)

    assert result["closed_positions"] == 1
    # Closed in FULL (size=None): the end-of-day policy retires the position, it
    # does not take another partial.
    assert broker["close_calls"] == [{"deal_id": "p1", "size": None}]
    assert _reload(tid).outcome == "WIN"


def test_a_partially_closed_position_that_is_now_losing_is_held(broker, make_trade):
    tid = make_trade(deal_id="p1", lots=2500.0, original_lots=10000.0,
                     tp1_done=True, tp2_done=True, partial_close_pct=75.0)
    broker["positions"] = [_pos("p1", -3.0)]

    result = pm.end_of_day_policy(now=EOD_NOW)

    assert result["closed_positions"] == 0
    assert _reload(tid).outcome == "OPEN"


# ══════════════════════════════════════════════════════════════════════════════
#  THE SCHEDULED JOB USES UTC
# ══════════════════════════════════════════════════════════════════════════════

def test_the_eod_job_runs_at_2030_utc():
    import main
    from modules.forex_position_manager import EOD_HOUR, EOD_MINUTE

    assert (EOD_HOUR, EOD_MINUTE) == (20, 30)

    job = next(j for j in main.scheduler.get_jobs() if j.id == "forex_end_of_day")
    fields = {f.name: str(f) for f in job.trigger.fields}
    assert fields["hour"] == "20"
    assert fields["minute"] == "30"
    assert str(job.trigger.timezone) == "UTC"


def test_the_scheduler_uses_the_profitable_only_policy(broker, make_trade, monkeypatch):
    """
    The registered job must call the policy WITHOUT `close_open`, so the
    close-everything switch can never be reached by the schedule.
    """
    import main

    seen = {}

    def fake_policy(now=None, close_open=False):
        seen["close_open"] = close_open
        return {"cancelled_setups": 0, "held_positions": 0, "errors": 0}

    monkeypatch.setattr(pm, "end_of_day_policy", fake_policy)
    monkeypatch.setattr("config.FOREX_ENABLED", True)

    main.run_end_of_day_policy()

    assert seen.get("close_open") is False, \
        "the scheduled job asked to close every position, not just profitable ones"


# ══════════════════════════════════════════════════════════════════════════════
#  LEGACY ENTRY LOCK
# ══════════════════════════════════════════════════════════════════════════════

def test_legacy_entries_are_disabled_by_default():
    assert fx.legacy_entries_enabled() is False


def test_silver_bullet_may_submit():
    ok, reason = fx.order_source_allowed(fx.STRATEGY_SILVER_BULLET)
    assert ok is True
    assert reason == "ok"


def test_legacy_crt_may_not_submit():
    ok, reason = fx.order_source_allowed(fx.STRATEGY_LEGACY_CRT)
    assert ok is False
    assert "retired" in reason


def test_legacy_smc_may_not_submit():
    """The SMC engine is retired too, not just the CRT one."""
    from modules.strategy_guard import STRATEGY_LEGACY_SMC
    ok, reason = fx.order_source_allowed(STRATEGY_LEGACY_SMC)
    assert ok is False
    assert "retired" in reason


def test_an_unidentified_source_may_not_submit():
    """
    A caller that does not identify itself predates the check, and those are
    exactly the callers the lock exists to stop.
    """
    ok, reason = fx.order_source_allowed(None)
    assert ok is False
    assert "unidentified" in reason

    ok, _ = fx.order_source_allowed("SOME_OLD_STRATEGY")
    assert ok is False


def test_the_lock_fails_closed_when_the_flag_cannot_be_read(monkeypatch):
    """
    The whole point: an old strategy must never submit an order merely because
    the new scanner is unavailable, misconfigured, or mid-deploy.
    """
    import builtins

    real_import = builtins.__import__

    def failing_import(name, *a, **k):
        if name == "config":
            raise ImportError("config unavailable")
        return real_import(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", failing_import)
    assert fx.legacy_entries_enabled() is False


def test_place_forex_order_refuses_a_legacy_order(monkeypatch):
    """
    The chokepoint refuses before any broker call. `place_order` is patched to a
    sentinel that records whether it was reached.
    """
    reached = []
    monkeypatch.setattr(mdf, "place_order",
                        lambda *a, **k: reached.append(a) or {"success": True})

    result = fx.place_forex_order(
        {"symbol": "EURUSD", "signal": "BUY", "entry_price": 1.1,
         "stop_loss": 1.095, "take_profit": 1.11, "confidence": 95},
        {},
        strategy=fx.STRATEGY_LEGACY_CRT,
    )

    assert result["success"] is False
    assert result.get("blocked") is True
    assert "retired" in result["error"]
    assert reached == [], "a legacy order reached the broker"


def test_place_forex_order_refuses_an_unidentified_caller(monkeypatch):
    reached = []
    monkeypatch.setattr(mdf, "place_order",
                        lambda *a, **k: reached.append(a) or {"success": True})

    result = fx.place_forex_order(
        {"symbol": "EURUSD", "signal": "BUY", "entry_price": 1.1,
         "stop_loss": 1.095, "take_profit": 1.11, "confidence": 95},
        {},
    )

    assert result["success"] is False
    assert reached == []


def test_the_lock_can_be_opened_deliberately(monkeypatch):
    """The escape hatch exists, it just is not the default."""
    from modules import strategy_guard
    monkeypatch.setattr(strategy_guard, "legacy_entries_enabled", lambda: True)
    ok, reason = strategy_guard.order_source_allowed(
        strategy_guard.STRATEGY_LEGACY_CRT)
    assert ok is True
    assert "explicitly enabled" in reason


def test_silver_bullet_is_unaffected_by_the_lock(monkeypatch):
    """The lock must not break the strategy it exists to protect."""
    monkeypatch.setattr(fx, "LEGACY_FOREX_ENTRIES_ENABLED", False)
    assert fx.order_source_allowed(fx.STRATEGY_SILVER_BULLET)[0] is True


# ══════════════════════════════════════════════════════════════════════════════
#  NO LEGACY ENTRY PATH SUBMITS
# ══════════════════════════════════════════════════════════════════════════════

def test_the_legacy_entry_job_returns_before_evaluating_setups(monkeypatch):
    """
    It must return early rather than evaluating setups whose orders would be
    refused — that wastes broker API calls and pollutes the diagnostics.
    """
    import main

    evaluated = []
    monkeypatch.setattr("modules.forex_signal_engine.check_entry_condition_refined",
                        lambda *a, **k: evaluated.append(1))
    monkeypatch.setattr("config.FOREX_ENABLED", True)

    main._forex_active_setups = {"EURUSD": {"trend_direction": "BULLISH"}}
    main.run_forex_entry_check()

    assert evaluated == [], "the legacy job evaluated setups despite the lock"
    assert main._forex_active_setups == {}, "stale setups were left advertised"


def test_the_crt_scan_does_not_arm_setups_while_locked(monkeypatch):
    """
    The scan still refreshes levels for the dashboard, but must not populate the
    legacy entry queue.
    """
    import main

    monkeypatch.setattr("config.FOREX_ENABLED", True)
    monkeypatch.setattr("config.FOREX_PAIRS", ["EURUSD"])
    monkeypatch.setattr("modules.forex_executor.legacy_entries_enabled",
                        lambda: False)
    monkeypatch.setattr("modules.crt_detector.scan_symbol_refined",
                        lambda s: {"trend_direction": "BULLISH", "direction": "BUY",
                                   "target": 1.11})
    monkeypatch.setattr("modules.crt_detector.validate_with_kronos",
                        lambda *a, **k: True)
    stored = []
    monkeypatch.setattr("modules.crt_detector.store_crt_level",
                        lambda s: stored.append(s))
    monkeypatch.setattr("modules.kronos_engine.get_cached_bias", lambda s: {})
    monkeypatch.setattr("modules.market_data_forex.get_session",
                        lambda: type("S", (), {"rate_limit_remaining": lambda self: 0})())

    main._forex_active_setups = {}
    main.run_crt_scan()

    assert stored, "the CRT levels were not refreshed for the dashboard"
    assert main._forex_active_setups == {}, \
        "the legacy scan armed a setup while entries are locked"


def test_only_the_silver_bullet_entry_job_passes_the_silver_bullet_strategy():
    """
    Static check over the source: every `place_forex_order` call site must name
    its strategy, and only the Silver Bullet one may name SILVER_BULLET.
    """
    import ast

    src = open("main.py", encoding="utf-8").read()
    tree = ast.parse(src)

    calls = []
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef):
            for sub in ast.walk(node):
                if (isinstance(sub, ast.Call)
                        and getattr(sub.func, "id", None) == "place_forex_order"):
                    kwargs = {k.arg: k.value for k in sub.keywords}
                    calls.append((node.name, kwargs))

    assert calls, "no place_forex_order call sites found — has it been renamed?"
    for func_name, kwargs in calls:
        assert "strategy" in kwargs, \
            f"{func_name}() calls place_forex_order without naming its strategy"
        if func_name == "run_silver_bullet_entry_check":
            assert getattr(kwargs["strategy"], "id", None) == "STRATEGY_SILVER_BULLET"


def test_the_legacy_entry_job_is_no_longer_registered(monkeypatch):
    """
    Phase 5.5 retired it. It used to stay registered to supply dashboard data;
    the dashboard is now fed from the Silver Bullet volume profile, so keeping a
    legacy scanner alive for a UI card is exactly what this phase removes.
    """
    import main
    ids = {j.id for j in main.scheduler.get_jobs()}
    assert not any("forex_entry" in i for i in ids)
    assert not any("crt_scan" in i for i in ids)


def test_the_dashboard_does_not_depend_on_a_legacy_scanner():
    """
    The CRT card must be served from the Silver Bullet state, not from the
    retired CRT range cache — otherwise retiring the scanner blanks the card.
    """
    import ast

    src = open("routers/forex.py", encoding="utf-8").read()
    tree = ast.parse(src)
    offenders = []
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef):
            body = "\n".join(
                ast.unparse(n) for n in node.body
                if not (isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant)
                        and isinstance(n.value.value, str)))
            if "get_cached_levels" in body:
                offenders.append(node.name)
    assert offenders == [], f"endpoints still read the CRT cache: {offenders}"


def test_open_position_monitoring_still_works_while_entries_are_locked(
        broker, make_trade, monkeypatch):
    """
    Disabling new legacy entries must not stop existing positions being managed.
    The monitor runs the same five rules regardless of the entry lock.
    """
    tid = make_trade(deal_id="m1", tp1=1.1050, tp2=1.1100, tp3=1.1150,
                     session_expires_at=None,
                     created_at=datetime(2026, 10, 15, 20, 0))

    # The monitor reconciles against the broker's open book, so the position
    # must be listed there or it is skipped as "not live".
    broker["positions"] = [_pos("m1", 55.0)]
    broker["close_results"]["m1"] = {"success": True, "pnl": 55.0, "remaining": 5000.0}

    monkeypatch.setattr(mdf, "get_current_price", lambda s: 1.1200)
    monkeypatch.setattr(mdf, "amend_position",
                        lambda deal_id, sl=None, tp=None: {"success": True, "stop_loss": sl})
    monkeypatch.setattr("modules.candle_provider.get_candles",
                        lambda *a, **k: None)   # no ATR: trailing declines

    stats = pm.manage_open_positions(now=datetime(2026, 10, 15, 20, 5))

    assert stats["checked"] == 1, "the open position was not monitored"
    # Price is past TP1, so the partial fires even with the entry lock engaged.
    assert stats["partials"] == 1
    assert _reload(tid).tp1_done is True


# ══════════════════════════════════════════════════════════════════════════════
#  API CONSISTENCY
# ══════════════════════════════════════════════════════════════════════════════

def test_the_api_reports_whether_legacy_entries_are_enabled():
    from routers.forex import _legacy_entries_enabled
    assert _legacy_entries_enabled() is False


def test_the_pair_endpoint_does_not_read_the_legacy_entry_queue():
    """
    The card must be fed from the levels store. Reading the legacy entry queue
    (now empty by design) would leave it permanently blank.
    """
    import ast

    src = open("routers/forex.py", encoding="utf-8").read()
    fn = next(n for n in ast.walk(ast.parse(src))
              if isinstance(n, ast.FunctionDef) and n.name == "forex_pair_detail")
    body = "\n".join(ast.unparse(n) for n in fn.body
                     if not (isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant)
                             and isinstance(n.value.value, str)))
    assert "_forex_active_setups" not in body, \
        "the pair endpoint reads the legacy entry queue again"


def test_the_status_endpoint_still_exposes_the_legacy_keys():
    """Existing consumers must not break on a missing key."""
    import main
    src = open("main.py", encoding="utf-8").read()
    assert '"forex_active_setups"' in src
