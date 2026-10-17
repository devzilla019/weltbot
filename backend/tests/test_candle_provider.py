"""
backend/tests/test_candle_provider.py
Phase 2 — the venue routing seam and the normalized frame contract.

The provider is the only place that knows whether a symbol trades on Capital.com
or Binance. These tests pin the routing (so a crypto symbol can never be sent to
the broker and vice versa), the frame contract every consumer relies on, and the
volume-provenance labelling that the volume gate depends on.
"""
import pandas as pd
import pytest

from modules import candle_provider as cp


# ── Routing ───────────────────────────────────────────────────────────────────

def test_forex_pairs_route_to_capital():
    for symbol in ("EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCAD"):
        assert cp.provider_for(symbol) == cp.CAPITAL


def test_metals_route_to_capital_despite_the_usd_suffix():
    """
    XAUUSD ends in "USD" and would look like a crypto pair to a naive
    quote-asset test. Metals are resolved first for exactly that reason.
    """
    for symbol in ("XAUUSD", "XAGUSD", "XPTUSD", "XPDUSD"):
        assert cp.provider_for(symbol) == cp.CAPITAL


def test_crypto_pairs_route_to_binance():
    for symbol in ("BTC/USDT", "ETH/USDT", "SOLUSDT", "BTCUSDT", "ETH-BUSD"):
        assert cp.provider_for(symbol) == cp.BINANCE


def test_separators_are_irrelevant_to_routing():
    for symbol in ("BTC/USDT", "BTC-USDT", "BTC_USDT", "btcusdt", "BTCUSDT"):
        assert cp.provider_for(symbol) == cp.BINANCE


def test_normalize_symbol_strips_every_separator():
    assert cp.normalize_symbol("btc/usdt") == "BTCUSDT"
    assert cp.normalize_symbol("eth-usdt") == "ETHUSDT"
    assert cp.normalize_symbol(" xau_usd ") == "XAUUSD"
    assert cp.normalize_symbol("") == ""


def test_is_binance_mirrors_provider_for():
    assert cp.is_binance("BTC/USDT") is True
    assert cp.is_binance("EURUSD") is False


def test_unknown_symbols_default_to_capital():
    """An unrecognised symbol must not be silently sent to the exchange."""
    assert cp.provider_for("EURCHF") == cp.CAPITAL
    assert cp.provider_for("SOMETHINGWEIRD") == cp.CAPITAL


# ── The frame contract ────────────────────────────────────────────────────────

def _raw_capital_frame():
    return pd.DataFrame({
        "timestamp": pd.to_datetime(
            ["2026-10-15 02:00", "2026-10-15 00:00", "2026-10-15 01:00"], utc=True),
        "open": [1.2, 1.0, 1.1],
        "high": [1.3, 1.1, 1.2],
        "low": [1.1, 0.9, 1.0],
        "close": [1.25, 1.05, 1.15],
        "volume": [10.0, 30.0, 20.0],
    })


def test_normalize_sorts_ascending_by_timestamp():
    out = cp._normalize(_raw_capital_frame(), "tick")
    assert out is not None
    assert out["timestamp"].is_monotonic_increasing
    assert list(out["close"]) == [1.05, 1.15, 1.25]


def test_normalize_drops_duplicate_timestamps_keeping_the_last():
    df = _raw_capital_frame()
    df = pd.concat([df, df.iloc[[1]].assign(close=9.99)], ignore_index=True)
    out = cp._normalize(df, "tick")
    assert out is not None
    assert out["timestamp"].is_unique
    assert 9.99 in set(out["close"])


def test_normalize_coerces_numeric_columns():
    df = _raw_capital_frame()
    df["open"] = df["open"].astype(str)
    out = cp._normalize(df, "tick")
    assert out is not None
    assert pd.api.types.is_numeric_dtype(out["open"])


def test_normalize_drops_rows_with_unparseable_ohlc():
    df = _raw_capital_frame()
    df["high"] = df["high"].astype(object)
    df.loc[0, "high"] = "not a number"
    out = cp._normalize(df, "tick")
    assert out is not None
    assert len(out) == 2


def test_normalize_returns_the_documented_column_set():
    out = cp._normalize(_raw_capital_frame(), "tick")
    assert list(out.columns) == [
        "timestamp", "open", "high", "low", "close", "volume"]


def test_normalize_adds_a_zero_volume_column_when_absent():
    df = _raw_capital_frame().drop(columns=["volume"])
    out = cp._normalize(df, "exchange")
    assert out is not None
    assert "volume" in out.columns
    assert (out["volume"] == 0.0).all()
    # A frame with no volume must not keep claiming a real volume source.
    assert out.attrs["volume_source"] == "none"


