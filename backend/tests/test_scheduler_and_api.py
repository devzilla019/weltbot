"""
backend/tests/test_scheduler_and_api.py
Phase 5 — the UTC schedule, the end-of-day policy, the daily report, and the
forex API contract.

The scheduler is inspected through the live APScheduler instance, so a
registration that is missing, duplicated or on the wrong trigger fails here
rather than in production.
"""
from datetime import datetime, timedelta

import pytest


UTC = "UTC"


# ══════════════════════════════════════════════════════════════════════════════
#  THE UTC SCHEDULE
# ══════════════════════════════════════════════════════════════════════════════

@pytest.fixture(scope="module")
def jobs():
    """The registered APScheduler jobs, keyed by id."""
    import main
    return {j.id: j for j in main.scheduler.get_jobs()}


def _cron_field(job, name):
    """
    One field of a CronTrigger, as a string.

    Returns None for a non-cron trigger, so a scan across all jobs does not blow
    up on the interval jobs.
    """
    fields = getattr(job.trigger, "fields", None)
    if fields is None:
        return None
    for f in fields:
        if f.name == name:
            return str(f)
    return None


def test_no_duplicate_job_ids(jobs):
    """
    A duplicate id would mean two registrations of the same job, which is how a
    scanner ends up running twice per tick.
    """
    import main
    all_ids = [j.id for j in main.scheduler.get_jobs()]
    assert len(all_ids) == len(set(all_ids)), f"duplicate job ids: {all_ids}"


def test_the_daily_bias_job_runs_at_0700_utc(jobs):
    job = jobs["silver_daily_bias"]
    assert _cron_field(job, "hour") == "7"
    assert _cron_field(job, "minute") == "0"
    assert str(job.trigger.timezone) == UTC


def test_the_three_presession_jobs_run_five_minutes_before_each_window(jobs):
    expected = {
        "silver_presession_0755": ("7", "55"),
        "silver_presession_1455": ("14", "55"),
        "silver_presession_1855": ("18", "55"),
    }
    for job_id, (hour, minute) in expected.items():
        assert job_id in jobs, f"{job_id} is not registered"
        assert _cron_field(jobs[job_id], "hour") == hour
        assert _cron_field(jobs[job_id], "minute") == minute


@pytest.mark.parametrize("session,open_hour", [
    ("LONDON", "8"),
    ("NY_MORNING", "15"),
    ("NY_AFTERNOON", "19"),
])
def test_each_session_has_its_own_scanner_on_the_right_hour(jobs, session, open_hour):
    """
    Three separate scanners, each bound to its own window. A single interval job
    that asks "which session is open?" makes the window a property of the data
    rather than of the schedule, so a misfire can scan the wrong one.
    """
    job_id = f"silver_scan_{session}"
    assert job_id in jobs, f"{session} has no scanner"
    job = jobs[job_id]
    assert _cron_field(job, "hour") == open_hour
    assert _cron_field(job, "minute") == "*/5"
    # The session name is bound at registration time, not looked up at run time.
    assert session in job.args


def test_all_three_sessions_have_scanners(jobs):
    """The NY-afternoon scanner in particular must exist, not just London."""
    for session in ("LONDON", "NY_MORNING", "NY_AFTERNOON"):
        assert f"silver_scan_{session}" in jobs


def test_the_position_monitor_runs_every_two_minutes(jobs):
    job = jobs["forex_position_monitor"]
    assert "interval" in str(job.trigger)
    assert job.trigger.interval == timedelta(minutes=2)


def test_the_end_of_day_job_runs_at_2030_utc(jobs):
    from modules.forex_position_manager import EOD_HOUR, EOD_MINUTE

    job = jobs["forex_end_of_day"]
    assert _cron_field(job, "hour") == str(EOD_HOUR)
    assert _cron_field(job, "minute") == str(EOD_MINUTE)
    assert (EOD_HOUR, EOD_MINUTE) == (20, 30)


def test_the_daily_report_runs_at_2300_utc(jobs):
    job = jobs["forex_daily_report"]
    assert _cron_field(job, "hour") == "23"
    assert _cron_field(job, "minute") == "0"


