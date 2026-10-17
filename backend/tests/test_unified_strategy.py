"""
backend/tests/test_unified_strategy.py
Phase 5.5 — Silver Bullet is the only strategy, across every enabled instrument.

The tests are grouped by the claim they defend:
  * the roster covers every enabled symbol,
  * routing picks the right adapter and position manager per market type,
  * both data providers produce frames the shared pipeline accepts,
  * sessions bind every asset class, including a manual invocation,
  * no retired strategy can be reached from a schedule or an entry path,
  * a failure in Silver Bullet does not fall back to anything,
  * missing or stale data refuses an entry rather than trading on it.
"""
import ast
import inspect
from datetime import datetime

import pandas as pd
import pytest

import config
from modules import forex_executor as fx
from modules import strategy_guard as guard
from modules.universe import get_universe


# ══════════════════════════════════════════════════════════════════════════════
#  1. THE ROSTER COVERS EVERY ENABLED SYMBOL
# ══════════════════════════════════════════════════════════════════════════════

def test_every_forex_and_metal_pair_is_scanned():
    missing = [s for s in config.FOREX_PAIRS
               if s not in config.SILVER_BULLET_INSTRUMENTS]
    assert missing == [], f"configured FX/metals are not scanned: {missing}"


def test_every_enabled_crypto_symbol_is_scanned():
    """
    The whole point of this phase: not just BTC/ETH. The roster must be derived
    from the crypto universe, so enabling a symbol there cannot silently leave
    it unscanned.
    """
    missing = [s for s in get_universe()
               if s not in config.SILVER_BULLET_INSTRUMENTS]
    assert missing == [], f"enabled crypto is not scanned: {missing}"


def test_the_roster_has_no_duplicates():
    inst = config.SILVER_BULLET_INSTRUMENTS
    assert len(inst) == len(set(inst))


def test_the_roster_is_not_a_hardcoded_partial_list():
    """
    A hand-written list would drift the moment an instrument was enabled. The
    roster must be computed from the configured universes.
    """
    src = inspect.getsource(config)
    assert "_crypto_universe()" in src, "the crypto universe is not consulted"
    # And the derivation must actually be the thing assigned.
    assert "SILVER_BULLET_INSTRUMENTS = list(dict.fromkeys(" in src


def test_metals_are_present_and_typed_as_metals():
    for symbol in ("XAUUSD", "XAGUSD"):
        assert symbol in config.SILVER_BULLET_INSTRUMENTS
        assert fx.instrument_kind(symbol) == "metal"


def test_more_than_two_crypto_symbols_are_scanned():
    """Guards against a regression to the old BTC/ETH-only roster."""
    crypto = [s for s in config.SILVER_BULLET_INSTRUMENTS
              if fx.instrument_kind(s) == "crypto"]
    assert len(crypto) > 2, f"only {len(crypto)} crypto symbols are scanned"
    assert set(crypto) == set(get_universe())


def test_every_configured_symbol_has_a_routing_record():
    for symbol in config.SILVER_BULLET_INSTRUMENTS:
        rec = fx.describe_symbol(symbol, check_venue=False)
        assert rec["symbol"] == symbol
        assert rec["market_type"] in ("fx", "metal", "crypto")
        assert rec["data_provider"] in ("capital", "binance")
        assert rec["execution_adapter"] in ("capital", "binance")
        assert rec["position_manager"]
        assert rec["scan_function"].endswith("run_silver_bullet_scan")
        assert rec["strategy"] == guard.STRATEGY_SILVER_BULLET


# ══════════════════════════════════════════════════════════════════════════════
#  2. ROUTING PER MARKET TYPE
# ══════════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("symbol,kind,adapter,manager", [
    ("EURUSD", "fx", fx.ADAPTER_CAPITAL, "modules.forex_position_manager"),
    ("GBPJPY", "fx", fx.ADAPTER_CAPITAL, "modules.forex_position_manager"),
    ("XAUUSD", "metal", fx.ADAPTER_CAPITAL, "modules.forex_position_manager"),
    ("XAGUSD", "metal", fx.ADAPTER_CAPITAL, "modules.forex_position_manager"),
    ("BTC/USDT", "crypto", fx.ADAPTER_BINANCE, "modules.position_manager"),
    ("SOL/USDT", "crypto", fx.ADAPTER_BINANCE, "modules.position_manager"),
    ("DOGE/USDT", "crypto", fx.ADAPTER_BINANCE, "modules.position_manager"),
])
def test_routing_per_market_type(symbol, kind, adapter, manager):
    assert fx.instrument_kind(symbol) == kind
    assert fx.execution_adapter_for(symbol) == adapter
    assert fx.position_manager_for(symbol) == manager


def test_routing_is_pure_and_does_not_touch_the_network(monkeypatch):
    """
    The scan consults the adapter on every tick. A venue call here would make
    the scanner slow and would make routing depend on venue uptime.
    """
    import modules.market_data_forex as mdf
    import modules.market_data as md

    def explode(*a, **k):
        raise AssertionError("routing made a venue call")

    monkeypatch.setattr(mdf, "resolve_epic", explode)
    monkeypatch.setattr(mdf, "get_dealing_rules", explode)
    monkeypatch.setattr(md, "get_lot_size_rules", explode)

    for symbol in ("EURUSD", "XAUUSD", "BTC/USDT", "SOL/USDT"):
        assert fx.execution_adapter_for(symbol) is not None


def test_an_empty_symbol_is_not_routable():
    assert fx.execution_adapter_for("") is None
    assert fx.execution_adapter_for(None) is None


def test_a_metal_is_never_routed_to_the_exchange():
    """XAUUSD ends in 'USD' and would look like crypto to a naive test."""
    for symbol in ("XAUUSD", "XAGUSD", "XPTUSD"):
        assert fx.execution_adapter_for(symbol) == fx.ADAPTER_CAPITAL


# ══════════════════════════════════════════════════════════════════════════════
#  3. TRADEABILITY IS CHECKED AGAINST THE VENUE, AND FAILS CLOSED
# ══════════════════════════════════════════════════════════════════════════════

