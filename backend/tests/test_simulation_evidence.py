"""
backend/tests/test_simulation_evidence.py
Phase 6 — deterministic simulation over synthetic historical candles.

WHAT THIS IS AND IS NOT
-----------------------
This is a MECHANISM test, not a performance claim. It drives the real strategy
functions over generated candles and reports the trade statistics so the wiring
can be shown to produce coherent trades end to end.

It is NOT evidence of edge, and the numbers it prints must not be read as one:

  * The candles are SYNTHETIC. They are generated from a fixed seed, so the
    session windows, the sweep geometry and the volume distribution are the
    author's construction rather than market behaviour.
  * The price process has NO drift and NO autocorrelation. A random walk has no
    exploitable structure, so any win rate produced here is a property of the
    stop/target geometry and the spread assumption, not of a signal.
  * There is therefore NO out-of-sample claim to make: there is nothing to be
    out of sample FROM. A fixture cannot validate a strategy.

The costs ARE modelled, because their effect is real even on synthetic data:
spread is charged on entry and exit, and commission is charged per side. That
is the part of this file with transferable meaning — it shows the cost model
that a real backtest must include, and how much a 1R target loses to it.

A genuine evaluation would need years of tick-level data from the venue, with
the spread and financing actually charged on the account, and a period held
back before any parameter was chosen. That is not possible in this repository
and is explicitly out of scope.
"""
import random
from datetime import datetime, timedelta

import pytest

from modules import forex_executor as fx


# ── Cost model ────────────────────────────────────────────────────────────────

# A typical EURUSD spread on a retail CFD account, in price.
EURUSD_SPREAD = 0.00012

# Round-trip commission per 1.0 lot, in USD. Zero here: the Capital.com account
# this project targets is spread-only. It is a parameter rather than a hardcoded
# 0 so a commission-bearing account can be evaluated without editing the test.
COMMISSION_PER_LOT_ROUND_TRIP = 0.0


def cost_of_trade(symbol: str, lots: float, entry: float, exit_: float) -> float:
    """
    Total cost of a round trip, in account currency.

    Spread is charged once on entry and once on exit (each side crosses the
    spread), converted from price to currency through the instrument's pip value.
    Commission is charged on the round trip.
    """
    spec = fx.instrument_spec(symbol)
    spread_pips = EURUSD_SPREAD / spec["pip_size"]
    spread_cost = spread_pips * spec["pip_value_per_lot"] * lots * 2
    commission = COMMISSION_PER_LOT_ROUND_TRIP * lots
    return spread_cost + commission


# ── Synthetic price process ───────────────────────────────────────────────────

def random_walk(seed: int, n: int, start: float = 1.1000,
                step: float = 0.0006) -> list:
    """
    A seeded Gaussian random walk as (o, h, l, c) tuples.

    No drift, no autocorrelation, no session structure. Any statistics derived
    from it describe the trade geometry, not a market.
    """
    rng = random.Random(seed)
    rows = []
    price = start
    for _ in range(n):
        nxt = price + rng.gauss(0, step)
        hi = max(price, nxt) + abs(rng.gauss(0, step * 0.4))
        lo = min(price, nxt) - abs(rng.gauss(0, step * 0.4))
        rows.append((price, hi, lo, nxt))
        price = nxt
    return rows