def test_the_daily_cache_reset_runs_inside_the_silver_bullet_cycle(jobs, monkeypatch):
    """
    The 00:01 reset is no longer a cron job. Phase 5.5 retired the CRT job that
    carried it, and the reset now happens inside the Silver Bullet cycle via
    `ensure_current_day`, which detects the rollover on every tick — so it still
    runs at 00:01, and it also survives a process that slept through that minute.
    """
    import main
    import modules.silver_bullet as sb

    monkeypatch.setattr("config.FOREX_ENABLED", True)
    called = []
    monkeypatch.setattr(sb, "ensure_current_day",
                        lambda *a, **k: called.append(1) or False)
    # Keep the cycle from scanning: no window is open in the test's clock.
    monkeypatch.setattr(sb, "sessions_opening_within", lambda *a, **k: [])
    monkeypatch.setattr(sb, "expire_setups", lambda *a, **k: 0)
    monkeypatch.setattr(sb, "current_session", lambda *a, **k: None)

    main.run_silver_bullet_cycle()

    assert called, "the cycle no longer checks for the UTC day rollover"
    assert "silver_cycle" in jobs


def test_every_scheduled_function_exists():
    """
    A typo in a function name registers a job that fails at fire time, not at
    import time. Every job's callable must be importable and callable.
    """
    import main
    for job in main.scheduler.get_jobs():
        assert callable(job.func), f"{job.id} is not callable"
        if isinstance(job.func, str):
            assert hasattr(main, job.func), f"{job.id} points at missing {job.func}"


def test_jobs_cannot_overlap(jobs):
    """max_instances=1 everywhere, so a slow run is not stacked on itself."""
    import main
    for job in main.scheduler.get_jobs():
        assert job.max_instances == 1, f"{job.id} allows overlapping runs"


def test_the_scan_body_is_gated_on_the_live_session(monkeypatch):
    """
    The scanners must not rely on cron alone. `run_silver_bullet_scanner` asks
    the engine which window is open and refuses if it is not its own.

    FOREX_ENABLED is forced on, because the job returns immediately when the
    strategy is switched off ? which would make these tests pass for the wrong
    reason (nothing runs at all) rather than because the guard held.
    """
    import main
    import modules.silver_bullet as sb

    monkeypatch.setattr("config.FOREX_ENABLED", True)
    called = []
    monkeypatch.setattr(main, "_silver_bullet_scan_once",
                        lambda s, n: called.append(s))
    # No window open.
    monkeypatch.setattr(sb, "current_session", lambda *a, **k: None)

    main.run_silver_bullet_scanner("LONDON")
    assert called == [], "a scanner ran outside its window"


def test_a_scanner_refuses_another_sessions_window(monkeypatch):
    """The London job must not trade the New York window even if it misfires."""
    import main
    import modules.silver_bullet as sb

    monkeypatch.setattr("config.FOREX_ENABLED", True)
    called = []
    monkeypatch.setattr(main, "_silver_bullet_scan_once",
                        lambda s, n: called.append(s))
    monkeypatch.setattr(sb, "current_session", lambda *a, **k: "NY_MORNING")

    main.run_silver_bullet_scanner("LONDON")
    assert called == []


def test_the_scan_body_runs_inside_its_own_window(monkeypatch):
    """
    Inside its own window the scanner must reach the scan body.

    `modules.silver_bullet.current_session` is the binding the job imports at
    call time, so it is the one to patch.
    """
    import main
    import modules.silver_bullet as sb

    monkeypatch.setattr("config.FOREX_ENABLED", True)
    called = []
    monkeypatch.setattr(main, "_silver_bullet_scan_once",
                        lambda s, n: called.append(s))
    monkeypatch.setattr(sb, "current_session", lambda *a, **k: "LONDON")

    main.run_silver_bullet_scanner("LONDON")
    assert called == ["LONDON"]


def test_a_disabled_strategy_scans_nothing(monkeypatch):
    """FOREX_ENABLED=false must stop every scanner, not just the entry path."""
    import main
    import modules.silver_bullet as sb

    monkeypatch.setattr("config.FOREX_ENABLED", False)
    called = []
    monkeypatch.setattr(main, "_silver_bullet_scan_once",
                        lambda s, n: called.append(s))
    monkeypatch.setattr(sb, "current_session", lambda *a, **k: "LONDON")

    main.run_silver_bullet_scanner("LONDON")
    assert called == []