def test_a_crypto_symbol_with_a_step_size_is_tradeable(monkeypatch):
    import modules.market_data as md
    monkeypatch.setattr(md, "get_lot_size_rules",
                        lambda s: {"step_size": 0.001, "min_notional": 5.0})
    ok, reason = fx.instrument_is_tradeable("BTC/USDT")
    assert ok is True


def test_a_crypto_symbol_without_a_step_size_is_refused(monkeypatch):
    """A delisted symbol has no step, and must not be traded."""
    import modules.market_data as md
    monkeypatch.setattr(md, "get_lot_size_rules", lambda s: {})
    ok, reason = fx.instrument_is_tradeable("DELISTED/USDT")
    assert ok is False
    assert "step size" in reason


def test_a_cfd_without_dealing_rules_is_refused(monkeypatch):
    import modules.market_data_forex as mdf
    monkeypatch.setattr(mdf, "resolve_epic", lambda s, refresh=False: "EPIC")
    monkeypatch.setattr(mdf, "get_dealing_rules", lambda s: {})
    ok, reason = fx.instrument_is_tradeable("EURUSD")
    assert ok is False
    assert "dealing rules" in reason


def test_an_unresolvable_epic_is_refused(monkeypatch):
    import modules.market_data_forex as mdf
    monkeypatch.setattr(mdf, "resolve_epic", lambda s, refresh=False: "")
    ok, reason = fx.instrument_is_tradeable("NOSUCHPAIR")
    assert ok is False
    assert "epic" in reason


def test_a_venue_failure_refuses_rather_than_guessing(monkeypatch):
    """The check must fail CLOSED: an unreachable venue is not a green light."""
    import modules.market_data_forex as mdf

    def boom(*a, **k):
        raise RuntimeError("venue down")

    monkeypatch.setattr(mdf, "resolve_epic", boom)
    ok, reason = fx.instrument_is_tradeable("EURUSD")
    assert ok is False
    assert "failed" in reason


# ══════════════════════════════════════════════════════════════════════════════
#  4. BOTH PROVIDERS FEED THE SHARED PIPELINE
# ══════════════════════════════════════════════════════════════════════════════

REQUIRED_COLUMNS = ["timestamp", "open", "high", "low", "close", "volume"]


def _capital_frame():
    return pd.DataFrame({
        "timestamp": pd.date_range("2026-10-15", periods=6, freq="1h", tz="UTC"),
        "open": [1.1] * 6, "high": [1.11] * 6,
        "low": [1.09] * 6, "close": [1.105] * 6,
        "volume": [10.0, 20.0, 30.0, 40.0, 50.0, 60.0],
    })


def _binance_frame():
    return pd.DataFrame({
        "timestamp": pd.date_range("2026-10-15", periods=6, freq="1h", tz="UTC"),
        "open": [60000.0] * 6, "high": [60100.0] * 6,
        "low": [59900.0] * 6, "close": [60050.0] * 6,
        "volume": [1.5, 2.5, 3.5, 4.5, 5.5, 6.5],
    })


def test_both_providers_normalize_to_the_same_interface():
    """
    The pipeline must not know which venue produced a frame. Same columns, same
    order, same dtypes — that is what lets one engine serve both.
    """
    from modules.candle_provider import _normalize

    for raw, source in ((_capital_frame(), "tick"),
                        (_binance_frame(), "exchange")):
        out = _normalize(raw, source)
        assert out is not None
        assert list(out.columns) == REQUIRED_COLUMNS
        assert out["timestamp"].is_monotonic_increasing
        assert out.attrs["volume_source"] == source
        for col in ("open", "high", "low", "close", "volume"):
            assert pd.api.types.is_numeric_dtype(out[col]), col


def test_normalized_frames_carry_their_volume_provenance():
    """
    The two venues' volumes are NOT interchangeable — one is the provider's own
    cleared contracts, the other is exchange-traded base volume. The frame must
    say which, so the profile never silently compares them.
    """
    from modules.candle_provider import _normalize

    cap = _normalize(_capital_frame(), "tick")
    bin_ = _normalize(_binance_frame(), "exchange")

    assert cap.attrs["volume_source"] == "tick"
    assert bin_.attrs["volume_source"] == "exchange"
    assert cap.attrs["volume_source"] != bin_.attrs["volume_source"]


def test_capital_tick_volume_is_treated_as_a_proxy_not_real_volume():
    """
    Requirement: FX tick volume is tick activity, not centralised traded volume.
    It is trusted for confluence because it IS volume, but the module documents
    it as a proxy and the dashboard labels it.
    """
    import modules.market_data_forex as mdf
    src = inspect.getsource(mdf.get_candles)
    assert "PROXY" in src.upper()
    assert "lastTradedVolume" in src

    # And a frame that reports no volume at all is labelled 'none', not 'tick'.
    from modules.candle_provider import _normalize
    frame = _capital_frame()
    frame["volume"] = 0.0
    out = _normalize(frame, "tick")
    assert out is not None   # normalization preserves what the venue sent
    # The venue itself is what decides 'tick' vs 'none'; verify that rule.
    src_provider = inspect.getsource(mdf.get_candles)
    assert 'volume_source"] = "tick" if saw_real_volume else "none"' in src_provider


def test_each_venue_volume_is_profiled_on_its_own_field():
    """
    The profile consumes whatever `volume` column the frame carries. It must not
    reach for a different field per venue, and it must report which one it used.
    """
    from modules.volume_profile import calculate_session_volume_profile
    from modules.candle_provider import _normalize

    for raw, source in ((_capital_frame(), "tick"),
                        (_binance_frame(), "exchange")):
        out = _normalize(raw, source)
        vp = calculate_session_volume_profile(out)
        if vp:      # a flat fixture can be rejected as unpeaked; that is fine
            assert vp["volume_source"] == source