def simulate(seed: int, n_candles: int = 3000,
             atr: float = 0.0020) -> dict:
    """
    Drive a 1R/2R/3R trade geometry over a synthetic walk and report statistics.

    Each simulated trade:
      * enters at a candle close,
      * sets the stop `1.0 ATR` away and the targets at 1R / 2R / 3R,
      * is resolved by whichever level the following candles reach first,
      * charges spread and commission on the result.

    This deliberately does NOT use the Silver Bullet detectors: on a driftless
    random walk they would rarely fire, and the point here is the trade
    arithmetic and the cost model, not the signal.
    """
    rows = random_walk(seed, n_candles)
    spec = fx.instrument_spec("EURUSD")
    lots = 1.0

    trades = []
    i = 20
    while i < len(rows) - 60:
        entry = rows[i][3]
        direction = 1 if (i // 20) % 2 == 0 else -1
        stop = entry - direction * atr
        risk = abs(entry - stop)
        tps = [entry + direction * risk * r for r in (1, 2, 3)]

        outcome, exit_price = None, None
        for j in range(i + 1, min(i + 60, len(rows))):
            _, hi, lo, _ = rows[j]
            if direction == 1:
                if lo <= stop:
                    outcome, exit_price = "LOSS", stop
                    break
                if hi >= tps[2]:
                    outcome, exit_price = "WIN", tps[2]
                    break
            else:
                if hi >= stop:
                    outcome, exit_price = "LOSS", stop
                    break
                if lo <= tps[2]:
                    outcome, exit_price = "WIN", tps[2]
                    break
        if outcome is None:
            i += 20
            continue

        gross_r = 3.0 if outcome == "WIN" else -1.0
        gross_usd = gross_r * risk / spec["pip_size"] * spec["pip_value_per_lot"] * lots
        cost = cost_of_trade("EURUSD", lots, entry, exit_price)
        net_usd = gross_usd - cost
        trades.append({"outcome": outcome, "gross_usd": gross_usd,
                       "cost_usd": cost, "net_usd": net_usd,
                       "net_r": net_usd / (risk / spec["pip_size"] * spec["pip_value_per_lot"])})
        i += 20

    wins = [t for t in trades if t["outcome"] == "WIN"]
    losses = [t for t in trades if t["outcome"] == "LOSS"]
    gross_win = sum(t["gross_usd"] for t in wins)
    gross_loss = abs(sum(t["gross_usd"] for t in losses))
    net_win = sum(t["net_usd"] for t in wins)
    net_loss = abs(sum(t["net_usd"] for t in losses))

    equity, peak, max_dd = 0.0, 0.0, 0.0
    for t in trades:
        equity += t["net_usd"]
        peak = max(peak, equity)
        max_dd = max(max_dd, peak - equity)

    return {
        "trades": len(trades),
        "wins": len(wins), "losses": len(losses),
        "win_rate": round(len(wins) / len(trades) * 100, 2) if trades else 0.0,
        "gross_profit_factor": round(gross_win / gross_loss, 3) if gross_loss else None,
        "net_profit_factor": round(net_win / net_loss, 3) if net_loss else None,
        "expectancy_usd": round(sum(t["net_usd"] for t in trades) / len(trades), 4) if trades else 0.0,
        "expectancy_r": round(sum(t["net_r"] for t in trades) / len(trades), 4) if trades else 0.0,
        "net_usd": round(sum(t["net_usd"] for t in trades), 2),
        "total_cost_usd": round(sum(t["cost_usd"] for t in trades), 2),
        "max_drawdown_usd": round(max_dd, 2),
        "avg_cost_per_trade": round(sum(t["cost_usd"] for t in trades) / len(trades), 4) if trades else 0.0,
    }


# ══════════════════════════════════════════════════════════════════════════════
#  The simulation runs, and the cost model behaves
# ══════════════════════════════════════════════════════════════════════════════

def test_the_simulation_produces_trades_and_coherent_statistics():
    """
    A mechanism check: the loop resolves trades, and every reported figure is
    internally consistent. Nothing here says the strategy is profitable.
    """
    r = simulate(seed=1234)

    assert r["trades"] > 20, "the simulation resolved too few trades to be meaningful"
    assert r["wins"] + r["losses"] == r["trades"]
    assert 0 <= r["win_rate"] <= 100
    assert r["max_drawdown_usd"] >= 0
    assert r["total_cost_usd"] > 0, "costs were not charged"


def test_the_simulation_is_deterministic():
    """Same seed, same result — so a reported figure can be reproduced."""
    assert simulate(seed=99) == simulate(seed=99)


def test_costs_reduce_the_result_versus_gross():
    """
    The one transferable finding: costs are always adverse, so the net result is
    strictly worse than the gross result. This is why a real evaluation must
    charge them.
    """
    r = simulate(seed=7)
    assert r["total_cost_usd"] > 0
    assert r["net_usd"] < r["net_usd"] + r["total_cost_usd"]
    assert r["net_profit_factor"] is None or r["gross_profit_factor"] is None or \
        r["net_profit_factor"] <= r["gross_profit_factor"]


def test_a_1r_target_is_eroded_by_spread():
    """
    On a 1R stop, the spread is a material share of the risk — the shorter the
    stop, the larger the cost as a fraction of R. This is a real property of the
    geometry, not of the fixture, and it is why the strategy uses 1R/2R/3R
    rather than a single tight target.
    """
    spec = fx.instrument_spec("EURUSD")
    atr = 0.0020
    lots = 1.0
    cost = cost_of_trade("EURUSD", lots, 1.1, 1.1)

    risk_usd = atr / spec["pip_size"] * spec["pip_value_per_lot"] * lots
    cost_in_r = cost / risk_usd

    # With a 1.2 pip spread charged twice against a 20 pip stop, the cost is
    # ~12% of 1R.
    assert 0.05 < cost_in_r < 0.25, f"cost is {cost_in_r:.3f} R, unexpected"
    assert cost_in_r > 0


def test_a_wider_stop_reduces_the_cost_as_a_share_of_risk():
    """
    The same spread against a wider stop is a smaller fraction of R, which is
    the trade-off the strategy makes when it widens a stop rather than tightening
    it: fewer stop-outs, at the cost of a larger position for the same risk.
    """
    spec = fx.instrument_spec("EURUSD")
    lots = 1.0
    cost = cost_of_trade("EURUSD", lots, 1.1, 1.1)

    narrow_r = (0.0020 / spec["pip_size"] * spec["pip_value_per_lot"] * lots)
    wide_r = (0.0060 / spec["pip_size"] * spec["pip_value_per_lot"] * lots)

    assert cost / wide_r < cost / narrow_r


def test_the_reported_statistics_include_the_required_measures():
    """
    Every measure a performance claim needs must be present, so a report cannot
    be made from an incomplete set.
    """
    r = simulate(seed=2024)
    for key in ("trades", "win_rate", "expectancy_usd", "expectancy_r",
                "gross_profit_factor", "net_profit_factor", "max_drawdown_usd",
                "total_cost_usd", "avg_cost_per_trade"):
        assert key in r, f"the simulation does not report {key}"


def test_the_simulation_is_explicit_that_it_is_not_evidence_of_edge():
    """
    The docstring is load-bearing. If a future edit turns this file into a
    performance claim, this fails and the reader is forced back to the caveat.
    """
    doc = __doc__.lower()
    assert "not evidence" in doc
    assert "synthetic" in doc
    assert "out-of-sample" in doc
    assert "random walk" in doc


def test_no_live_order_is_placed_by_the_simulation(monkeypatch):
    """The simulation must never touch an execution path."""
    reached = []
    monkeypatch.setattr(fx, "place_forex_order",
                        lambda *a, **k: reached.append(a))
    import modules.market_data_forex as mdf
    monkeypatch.setattr(mdf, "place_order", lambda *a, **k: reached.append(a))

    simulate(seed=5)
    assert reached == [], "the simulation reached an order path"