def test_the_generic_cycle_does_not_scan_between_windows(monkeypatch):
    """
    The catch-all tick must still refuse to scan outside a window, because it is
    the one job that is not cron-bound.
    """
    import main
    from modules import silver_bullet as sb

    monkeypatch.setattr("config.FOREX_ENABLED", True)
    called = []
    monkeypatch.setattr(main, "_silver_bullet_scan_once",
                        lambda s, n: called.append(s))
    monkeypatch.setattr(sb, "ensure_current_day", lambda *a, **k: False)
    monkeypatch.setattr(sb, "sessions_opening_within", lambda *a, **k: [])
    monkeypatch.setattr(sb, "expire_setups", lambda *a, **k: 0)
    monkeypatch.setattr(sb, "current_session", lambda *a, **k: None)

    main.run_silver_bullet_cycle()
    assert called == []



#  END-OF-DAY POLICY
# ══════════════════════════════════════════════════════════════════════════════

def test_the_eod_cutoff_is_the_documented_hour():
    from modules.forex_position_manager import EOD_NO_NEW_ENTRIES_HOUR
    assert EOD_NO_NEW_ENTRIES_HOUR == 20


def test_the_eod_policy_cancels_pending_setups(monkeypatch):
    """
    A setup is a plan to enter. A plan whose window has closed cannot be filled,
    so dropping it is free.
    """
    from modules import forex_position_manager as pm
    from modules import market_data_forex as mdf
    from modules import silver_bullet as sb

    # No open positions: this test is only about the setup cancellation.
    monkeypatch.setattr(mdf, "clear_caches", lambda: None)
    monkeypatch.setattr(mdf, "get_open_positions", lambda: [])

    sb.reset_daily_cache("test")
    sb._active_setups["EURUSD"] = {"symbol": "EURUSD", "session": "NY_AFTERNOON"}
    sb._active_setups["GBPUSD"] = {"symbol": "GBPUSD", "session": "NY_AFTERNOON"}

    result = pm.end_of_day_policy(now=datetime(2026, 10, 15, 20, 30))
    assert result["cancelled_setups"] == 2
    assert sb.get_active_setups() == {}
    sb.reset_daily_cache("test")


def test_the_eod_policy_holds_a_losing_position(monkeypatch):
    """
    The rule was specified for PROFITABLE positions. A losing position has its
    stop still doing its job, so closing it early would turn a bounded risk into
    a realised loss for no strategic reason.
    """
    from modules import forex_position_manager as pm
    from modules import market_data_forex as mdf
    from models import ForexTrade

    db = pm.SessionLocal()
    trade = ForexTrade(
        symbol="USDJPY", signal="BUY", confidence=91.0,
        entry_price=150.00, stop_loss=149.50, take_profit=151.50,
        lots=10000.0, original_lots=10000.0,
        metaapi_position_id="eod-loss-1", outcome="OPEN",
    )
    db.add(trade)
    db.commit()
    tid = trade.id
    db.close()

    closed = []
    try:
        monkeypatch.setattr(mdf, "clear_caches", lambda: None)
        monkeypatch.setattr(mdf, "get_open_positions",
                            lambda: [{"id": "eod-loss-1", "symbol": "USDJPY",
                                      "unrealized_pnl": -42.0}])
        monkeypatch.setattr(mdf, "close_position",
                            lambda *a, **k: closed.append(a) or {"success": True})

        result = pm.end_of_day_policy(now=datetime(2026, 10, 15, 20, 30))

        assert result["closed_positions"] == 0
        assert closed == [], "the EOD policy closed a losing position"
        assert result["held_positions"] == 1
        assert "losing" in result["held"][0]["reason"]

        db = pm.SessionLocal()
        t = db.query(ForexTrade).filter(ForexTrade.id == tid).first()
        assert t.outcome == "OPEN", "the losing position was settled"
        db.close()
    finally:
        db = pm.SessionLocal()
        db.query(ForexTrade).filter(ForexTrade.id == tid).delete()
        db.commit()
        db.close()