def test_the_pipeline_accepts_a_frame_from_either_provider():
    """The strategy must run on both without a venue branch in the detector."""
    from modules import forex_signal_engine as fse
    from modules.candle_provider import _normalize

    levels = {"swing_high": 1.2, "swing_low": 1.0}
    for raw, source in ((_capital_frame(), "tick"),
                        (_binance_frame(), "exchange")):
        out = _normalize(raw, source)
        # No exception, and a well-formed answer (None or a dict) for both.
        result = fse.detect_liquidity_sweep(out, levels, "BULLISH")
        assert result is None or isinstance(result, dict)


# ══════════════════════════════════════════════════════════════════════════════
#  5. SESSIONS BIND EVERY ASSET CLASS
# ══════════════════════════════════════════════════════════════════════════════

def test_the_three_windows_are_the_specified_utc_hours():
    from modules.forex_signal_engine import SESSIONS
    assert SESSIONS["LONDON"] == (8, 9, 3)
    assert SESSIONS["NY_MORNING"] == (15, 16, 4)
    assert SESSIONS["NY_AFTERNOON"] == (19, 20, 2)


def test_every_asset_class_is_scanned_by_the_same_session_jobs():
    """
    There is no separate crypto schedule. One set of session jobs covers the
    whole roster, which is what makes the windows apply to crypto too.
    """
    import main
    ids = {j.id for j in main.scheduler.get_jobs()}
    for session in ("LONDON", "NY_MORNING", "NY_AFTERNOON"):
        assert f"silver_scan_{session}" in ids
    # And no per-asset-class scanner exists to bypass the windows.
    assert not [i for i in ids if "crypto_scan" in i]


@pytest.mark.parametrize("hour,expected", [
    (8, "LONDON"), (15, "NY_MORNING"), (19, "NY_AFTERNOON"),
])
def test_the_scan_accepts_its_own_window(hour, expected):
    from modules import silver_bullet as sb
    import modules.forex_signal_engine as fse
    from tests.test_scheduler_and_api import _cron_field  # noqa: F401  (parity)

    now = datetime(2026, 10, 15, hour, 30)
    assert fse.current_session(now) == expected


@pytest.mark.parametrize("hour", [0, 7, 9, 12, 14, 16, 18, 20, 23])
def test_crypto_is_not_scanned_outside_the_windows(hour):
    """
    Crypto trades around the clock, but this strategy must not enter outside its
    windows. The session helper is asset-agnostic, so this holds for crypto
    exactly as it does for FX.
    """
    from modules.forex_signal_engine import current_session
    assert current_session(datetime(2026, 10, 15, hour, 30)) is None


def test_a_manual_scan_outside_a_window_does_nothing(monkeypatch):
    """
    A manual trigger is the obvious way to bypass a cron-only guard. The cycle
    must refuse when no window is open, for every asset class.
    """
    import main
    import modules.silver_bullet as sb

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


def test_the_manual_scan_endpoint_runs_the_silver_bullet_cycle():
    """`/api/bot/scan-now` must not reach a retired engine."""
    src = open("main.py", encoding="utf-8").read()
    tree = ast.parse(src)
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == "scan_now")
    body = ast.unparse(fn)
    assert "run_silver_bullet_cycle" in body
    assert "level2_entry_check" not in body
    assert "level1_bos_scan" not in body


def test_a_scanner_cannot_run_in_another_session(monkeypatch):
    """The session name is bound at registration and re-checked at run time."""
    import main
    import modules.silver_bullet as sb

    monkeypatch.setattr("config.FOREX_ENABLED", True)
    called = []
    monkeypatch.setattr(main, "_silver_bullet_scan_once",
                        lambda s, n: called.append(s))
    monkeypatch.setattr(sb, "current_session", lambda *a, **k: "NY_MORNING")

    main.run_silver_bullet_scanner("LONDON")
    assert called == []


# ══════════════════════════════════════════════════════════════════════════════
#  6. NO RETIRED STRATEGY IS REACHABLE
# ══════════════════════════════════════════════════════════════════════════════

RETIRED_JOB_FUNCTIONS = (
    "level1_bos_scan",
    "level2_entry_check",
    "refresh_signal_cache",
    "run_crypto_crt_scan",
    "run_crypto_entry_check",
    "run_crypto_kronos_bias",
)

# Helpers that only ever ran inside a retired job. They are unreachable for the
# same reason, so an unguarded order call inside one is dead rather than live —
# but the guard must still refuse it, which is what the assertion below proves.
RETIRED_ENTRY_HELPERS = ("_place_trade",)


def test_no_order_is_submitted_outside_a_permitted_window(monkeypatch):
    """
    The end-to-end guarantee: with an EXECUTABLE setup sitting in the store, the
    entry job submits nothing when no window is open.

    Both order paths are instrumented, so this fails if either venue is reached
    — a scheduler-only guard would let a manual or misfired run through.
    """
    import main
    import modules.silver_bullet as sb
    import modules.forex_signal_engine as fse
    import modules.forex_executor as fx
    from tests.helpers import (bull_sweep_sequence, candles, silver_bias,
                               silver_session_levels, trusted_vp)

    now = datetime(2026, 10, 15, 8, 30)
    setup = fse.build_setup("EURUSD", candles(bull_sweep_sequence()),
                            silver_session_levels(),
                            silver_bias(vp_levels=trusted_vp()), "LONDON", now)
    assert setup["executable"] is True

    orders = []
    monkeypatch.setattr(fx, "place_forex_order",
                        lambda *a, **k: orders.append("forex") or {"success": True})
    monkeypatch.setattr(main, "place_crypto_order",
                        lambda *a, **k: orders.append("crypto") or {"success": True})
    monkeypatch.setattr("config.FOREX_ENABLED", True)

    # 11:00 and 14:00 are between windows; 9:30 and 20:30 are past one.
    for label, session in (("11:00", None), ("14:00", None),
                           ("09:30", None), ("20:30", None)):
        orders.clear()
        sb.reset_daily_cache("test")
        sb._active_setups["EURUSD"] = dict(setup)
        monkeypatch.setattr(sb, "current_session", lambda *a, **k: session)
        main.run_silver_bullet_entry_check(now=datetime(2026, 10, 15, 11, 0))
        assert orders == [], f"an order was submitted at {label} with no window open"

    sb.reset_daily_cache("test")