def test_normalize_returns_none_when_an_ohlc_column_is_missing():
    df = _raw_capital_frame().drop(columns=["low"])
    assert cp._normalize(df, "tick") is None


def test_normalize_returns_none_when_every_row_is_invalid():
    df = _raw_capital_frame()
    df["high"] = "bad"
    assert cp._normalize(df, "tick") is None


def test_normalize_reports_none_when_ohlc_are_non_numeric():
    df = _raw_capital_frame()
    for col in ("open", "high", "low", "close"):
        df[col] = df[col].astype(object)
        df.loc[0, col] = "bad"
    out = cp._normalize(df, "tick")
    assert out is not None
    assert len(out) == 2


def test_normalize_keeps_working_without_a_timestamp_column():
    df = _raw_capital_frame().drop(columns=["timestamp"])
    out = cp._normalize(df, "tick")
    assert out is not None
    assert "timestamp" not in out.columns
    assert len(out) == 3


def test_normalize_stamps_the_volume_source():
    assert cp._normalize(_raw_capital_frame(), "tick").attrs["volume_source"] == "tick"
    assert cp._normalize(_raw_capital_frame(), "exchange").attrs["volume_source"] == "exchange"


def test_normalize_does_not_mutate_the_input():
    df = _raw_capital_frame()
    before = df.copy()
    cp._normalize(df, "tick")
    pd.testing.assert_frame_equal(df, before)


# ── CoinGecko fallback detection ──────────────────────────────────────────────

def test_constant_volume_is_recognised_as_the_coingecko_fallback():
    """
    market_data stamps a constant 1000000.0 volume on every candle when every
    Binance mirror failed. A constant series carries no distributional
    information, so it must not be presented as exchange volume.
    """
    df = pd.DataFrame({"volume": [1_000_000.0] * 10})
    assert cp._came_from_coingecko(df) is True


def test_varying_volume_is_not_the_fallback():
    df = pd.DataFrame({"volume": [1.0, 2.0, 3.0, 4.0, 5.0, 6.0]})
    assert cp._came_from_coingecko(df) is False


def test_a_short_series_is_treated_as_the_fallback():
    df = pd.DataFrame({"volume": [1.0, 2.0, 3.0]})
    assert cp._came_from_coingecko(df) is True


def test_a_missing_volume_column_is_treated_as_the_fallback():
    assert cp._came_from_coingecko(pd.DataFrame({"close": [1.0] * 10})) is True


# ── get_candles: routing, failure and the volume tag ──────────────────────────

@pytest.fixture
def stub_venues(monkeypatch):
    """Patch both venue fetchers and record which one was called."""
    import modules.market_data as md
    import modules.market_data_forex as mdf

    calls = {"binance": [], "capital": []}
    responses = {"binance": None, "capital": None}

    def fake_binance(symbol, interval="1h", limit=400):
        calls["binance"].append((symbol, interval, limit))
        return responses["binance"]

    def fake_capital(symbol, timeframe="1h", limit=400):
        calls["capital"].append((symbol, timeframe, limit))
        return responses["capital"]

    monkeypatch.setattr(md, "fetch_ohlcv", fake_binance)
    monkeypatch.setattr(mdf, "get_candles", fake_capital)
    return calls, responses


def test_binance_symbols_never_reach_the_broker(stub_venues):
    calls, responses = stub_venues
    responses["binance"] = pd.DataFrame({
        "timestamp": pd.date_range("2026-10-15", periods=5, freq="1h", tz="UTC"),
        "open": [1.0] * 5, "high": [2.0] * 5,
        "low": [0.5] * 5, "close": [1.5] * 5,
        "volume": [1.0, 2.0, 3.0, 4.0, 5.0],
    })

    df = cp.get_candles("BTC/USDT", "1h", 5)
    assert df is not None
    assert len(calls["capital"]) == 0
    assert calls["binance"][0][0] == "BTCUSDT"
    assert df.attrs["volume_source"] == "exchange"


def test_forex_symbols_never_reach_the_exchange(stub_venues):
    calls, responses = stub_venues
    fx = _raw_capital_frame()
    fx.attrs["volume_source"] = "tick"
    responses["capital"] = fx

    df = cp.get_candles("EURUSD", "1h", 3)
    assert df is not None
    assert len(calls["binance"]) == 0
    assert calls["capital"][0][0] == "EURUSD"
    assert df.attrs["volume_source"] == "tick"