def test_the_eod_policy_closes_positions_when_explicitly_asked(monkeypatch):
    """
    The explicit close-all switch exists for an operator decision (retiring an
    account, say). It is deliberately not what the scheduler uses.
    """
    from modules import forex_position_manager as pm
    from modules import market_data_forex as mdf
    from models import ForexTrade

    db = pm.SessionLocal()
    trade = ForexTrade(
        symbol="EURUSD", signal="BUY", confidence=93.0,
        entry_price=1.1000, stop_loss=1.0950, take_profit=1.1150,
        lots=10000.0, original_lots=10000.0,
        metaapi_position_id="eod-deal-1", outcome="OPEN",
    )
    db.add(trade)
    db.commit()
    tid = trade.id
    db.close()

    try:
        monkeypatch.setattr(mdf, "clear_caches", lambda: None)
        monkeypatch.setattr(mdf, "get_open_positions",
                            lambda: [{"id": "eod-deal-1", "symbol": "EURUSD",
                                      "unrealized_pnl": 12.5}])
        monkeypatch.setattr(mdf, "close_position",
                            lambda deal_id: {"success": True, "pnl": 12.5})

        result = pm.end_of_day_policy(now=datetime(2026, 10, 15, 20, 30),
                                      close_open=True)
        assert result["closed_positions"] == 1
        assert result["pnl"] == pytest.approx(12.5)
        assert result["mode"] == "close_all"

        db = pm.SessionLocal()
        t = db.query(ForexTrade).filter(ForexTrade.id == tid).first()
        assert t.outcome == "WIN"
        assert "end-of-day" in (t.close_reason or "")
        db.close()
    finally:
        db = pm.SessionLocal()
        db.query(ForexTrade).filter(ForexTrade.id == tid).delete()
        db.commit()
        db.close()


def test_the_eod_policy_closes_an_eligible_profitable_position(monkeypatch):
    """
    The core requirement: a profitable position is closed at 20:30, its P&L is
    taken from the broker's own unrealised figure, and the outcome is recorded.
    """
    from modules import forex_position_manager as pm
    from modules import market_data_forex as mdf
    from models import ForexTrade

    db = pm.SessionLocal()
    trade = ForexTrade(
        symbol="GBPUSD", signal="SELL", confidence=95.0,
        entry_price=1.2500, stop_loss=1.2550, take_profit=1.2400,
        lots=10000.0, original_lots=10000.0,
        metaapi_position_id="eod-profit-1", outcome="OPEN",
    )
    db.add(trade)
    db.commit()
    tid = trade.id
    db.close()

    closed_with = []
    try:
        monkeypatch.setattr(mdf, "clear_caches", lambda: None)
        monkeypatch.setattr(mdf, "get_open_positions",
                            lambda: [{"id": "eod-profit-1", "symbol": "GBPUSD",
                                      "unrealized_pnl": 88.25}])

        def fake_close(deal_id):
            closed_with.append(deal_id)
            return {"success": True, "pnl": 87.9}

        monkeypatch.setattr(mdf, "close_position", fake_close)

        result = pm.end_of_day_policy(now=datetime(2026, 10, 15, 20, 30))

        assert result["eligible"] == 1
        assert result["closed_positions"] == 1
        assert closed_with == ["eod-profit-1"]
        # The recorded P&L is the broker's realised figure, not the UPL estimate.
        assert result["pnl"] == pytest.approx(87.9)
        assert result["closed"][0]["upl_at_decision"] == pytest.approx(88.25)

        db = pm.SessionLocal()
        t = db.query(ForexTrade).filter(ForexTrade.id == tid).first()
        assert t.outcome == "WIN"
        assert t.pnl == pytest.approx(87.9)
        assert "profitable" in (t.close_reason or "")
        db.close()
    finally:
        db = pm.SessionLocal()
        db.query(ForexTrade).filter(ForexTrade.id == tid).delete()
        db.commit()
        db.close()


def test_the_eod_policy_never_raises(monkeypatch):
    from modules import forex_position_manager as pm
    import modules.silver_bullet as sb

    monkeypatch.setattr(sb, "get_active_setups",
                        lambda: (_ for _ in ()).throw(RuntimeError("boom")))
    result = pm.end_of_day_policy(now=datetime(2026, 10, 15, 20, 30))
    assert isinstance(result, dict)
    assert result["errors"] >= 1


# ══════════════════════════════════════════════════════════════════════════════
#  DAILY REPORT
# ══════════════════════════════════════════════════════════════════════════════

def test_an_empty_day_reports_zeros_not_an_error():
    """
    "No trades" is a valid and common outcome of a strategy whose main filter is
    NEUTRAL, so it must not be reported as a failure.
    """
    from modules.forex_position_manager import build_daily_report

    report = build_daily_report(datetime(2020, 1, 1, 23, 0))
    assert report["opened"] == 0
    assert report["closed"] == 0
    assert report["realised_pnl"] == 0.0
    assert report["win_rate"] is None
    assert "error" not in report