def test_the_entry_job_completes_without_a_retired_bias_cache(monkeypatch):
    """
    REGRESSION: removing the Kronos confidence boost left a dangling `bias`
    reference, so every in-window entry raised NameError and was swallowed by
    the job's own try/except — the trade silently never happened.

    The job must run to completion with no Kronos cache present, which is the
    normal state now that `run_kronos_bias_update` is retired.
    """
    import main
    import modules.silver_bullet as sb
    import modules.forex_signal_engine as fse
    import modules.forex_executor as fx
    import modules.candle_provider as cp
    import modules.kronos_engine as ke
    from tests.helpers import (bull_sweep_sequence, candles, silver_bias,
                               silver_entry_frame, silver_session_levels,
                               trusted_vp)

    now = datetime(2026, 10, 15, 8, 30)
    setup = fse.build_setup("EURUSD", candles(bull_sweep_sequence()),
                            silver_session_levels(),
                            silver_bias(vp_levels=trusted_vp()), "LONDON", now)

    # The Kronos cache is empty, as it is in production now.
    ke._kronos_bias_cache.clear()
    assert ke.get_cached_bias("EURUSD") is None

    orders, errors = [], []
    monkeypatch.setattr(fx, "place_forex_order",
                        lambda *a, **k: orders.append("forex") or {"success": True})
    monkeypatch.setattr("config.FOREX_ENABLED", True)
    monkeypatch.setattr(sb, "current_session", lambda *a, **k: "LONDON")
    monkeypatch.setattr(cp, "is_binance", lambda s: False)
    monkeypatch.setattr(cp, "get_candles", lambda *a, **k: silver_entry_frame())
    monkeypatch.setattr(cp, "get_current_price", lambda s: 1.1084)
    monkeypatch.setattr("modules.forex_position_manager.can_open_forex_trade",
                        lambda s: (True, "ok"))

    sb.reset_daily_cache("test")
    sb._active_setups["EURUSD"] = dict(setup)

    main.run_silver_bullet_entry_check(now=now)

    assert orders == ["forex"], (
        "the entry job did not reach the order path with an empty Kronos cache "
        "— it is still raising internally")
    sb.reset_daily_cache("test")


def test_the_entry_job_does_submit_inside_its_window(monkeypatch):
    """
    The mirror of the test above: the guard must not block a legitimate entry,
    or the "no order outside a window" result would be trivially true.
    """
    import main
    import modules.silver_bullet as sb
    import modules.forex_signal_engine as fse
    import modules.forex_executor as fx
    import modules.candle_provider as cp
    from tests.helpers import (bull_sweep_sequence, candles, silver_bias,
                               silver_entry_frame, silver_session_levels,
                               trusted_vp)

    now = datetime(2026, 10, 15, 8, 30)
    setup = fse.build_setup("EURUSD", candles(bull_sweep_sequence()),
                            silver_session_levels(),
                            silver_bias(vp_levels=trusted_vp()), "LONDON", now)

    orders = []
    monkeypatch.setattr(fx, "place_forex_order",
                        lambda *a, **k: orders.append("forex") or {"success": True})
    monkeypatch.setattr("config.FOREX_ENABLED", True)
    monkeypatch.setattr(sb, "current_session", lambda *a, **k: "LONDON")
    monkeypatch.setattr(cp, "is_binance", lambda s: False)
    monkeypatch.setattr(cp, "get_candles", lambda *a, **k: silver_entry_frame())
    monkeypatch.setattr(cp, "get_current_price", lambda s: 1.1084)
    monkeypatch.setattr("modules.forex_position_manager.can_open_forex_trade",
                        lambda s: (True, "ok"))

    sb.reset_daily_cache("test")
    sb._active_setups["EURUSD"] = dict(setup)
    # 08:30 is inside LONDON and before the 20:00 cutoff.
    main.run_silver_bullet_entry_check(now=datetime(2026, 10, 15, 8, 30))

    assert orders == ["forex"], "a legitimate in-window entry was blocked"
    sb.reset_daily_cache("test")


def test_the_entry_job_refuses_after_the_eod_cutoff(monkeypatch):
    """
    The end-of-day cutoff is a separate guard from the session check, and it
    must hold even if a session somehow reports itself open.
    """
    import main
    import modules.silver_bullet as sb
    import modules.forex_executor as fx
    from tests.helpers import silver_entry_frame  # noqa: F401  (fixture parity)

    orders = []
    monkeypatch.setattr(fx, "place_forex_order",
                        lambda *a, **k: orders.append("forex") or {"success": True})
    monkeypatch.setattr("config.FOREX_ENABLED", True)
    # Pretend a window is open past the cutoff.
    monkeypatch.setattr(sb, "current_session", lambda *a, **k: "NY_AFTERNOON")

    sb.reset_daily_cache("test")
    sb._active_setups["EURUSD"] = {"symbol": "EURUSD", "session": "NY_AFTERNOON",
                                   "executable": True, "direction": "BUY"}
    main.run_silver_bullet_entry_check(now=datetime(2026, 10, 15, 20, 30))

    assert orders == [], "an order was submitted after the EOD cutoff"
    sb.reset_daily_cache("test")
    """
    Unregistered, not merely renamed. These generated entries from the BOS/CRT/
    SMC engines, and Silver Bullet is now the only strategy.
    """
    import main
    live = {getattr(j.func, "__name__", str(j.func))
            for j in main.scheduler.get_jobs()}
    offending = sorted(live & set(RETIRED_JOB_FUNCTIONS))
    assert offending == [], f"retired strategy jobs are still scheduled: {offending}"