def test_a_constant_binance_volume_is_downgraded_to_a_proxy(stub_venues):
    calls, responses = stub_venues
    responses["binance"] = pd.DataFrame({
        "timestamp": pd.date_range("2026-10-15", periods=8, freq="1h", tz="UTC"),
        "open": [1.0] * 8, "high": [2.0] * 8,
        "low": [0.5] * 8, "close": [1.5] * 8,
        "volume": [1_000_000.0] * 8,
    })

    df = cp.get_candles("BTC/USDT", "1h", 8)
    assert df is not None
    assert df.attrs["volume_source"] == "proxy"


def test_a_capital_frame_without_volume_is_tagged_none(stub_venues):
    calls, responses = stub_venues
    fx = _raw_capital_frame().drop(columns=["volume"])
    responses["capital"] = fx

    df = cp.get_candles("EURUSD", "1h", 3)
    assert df is not None
    assert df.attrs["volume_source"] == "none"


def test_a_missing_capital_volume_source_defaults_to_none(stub_venues):
    """A frame from a venue that never sets the attribute must not be trusted."""
    calls, responses = stub_venues
    responses["capital"] = _raw_capital_frame()  # no attrs at all

    df = cp.get_candles("EURUSD", "1h", 3)
    assert df is not None
    assert df.attrs["volume_source"] == "none"


def test_empty_venue_responses_return_none(stub_venues):
    calls, responses = stub_venues
    responses["capital"] = None
    responses["binance"] = None

    assert cp.get_candles("EURUSD", "1h", 3) is None
    assert cp.get_candles("BTC/USDT", "1h", 3) is None


def test_an_empty_frame_returns_none(stub_venues):
    calls, responses = stub_venues
    responses["capital"] = pd.DataFrame()
    responses["binance"] = pd.DataFrame()

    assert cp.get_candles("EURUSD", "1h", 3) is None
    assert cp.get_candles("BTC/USDT", "1h", 3) is None


def test_a_venue_exception_returns_none_rather_than_raising(monkeypatch):
    import modules.market_data_forex as mdf

    def explode(*_a, **_k):
        raise RuntimeError("broker is down")

    monkeypatch.setattr(mdf, "get_candles", explode)
    assert cp.get_candles("EURUSD", "1h", 3) is None


def test_an_exchange_exception_returns_none_rather_than_raising(monkeypatch):
    import modules.market_data as md

    def explode(*_a, **_k):
        raise RuntimeError("exchange is down")

    monkeypatch.setattr(md, "fetch_ohlcv", explode)
    assert cp.get_candles("BTC/USDT", "1h", 3) is None


def test_an_empty_symbol_returns_none():
    assert cp.get_candles("", "1h", 3) is None
    assert cp.get_candles(None, "1h", 3) is None


def test_get_candles_normalized_returns_the_frame_and_its_source(stub_venues):
    calls, responses = stub_venues
    fx = _raw_capital_frame()
    fx.attrs["volume_source"] = "tick"
    responses["capital"] = fx

    df, source = cp.get_candles_normalized("EURUSD", "1h", 3)
    assert df is not None
    assert source == "tick"


def test_get_candles_normalized_reports_none_when_the_fetch_fails(stub_venues):
    calls, responses = stub_venues
    responses["capital"] = None
    df, source = cp.get_candles_normalized("EURUSD", "1h", 3)
    assert df is None
    assert source == "none"


def test_normalized_frames_keep_the_attrs_when_copied(stub_venues):
    """
    A caller that mutates a returned frame must not corrupt the cached one, and
    a `.copy()` must carry the volume provenance with it.
    """
    calls, responses = stub_venues
    fx = _raw_capital_frame()
    fx.attrs["volume_source"] = "tick"
    responses["capital"] = fx

    df = cp.get_candles("EURUSD", "1h", 3)
    df.attrs["volume_source"] = "tampered"
    assert df.copy().attrs["volume_source"] == "tampered"


# ── get_current_price routing ─────────────────────────────────────────────────

def test_price_routing_follows_the_symbol(monkeypatch):
    import modules.market_data as md
    import modules.market_data_forex as mdf

    seen = []
    monkeypatch.setattr(md, "get_ticker_price",
                        lambda s: seen.append(("binance", s)) or 123.0)
    monkeypatch.setattr(mdf, "get_current_price",
                        lambda s: seen.append(("capital", s)) or 1.2345)

    assert cp.get_current_price("BTC/USDT") == 123.0
    assert cp.get_current_price("EURUSD") == 1.2345
    assert seen == [("binance", "BTCUSDT"), ("capital", "EURUSD")]


def test_price_failure_returns_zero(monkeypatch):
    import modules.market_data_forex as mdf

    def explode(_s):
        raise RuntimeError("no price")

    monkeypatch.setattr(mdf, "get_current_price", explode)
    assert cp.get_current_price("EURUSD") == 0.0


def test_price_for_an_empty_symbol_is_zero():
    assert cp.get_current_price("") == 0.0