def test_the_report_summarises_a_closed_trade(monkeypatch):
    from modules import forex_position_manager as pm
    from models import ForexTrade

    day = datetime(2026, 3, 10, 23, 0)
    db = pm.SessionLocal()
    trade = ForexTrade(
        symbol="EURUSD", signal="BUY", confidence=93.0,
        entry_price=1.1000, stop_loss=1.0950, take_profit=1.1150,
        lots=10000.0, original_lots=10000.0,
        session_name="LONDON", entry_type="SILVER_BULLET_FVG",
        outcome="WIN", pnl=125.5,
        created_at=day.replace(hour=9), closed_at=day.replace(hour=10),
    )
    db.add(trade)
    db.commit()
    tid = trade.id
    db.close()

    try:
        report = pm.build_daily_report(day)
        assert report["opened"] == 1
        assert report["closed"] == 1
        assert report["wins"] == 1
        assert report["realised_pnl"] == pytest.approx(125.5)
        assert report["win_rate"] == 100.0
        assert report["by_symbol"]["EURUSD"]["trades"] == 1
        assert report["by_session"]["LONDON"]["pnl"] == pytest.approx(125.5)
        assert report["by_entry_type"]["SILVER_BULLET_FVG"]["wins"] == 1
        assert report["best"]["pnl"] == pytest.approx(125.5)
    finally:
        db = pm.SessionLocal()
        db.query(ForexTrade).filter(ForexTrade.id == tid).delete()
        db.commit()
        db.close()


def test_unrealised_pnl_is_kept_separate_from_the_days_result(monkeypatch):
    """
    Folding open P&L into the day's result would make the number depend on when
    it was read.
    """
    from modules import forex_position_manager as pm
    from models import ForexTrade

    day = datetime(2026, 3, 11, 23, 0)
    db = pm.SessionLocal()
    trade = ForexTrade(
        symbol="GBPUSD", signal="SELL", confidence=90.0,
        entry_price=1.2500, stop_loss=1.2550, take_profit=1.2400,
        lots=10000.0, original_lots=10000.0,
        outcome="OPEN", pnl=40.0, created_at=day.replace(hour=15),
    )
    db.add(trade)
    db.commit()
    tid = trade.id
    db.close()

    try:
        report = pm.build_daily_report(day)
        assert report["realised_pnl"] == 0.0
        assert report["open_positions"] == 1
        assert report["unrealised_pnl"] == pytest.approx(40.0)
    finally:
        db = pm.SessionLocal()
        db.query(ForexTrade).filter(ForexTrade.id == tid).delete()
        db.commit()
        db.close()


def test_the_report_job_logs_without_raising(monkeypatch, capsys):
    import main
    main.run_daily_report()
    # FOREX_ENABLED may be false, in which case the job is a no-op; either way it
    # must not raise.
    assert True


# ══════════════════════════════════════════════════════════════════════════════
#  API CONTRACT
# ══════════════════════════════════════════════════════════════════════════════

def test_the_router_session_helper_matches_the_engine():
    """
    The router used to hold a SECOND session definition ('NY' / 'LONDON' /
    'ASIA') that disagreed with the windows the scanner enforces. A dashboard
    that contradicts the scanner is worse than no dashboard.
    """
    from routers import forex as fr
    from modules.forex_signal_engine import current_session

    assert fr._current_session() == (current_session() or "CLOSED")


def test_the_router_has_no_hardcoded_session_hours():
    """
    Guard against the old definition creeping back in.

    Checked against the parsed source, not the raw text: the docstring above
    `_current_session` quotes the old rule to explain why it was removed, and a
    raw substring match would flag that explanation as a violation.
    """
    import ast

    src = open("routers/forex.py", encoding="utf-8").read()
    tree = ast.parse(src)

    # Only the EXECUTABLE body of _current_session matters. The docstring is
    # excluded because it quotes the old rule to explain why it was removed, and
    # a raw text match would flag that explanation as a violation.
    import ast

    src = open("routers/forex.py", encoding="utf-8").read()
    tree = ast.parse(src)

    fn = next((n for n in ast.walk(tree)
               if isinstance(n, ast.FunctionDef) and n.name == "_current_session"),
              None)
    assert fn is not None, "_current_session is missing"

    code = [n for n in fn.body
            if not (isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant)
                    and isinstance(n.value.value, str))]
    body_src = "\n".join(ast.unparse(n) for n in code)

    assert "ASIA" not in body_src, "the old ASIA label is back"
    assert "hour" not in body_src, "the old hour-range rule is back"
    # It must delegate rather than decide.
    assert "current_session" in body_src