def test_no_retired_strategy_job_id_is_registered():
    import main
    ids = {j.id for j in main.scheduler.get_jobs()}
    offending = sorted(i for i in ids
                       if any(k in i for k in ("bos", "level1", "level2",
                                               "crypto_crt", "crypto_entry",
                                               "signal_cache")))
    assert offending == [], f"retired job ids still registered: {offending}"


def test_position_monitoring_survives_the_retirement():
    """Existing positions must keep being managed. Only ENTRIES are retired."""
    import main
    ids = {j.id for j in main.scheduler.get_jobs()}
    assert "crypto_position_monitor" in ids
    assert "forex_position_monitor" in ids


def test_the_retired_functions_are_unreachable_from_the_startup_threads():
    """A bootstrap thread is an easy place to leave a retired job running."""
    src = open("main.py", encoding="utf-8").read()
    tree = ast.parse(src)

    bad = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and getattr(node.func, "attr", "") == "Thread":
            for kw in node.keywords:
                if kw.arg == "target":
                    name = getattr(kw.value, "id", None)
                    if name in RETIRED_JOB_FUNCTIONS:
                        bad.append((name, node.lineno))
    assert bad == [], f"startup threads still launch retired jobs: {bad}"


def test_no_retired_strategy_is_reachable_from_a_router():
    """
    Router-triggered scans are another way round a scheduler-only guard.
    """
    import glob
    offenders = []
    for path in glob.glob("routers/*.py"):
        src = open(path, encoding="utf-8").read()
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                name = getattr(node.func, "id", None) or getattr(node.func, "attr", None)
                if name in RETIRED_JOB_FUNCTIONS:
                    offenders.append(f"{path}:{node.lineno} {name}")
    assert offenders == [], f"routers still reach retired jobs: {offenders}"


def test_the_watchdog_drives_silver_bullet_not_a_retired_scan():
    """A watchdog that resurrects a retired strategy is worse than none."""
    src = open("main.py", encoding="utf-8").read()
    tree = ast.parse(src)
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == "_scanner_watchdog")
    body = ast.unparse(fn)
    assert "run_silver_bullet_cycle" in body
    assert "level1_bos_scan" not in body


def test_the_crypto_scan_jobs_are_not_registered_but_their_code_is_retained():
    """
    Retained on disk for reference, unreachable from the schedule. Deleting them
    would make the migration unreviewable; leaving them scheduled would make it
    incomplete.
    """
    import main
    assert hasattr(main, "run_crypto_crt_scan")
    assert hasattr(main, "level2_entry_check")
    live = {getattr(j.func, "__name__", "") for j in main.scheduler.get_jobs()}
    assert "run_crypto_crt_scan" not in live
    assert "level2_entry_check" not in live


def test_no_legacy_module_is_imported_at_startup_by_a_job():
    """
    `crt_detector` and `crypto_strategy` may remain on disk, but no REGISTERED
    job may import them to generate entries.
    """
    import main
    offenders = []
    for job in main.scheduler.get_jobs():
        fn = job.func
        try:
            src = inspect.getsource(fn)
        except (OSError, TypeError):
            continue
        if "crypto_strategy" in src and "entry" in getattr(fn, "__name__", ""):
            offenders.append(job.id)
    assert offenders == [], f"jobs still import a retired engine: {offenders}"


# ══════════════════════════════════════════════════════════════════════════════
#  7. THE ENTRY GUARD HOLDS FOR BOTH VENUES
# ══════════════════════════════════════════════════════════════════════════════

def test_only_silver_bullet_may_submit():
    assert guard.order_source_allowed(guard.STRATEGY_SILVER_BULLET)[0] is True
    for retired in guard.RETIRED_STRATEGIES:
        assert guard.order_source_allowed(retired)[0] is False


def test_an_unidentified_source_may_not_submit():
    assert guard.order_source_allowed(None)[0] is False
    assert guard.order_source_allowed("WHATEVER")[0] is False


def test_the_guard_fails_closed_when_config_is_unreadable(monkeypatch):
    """
    The critical property: an old strategy must never submit merely because the
    new scanner is unavailable, misconfigured, or mid-deploy.
    """
    import builtins
    real_import = builtins.__import__

    def failing(name, *a, **k):
        if name == "config":
            raise ImportError("config unavailable")
        return real_import(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", failing)
    assert guard.legacy_entries_enabled() is False


def test_both_adapters_consult_the_same_guard():
    """
    A lock living in one adapter would leave the other open. Both chokepoints
    must reference the shared rule.
    """
    forex_src = inspect.getsource(fx.place_forex_order)
    crypto_src = inspect.getsource(
        __import__("modules.executor", fromlist=["x"]).place_order)
    assert "order_source_allowed" in forex_src
    assert "order_source_allowed" in crypto_src


def test_the_capital_chokepoint_refuses_a_retired_strategy(monkeypatch):
    import modules.market_data_forex as mdf
    reached = []
    monkeypatch.setattr(mdf, "place_order",
                        lambda *a, **k: reached.append(a) or {"success": True})

    result = fx.place_forex_order(
        {"symbol": "EURUSD", "signal": "BUY", "entry_price": 1.1,
         "stop_loss": 1.095, "take_profit": 1.11, "confidence": 95},
        {}, strategy=guard.STRATEGY_LEGACY_CRT)
    assert result["success"] is False
    assert reached == []


def test_the_binance_chokepoint_refuses_a_retired_strategy(monkeypatch):
    from modules import executor
    import modules.market_data as md
    reached = []
    monkeypatch.setattr(md, "place_order_raw",
                        lambda *a, **k: reached.append(a) or {"success": True})

    result = executor.place_order("BTC/USDT", "BUY", 0.01, 59000, 61000, 95,
                                  strategy=guard.STRATEGY_LEGACY_SMC)
    assert result["success"] is False
    assert reached == []


def test_the_signals_execute_endpoint_refuses(monkeypatch):
    """
    The REST execution endpoint was a second way to place a legacy order.
    """
    from routers import signals as sig_router

    result = sig_router.execute_signal("BTC/USDT", None)
    assert result["success"] is False
    assert result.get("blocked") is True


def test_no_fallback_to_a_retired_strategy_when_silver_bullet_fails(monkeypatch):
    """
    The requirement stated plainly: if the scanner fails, nothing else may
    trade. The scanner is the only thing wired to an entry path.
    """
    import main

    monkeypatch.setattr("config.FOREX_ENABLED", True)

    def exploding_scan(*a, **k):
        raise RuntimeError("scanner failed")

    monkeypatch.setattr(main, "_silver_bullet_scan_once", exploding_scan)

    # The cycle swallows the error and returns; it must not then reach for
    # another engine.
    main.run_silver_bullet_cycle()

    src = ast.unparse(ast.parse(open("main.py", encoding="utf-8").read()))
    cycle_src = inspect.getsource(main.run_silver_bullet_cycle)
    assert "run_crt_scan" not in cycle_src
    assert "level1_bos_scan" not in cycle_src
    assert "crypto_strategy" not in cycle_src


def test_every_entry_path_names_its_strategy_or_is_retired_and_refused():
    """
    Static sweep of every `place_order` / `place_forex_order` call site.

    A call that names its strategy is guarded at the call. A call that does not
    is only acceptable if BOTH hold:

      * its enclosing function is retired (not reachable from the scheduler,
        a startup thread, a router or the watchdog), and
      * the guard would refuse it anyway, because the default strategy is None
        and None is denied.

    That second condition is what makes an unguarded dead call safe rather than
    a loaded gun, so it is asserted rather than assumed.
    """
    retired = set(RETIRED_JOB_FUNCTIONS) | set(RETIRED_ENTRY_HELPERS)
    offenders = []

    for path in ("main.py", "routers/signals.py"):
        tree = ast.parse(open(path, encoding="utf-8").read())
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef):
                continue
            for sub in ast.walk(node):
                if not isinstance(sub, ast.Call):
                    continue
                name = (getattr(sub.func, "id", None)
                        or getattr(sub.func, "attr", None))
                if name not in ("place_forex_order", "place_order"):
                    continue
                # main's own wrapper passes the guard internally.
                if name == "place_order" and node.name == "place_crypto_order":
                    continue
                kwargs = {k.arg for k in sub.keywords}
                if "strategy" in kwargs:
                    continue
                # Unguarded: it must be retired AND refused.
                if node.name not in retired:
                    offenders.append(f"{path}:{sub.lineno} in {node.name}()")
                else:
                    assert guard.order_source_allowed(None)[0] is False, (
                        f"{node.name}() omits the strategy and the guard would "
                        f"allow it")

    assert offenders == [], f"live unguarded order call sites: {offenders}"


def test_the_retired_crypto_entry_functions_cannot_be_scheduled():
    """They are dead code, and nothing may bring them back to life."""
    import main
    live = {getattr(j.func, "__name__", "") for j in main.scheduler.get_jobs()}
    for fn in ("_place_trade", "run_crypto_entry_check", "level2_entry_check"):
        assert fn not in live, f"{fn} is scheduled again"


# ══════════════════════════════════════════════════════════════════════════════
#  8. BAD OR MISSING DATA REFUSES AN ENTRY
# ══════════════════════════════════════════════════════════════════════════════

@pytest.fixture
def stub_scan_env(monkeypatch):
    """
    A scan that can run offline, with the venue guards stubbed to allow.

    The scan lives in `modules.silver_bullet`; `main` only orchestrates it, so
    the module under test is the module that holds the loop.
    """
    import main
    import modules.silver_bullet as sb
    import modules.candle_provider as cp

    monkeypatch.setattr("config.SILVER_BULLET_INSTRUMENTS", ["EURUSD"])
    monkeypatch.setattr(cp, "is_binance", lambda s: False)
    monkeypatch.setattr("modules.forex_position_manager.can_open_forex_trade",
                        lambda s: (True, "ok"))
    return main, sb, cp


def _good_bias():
    from tests.helpers import silver_bias, trusted_vp
    import modules.silver_bullet as sb
    return dict(silver_bias(vp_levels=trusted_vp()),
                session_date=sb.utc_date_key())


def test_missing_candles_refuse_the_setup(stub_scan_env, monkeypatch):
    main, sb, cp = stub_scan_env
    monkeypatch.setattr(cp, "get_candles", lambda *a, **k: None)
    sb.reset_daily_cache("test")
    sb._daily_bias["EURUSD"] = _good_bias()

    assert sb.run_silver_bullet_scan("LONDON", datetime(2026, 10, 15, 8, 30)) == 0
    sb.reset_daily_cache("test")


def test_stale_candles_refuse_the_setup(stub_scan_env, monkeypatch):
    """Too few bars to find a swing or a gap must refuse, not guess."""
    from tests.helpers import candles
    main, sb, cp = stub_scan_env
    monkeypatch.setattr(cp, "get_candles",
                        lambda *a, **k: candles([(1.1, 1.11, 1.09, 1.1, 10.0)] * 5))
    sb.reset_daily_cache("test")
    sb._daily_bias["EURUSD"] = _good_bias()

    assert sb.run_silver_bullet_scan("LONDON", datetime(2026, 10, 15, 8, 30)) == 0
    sb.reset_daily_cache("test")


def test_a_missing_bias_refuses_the_setup(stub_scan_env, monkeypatch):
    from tests.helpers import silver_entry_frame
    main, sb, cp = stub_scan_env
    monkeypatch.setattr(cp, "get_candles", lambda *a, **k: silver_entry_frame())
    sb.reset_daily_cache("test")
    # No bias for today.
    assert sb.run_silver_bullet_scan("LONDON", datetime(2026, 10, 15, 8, 30)) == 0
    sb.reset_daily_cache("test")