def test_the_status_endpoint_exposes_the_silver_bullet_state():
    from routers import forex as fr
    src = open("routers/forex.py", encoding="utf-8").read()
    assert "'silver_bullet'" in src
    assert "def forex_silver_bullet" in src


def test_the_silver_bullet_state_has_the_documented_keys():
    from routers.forex import _silver_bullet_state

    state = _silver_bullet_state()
    for key in ("date", "active_session", "time_remaining_seconds", "sessions",
                "min_confidence", "biases", "pending_setups", "pending_count"):
        assert key in state, f"state is missing {key}"


def test_the_state_reports_every_session_window():
    from routers.forex import _silver_bullet_state

    state = _silver_bullet_state()
    assert set(state["sessions"]) == {"LONDON", "NY_MORNING", "NY_AFTERNOON"}
    for name, window in state["sessions"].items():
        assert window["open_utc"] and window["close_utc"]
        assert isinstance(window["is_open"], bool)


def test_the_state_exposes_vp_levels_per_symbol(monkeypatch):
    """
    The dashboard needs POC/VAH/VAL per pair. They must come from the stored
    bias record, not be recomputed.
    """
    from routers.forex import _silver_bullet_state
    from modules import silver_bullet as sb

    sb.reset_daily_cache("test")
    sb._daily_bias["EURUSD"] = {
        "symbol": "EURUSD", "h4_bias": "BULLISH", "strength": 3,
        "price_position": "ABOVE_VALUE", "vp_bias": "STRONG_BUY",
        "session_date": sb.utc_date_key(),
        "vp_levels": {"poc": 1.1050, "vah": 1.1100, "val": 1.1000,
                      "volume_source": "exchange", "source_trusted": True,
                      "valid": True, "warning": None},
        "vp_gateable": True, "vp_gate_reason": "ok",
    }

    state = _silver_bullet_state()
    row = state["biases"]["EURUSD"]
    assert row["h4_bias"] == "BULLISH"
    assert row["vp_levels"]["poc"] == 1.1050
    assert row["vp_levels"]["vah"] == 1.1100
    assert row["vp_levels"]["val"] == 1.1000
    assert row["vp_levels"]["source_trusted"] is True
    sb.reset_daily_cache("test")


def test_the_state_exposes_pending_setups(monkeypatch):
    from routers.forex import _silver_bullet_state
    from modules import silver_bullet as sb
    from modules.forex_signal_engine import STATE_FVG_FOUND

    sb.reset_daily_cache("test")
    sb._active_setups["EURUSD"] = {
        "symbol": "EURUSD", "state": STATE_FVG_FOUND, "direction": "BUY",
        "session": "LONDON", "confidence": 93, "executable": True,
        "fvg": {"fvg_low": 1.1080, "fvg_high": 1.1088},
        "sweep": {"sweep_wick": 1.0990},
        "vp_confluence": "POC_OVERLAP", "vp_source": "exchange",
        "expires_at": "2026-10-15T09:00:00",
    }

    state = _silver_bullet_state()
    assert state["pending_count"] == 1
    row = state["pending_setups"][0]
    assert row["symbol"] == "EURUSD"
    assert row["state"] == STATE_FVG_FOUND
    assert row["confidence"] == 93
    assert row["fvg_low"] == 1.1080
    assert row["vp_confluence"] == "POC_OVERLAP"
    sb.reset_daily_cache("test")


def test_pending_setups_are_ranked_by_score(monkeypatch):
    from routers.forex import _silver_bullet_state
    from modules import silver_bullet as sb

    sb.reset_daily_cache("test")
    for symbol, conf in (("EURUSD", 89), ("GBPUSD", 96), ("USDJPY", 92)):
        sb._active_setups[symbol] = {"symbol": symbol, "confidence": conf,
                                     "session": "LONDON"}

    state = _silver_bullet_state()
    scores = [s["confidence"] for s in state["pending_setups"]]
    assert scores == sorted(scores, reverse=True)
    sb.reset_daily_cache("test")