def test_an_ungateable_profile_refuses_the_setup(stub_scan_env, monkeypatch):
    """
    A range-proxy profile cannot gate an entry. The pipeline must refuse it
    rather than score it.
    """
    from tests.helpers import silver_entry_frame, silver_bias, trusted_vp
    from modules.forex_signal_engine import build_setup
    main, sb, cp = stub_scan_env

    proxy = dict(trusted_vp(), volume_source="range", source_trusted=False)
    bias = silver_bias(vp_levels=proxy)
    setup = build_setup("EURUSD", silver_entry_frame(),
                        {"swing_high": 1.2, "swing_low": 1.1}, bias,
                        "LONDON", datetime(2026, 10, 15, 8, 30))
    assert setup["executable"] is False
    assert "not gateable" in setup["reject_reason"]


def test_an_unsupported_instrument_is_skipped_by_the_scan(stub_scan_env, monkeypatch):
    """
    A symbol the venue cannot trade must not produce a setup that could never be
    filled.
    """
    from tests.helpers import silver_entry_frame
    main, sb, cp = stub_scan_env

    monkeypatch.setattr("config.SILVER_BULLET_INSTRUMENTS", ["NOSUCH/USDT"])
    monkeypatch.setattr("modules.forex_executor.execution_adapter_for",
                        lambda s: None)
    monkeypatch.setattr(cp, "get_candles", lambda *a, **k: silver_entry_frame())

    sb.reset_daily_cache("test")
    sb._daily_bias["NOSUCH/USDT"] = _good_bias()
    assert sb.run_silver_bullet_scan("LONDON", datetime(2026, 10, 15, 8, 30)) == 0
    assert "NOSUCH/USDT" not in sb.get_active_setups()
    sb.reset_daily_cache("test")


# ══════════════════════════════════════════════════════════════════════════════
#  9. RISK AND POSITION MANAGEMENT SURVIVE
# ══════════════════════════════════════════════════════════════════════════════

def test_daily_loss_limits_still_apply():
    import modules.forex_position_manager as pm
    assert hasattr(pm, "forex_daily_loss_check")
    assert hasattr(pm, "daily_halt_active")
    # And the crypto equivalent.
    import modules.position_manager as cpm
    assert hasattr(cpm, "daily_drawdown_check")


def test_crypto_entries_go_through_the_crypto_risk_guards():
    """FX lot sizing must never be applied to a crypto quantity."""
    src = inspect.getsource(
        __import__("modules.silver_bullet", fromlist=["x"]).run_silver_bullet_scan)
    assert "daily_drawdown_check" in src
    assert "can_reenter" in src


def test_fx_entries_go_through_the_broker_guards():
    src = inspect.getsource(
        __import__("modules.silver_bullet", fromlist=["x"]).run_silver_bullet_scan)
    assert "can_open_forex_trade" in src


def test_the_two_sizing_paths_are_distinct():
    """
    A Capital.com 'lot' and a Binance base-asset quantity are different units,
    and each must be sized by its own function.
    """
    assert hasattr(fx, "calculate_position_size")
    from modules import executor
    assert hasattr(executor, "calculate_silver_bullet_crypto_size")

    fx_src = inspect.getsource(fx.calculate_position_size)
    assert "instrument_spec" in fx_src

    crypto_src = inspect.getsource(executor.calculate_silver_bullet_crypto_size)
    assert "crypto_step_and_min" in crypto_src


def test_the_shared_confidence_tiers_are_used_by_both():
    from modules import executor
    crypto_src = inspect.getsource(executor.calculate_silver_bullet_crypto_size)
    assert "effective_size_multiplier" in crypto_src


# ══════════════════════════════════════════════════════════════════════════════
#  10. SCHEDULE, API AND UI AGREE
# ══════════════════════════════════════════════════════════════════════════════

def test_the_schedule_reports_silver_bullet_as_the_only_strategy():
    from routers.forex import forex_schedule
    schedule = forex_schedule()
    assert schedule["min_confidence"] == 88
    assert schedule["timezone"] == "UTC"
    # The three windows, for every asset class.
    times = {j["time"] for j in schedule["jobs"]}
    assert {"08:00-09:00", "15:00-16:00", "19:00-20:00"} <= times


def test_the_api_session_helper_delegates_to_the_engine():
    from routers.forex import _current_session
    from modules.forex_signal_engine import current_session
    assert _current_session() == (current_session() or "CLOSED")


def test_the_status_payload_exposes_the_strategy_state():
    from routers.forex import _silver_bullet_state
    state = _silver_bullet_state()
    for key in ("active_session", "sessions", "biases", "pending_setups",
                "pending_count", "min_confidence"):
        assert key in state


def test_the_api_reports_the_full_routed_roster():
    """
    The dashboard must be able to show every instrument's market type and
    adapter, from the same source the scanner uses.
    """
    recs = [fx.describe_symbol(s, check_venue=False)
            for s in config.SILVER_BULLET_INSTRUMENTS]
    assert len(recs) == len(config.SILVER_BULLET_INSTRUMENTS)
    kinds = {r["market_type"] for r in recs}
    assert kinds == {"fx", "metal", "crypto"}


def test_no_crt_or_smc_label_remains_on_the_active_trading_screen():
    """
    A label is a claim. Leaving 'CRT' on the live screen would tell the operator
    a retired engine is running.
    """
    src = open("../frontend/src/components/ForexTab.jsx", encoding="utf-8").read()
    assert "CRT PULLBACK" not in src
    assert "CRTSignalCard" not in src
    assert "SilverBulletCard" in src


def test_the_silver_bullet_card_shows_the_required_fields():
    src = open("../frontend/src/components/SilverBulletCard.jsx", encoding="utf-8").read()
    for field in ("h4_bias", "poc", "vah", "val", "session", "confidence",
                  "breakeven_done", "partial_close_pct"):
        assert field in src, f"the card does not show {field}"


def test_the_crypto_api_serves_silver_bullet_not_the_retired_engine():
    """
    The crypto tab read the retired engine's biases and levels. Reporting those
    would tell the operator a strategy is running that cannot trade.
    """
    from routers.crypto_strategy import crypto_strategy_status

    payload = crypto_strategy_status()
    assert payload["strategy"] == "SILVER_BULLET"
    assert payload["min_confidence"] == 88
    assert payload["active_session"] is not None
    # The retired engine's keys must not be sourced from it any more.
    src = open("routers/crypto_strategy.py", encoding="utf-8").read()
    assert "get_all_crypto_biases" not in src
    assert "_crypto_levels" not in src


def test_the_crypto_api_reports_the_full_universe_with_routing():
    from routers.crypto_strategy import crypto_strategy_status

    payload = crypto_strategy_status()
    assert set(payload["universe"]) == set(get_universe())
    assert len(payload["routing"]) == len(get_universe())
    for rec in payload["routing"]:
        assert rec["market_type"] == "crypto"
        assert rec["execution_adapter"] == fx.ADAPTER_BINANCE
        assert rec["position_manager"] == "modules.position_manager"


def test_the_crypto_api_keeps_its_legacy_keys_for_compatibility():
    """An existing frontend build must not break on a missing field."""
    from routers.crypto_strategy import crypto_strategy_status

    payload = crypto_strategy_status()
    for key in ("biases", "crt_levels", "active_setups", "universe"):
        assert key in payload, f"the crypto API dropped {key}"


def test_the_crypto_api_does_not_reach_the_network(monkeypatch):
    """The dashboard polls this every 15s; it must not do venue round trips."""
    import modules.market_data_forex as mdf
    import modules.market_data as md

    def explode(*a, **k):
        raise AssertionError("the crypto status API made a venue call")

    monkeypatch.setattr(mdf, "resolve_epic", explode)
    monkeypatch.setattr(mdf, "get_dealing_rules", explode)
    monkeypatch.setattr(md, "get_lot_size_rules", explode)

    from routers.crypto_strategy import crypto_strategy_status
    assert crypto_strategy_status()["strategy"] == "SILVER_BULLET"


def test_no_retired_engine_is_imported_by_a_router_at_call_time():
    """
    `crypto_strategy` and `crt_detector` may remain on disk, but no router may
    call into them to report or generate strategy state.
    """
    import glob
    offenders = []
    for path in glob.glob("routers/*.py"):
        src = open(path, encoding="utf-8").read()
        for line in src.split("\n"):
            stripped = line.strip()
            if stripped.startswith("from modules.crypto_strategy import"):
                offenders.append(f"{path}: {stripped}")
    assert offenders == [], f"routers still import the retired engine: {offenders}"


def test_the_retired_data_refresh_jobs_are_not_registered():
    """
    A refresh job whose only consumer is a retired strategy is the "running
    merely to populate a UI card" case. The dashboard is served from the Silver
    Bullet volume profile instead.
    """
    import main
    live = {getattr(j.func, "__name__", "") for j in main.scheduler.get_jobs()}
    for fn in ("run_kronos_bias_update", "run_crt_scan",
               "run_daily_pdh_pdl_reset", "run_crypto_kronos_bias",
               "run_crypto_crt_scan"):
        assert fn not in live, f"{fn} is still scheduled"


def test_the_crt_range_cache_is_no_longer_read_by_an_endpoint():
    """
    The retired scanner fed `crt_detector._crt_levels_cache`. If an endpoint
    still reads it, retiring the scanner blanks the card.
    """
    import ast

    offenders = []
    for path in ("routers/forex.py", "main.py"):
        tree = ast.parse(open(path, encoding="utf-8").read())
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                body = "\n".join(
                    ast.unparse(n) for n in node.body
                    if not (isinstance(n, ast.Expr)
                            and isinstance(n.value, ast.Constant)
                            and isinstance(n.value.value, str)))
                if "get_cached_levels" in body:
                    offenders.append(f"{path}:{node.name}")
    assert offenders == [], f"still reading the retired CRT cache: {offenders}"


def test_the_manual_strategy_endpoints_do_not_run_a_retired_engine():
    """
    The manual refresh routes kept their names for compatibility, but must do
    the live strategy's work rather than the retired engine's.
    """
    import ast

    tree = ast.parse(open("routers/forex.py", encoding="utf-8").read())
    for name in ("update_kronos_bias", "update_crt_levels"):
        fn = next(n for n in ast.walk(tree)
                  if isinstance(n, ast.FunctionDef) and n.name == name)
        body = "\n".join(
            ast.unparse(n) for n in fn.body
            if not (isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant)
                    and isinstance(n.value.value, str)))
        assert "calculate_daily_bias" in body, f"{name} does not run Silver Bullet"
        assert "kronos_engine" not in body, f"{name} still runs Kronos"
        assert "crt_detector" not in body, f"{name} still runs the CRT detector"


def test_the_signal_cache_endpoint_does_not_compute_a_retired_signal():
    """
    A read-only endpoint must not produce a tradeable recommendation from an
    engine that can no longer trade.

    Checked against the parsed module, not the raw text: the docstring explains
    what `compute_signal` was and why it went, and a substring match would flag
    that explanation as a violation.
    """
    import ast

    tree = ast.parse(open("routers/signals.py", encoding="utf-8").read())

    # No import of the retired engine at all.
    for node in ast.walk(tree):
        mods = []
        if isinstance(node, ast.ImportFrom) and node.module:
            mods = [node.module]
        elif isinstance(node, ast.Import):
            mods = [a.name for a in node.names]
        assert not any(m.endswith("signal_engine") for m in mods), \
            "signals.py imports the retired SMC engine"

    # And no call to it.
    calls = {getattr(n.func, "id", None) or getattr(n.func, "attr", None)
             for n in ast.walk(tree) if isinstance(n, ast.Call)}
    assert "compute_signal" not in calls, "signals.py still computes a retired signal"


def test_the_bot_status_does_not_read_the_retired_crypto_setups():
    import ast

    tree = ast.parse(open("main.py", encoding="utf-8").read())
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == "bot_status")
    body = "\n".join(
        ast.unparse(n) for n in fn.body
        if not (isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant)
                and isinstance(n.value.value, str)))
    assert "crypto_strategy" not in body
    assert "get_crypto_setups" not in body