def test_the_state_degrades_gracefully_when_a_module_fails(monkeypatch):
    """The status endpoint must not 500 because one sub-read failed."""
    from routers import forex as fr
    import modules.silver_bullet as sb

    monkeypatch.setattr(sb, "get_all_daily_bias",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("db down")))
    state = fr._silver_bullet_state()
    assert "error" in state
    assert state["pending_setups"] == []


def test_the_schedule_endpoint_describes_the_real_schedule():
    from routers.forex import forex_schedule

    schedule = forex_schedule()
    assert schedule["timezone"] == "UTC"
    times = {j["time"] for j in schedule["jobs"]}
    for expected in ("00:01", "07:00", "07:55", "14:55", "18:55", "20:30", "23:00"):
        assert expected in times, f"{expected} missing from the advertised schedule"
    assert "08:00-09:00" in times
    assert "15:00-16:00" in times
    assert "19:00-20:00" in times
    assert schedule["no_new_entries_after_hour"] == 20


def test_the_schedule_endpoint_reports_the_session_times():
    from routers.forex import forex_schedule

    schedule = forex_schedule()
    assert set(schedule["sessions"]) == {"LONDON", "NY_MORNING", "NY_AFTERNOON"}
    london = schedule["sessions"]["LONDON"]
    assert london["open_utc"] == "08:00"
    assert london["close_utc"] == "09:00"


def test_the_new_endpoints_are_registered():
    from routers import forex as fr
    paths = {r.path for r in fr.router.routes}
    for path in ("/api/forex/silver-bullet", "/api/forex/silver-bullet/setups",
                 "/api/forex/schedule", "/api/forex/daily-report"):
        assert path in paths, f"{path} is not registered"


def test_existing_endpoints_are_preserved():
    """Nothing unrelated to this strategy may be removed from the API."""
    from routers import forex as fr
    paths = {r.path for r in fr.router.routes}
    for path in ("/api/forex/status", "/api/forex/signals", "/api/forex/positions",
                 "/api/forex/trades", "/api/forex/balance", "/api/forex/daily-risk",
                 "/api/forex/test-connection", "/api/forex/kronos-status",
                 "/api/forex/cascade-stats", "/api/forex/pair/{symbol}",
                 "/api/forex/close-all", "/api/forex/trades/clear"):
        assert path in paths, f"{path} was removed"


def test_the_positions_endpoint_adds_context_without_replacing_keys(monkeypatch):
    """
    The added keys must be additive, so an existing consumer is unaffected.
    """
    from routers import forex as fr
    import modules.forex_position_manager as pm

    monkeypatch.setattr(pm, "get_forex_position_summary",
                        lambda: {"open_count": 1, "win_rate": 50.0})
    monkeypatch.setattr(pm, "daily_halt_active", lambda: (False, "OK"))

    result = fr.forex_positions()
    assert result["open_count"] == 1
    assert result["win_rate"] == 50.0
    assert "active_session" in result
    assert "pending_setups" in result
    assert result["daily_halt"] is False


# ══════════════════════════════════════════════════════════════════════════════
#  MIGRATION
# ══════════════════════════════════════════════════════════════════════════════

def test_the_migration_covers_every_new_trade_column():
    """
    Adding an ORM column does NOT update an existing database. The light
    migration is what makes a deployed instance gain the column.
    """
    src = open("database.py", encoding="utf-8").read()
    block = src.split('"forex_trades": [', 1)[1].split("],", 1)[0]
    for col in ("tp3", "original_lots", "initial_stop", "initial_risk",
                "tp1_done", "tp2_done", "tp3_done", "breakeven_done",
                "trailing_active", "peak_price", "session_name",
                "session_expires_at", "management_state", "close_reason",
                "vp_confluence", "partial_close_pct"):
        assert f'"{col}"' in block, f"migration is missing forex_trades.{col}"


def test_the_migration_is_idempotent():
    """It runs on every startup, so a second run must be a no-op."""
    import database
    database.run_light_migrations()
    database.run_light_migrations()   # must not raise


def test_the_new_columns_exist_on_the_model():
    from models import ForexTrade
    for field in ("vp_confluence", "partial_close_pct"):
        assert hasattr(ForexTrade, field), f"ForexTrade is missing {field}"


def test_the_new_columns_exist_in_the_live_database():
    """The migrated database must actually accept the columns."""
    from sqlalchemy import inspect
    import database

    cols = {c["name"] for c in inspect(database.engine).get_columns("forex_trades")}
    assert "vp_confluence" in cols
    assert "partial_close_pct" in cols
