"""
backend/modules/forex_executor.py
Capital.com REST order execution for Forex/Metals.

Pure synchronous — no asyncio. Position sizing is in Capital.com "lots".

Capital.com's order `size` field is in UNITS of the instrument, not lots, and a
"lot" does not mean the same thing across the instrument families:

    FX      1 lot = 100,000 units of the base currency
    Metals  1 lot = 100 oz (gold) / 5,000 oz (silver)
    Crypto  no lot at all — Binance quantity is base-asset units on a step grid

`instrument_spec()` is the single place that is recorded for this module. The
crypto path lives in modules/executor.py and deliberately does not share it.
"""
import logging
import math
from datetime import datetime
from typing import Dict, Optional, Tuple

from database import SessionLocal
from models import ForexTrade

logger = logging.getLogger(__name__)


# The strategy's hard confidence floor. Mirrors forex_signal_engine's
# MIN_CONFIDENCE and config's FOREX_MIN_CONF; kept as a literal here so sizing
# cannot be imported into a state where the floor is undefined.
MIN_TRADE_CONFIDENCE = 88


# ══════════════════════════════════════════════════════════════════════════════
#  EXECUTION ADAPTER RESOLUTION
#
#  Silver Bullet is the only strategy, but it must not become the only ADAPTER.
#  A Capital.com CFD order and a Binance spot order are not the same request and
#  must not be forced into one implementation:
#
#    forex + metals  Capital.com   size in instrument UNITS, min/max/increment
#                                  from the broker's dealing rules
#    crypto          Binance       quantity in BASE-ASSET units on the
#                                  exchange's step grid, min notional
#
#  What IS unified is the STRATEGY: both venues feed the same pipeline through
#  `candle_provider`, and both produce the same signal dict. This module decides
#  which adapter a signal belongs to, so no caller has to guess.
# ══════════════════════════════════════════════════════════════════════════════

ADAPTER_CAPITAL = "capital"
ADAPTER_BINANCE = "binance"


def instrument_kind(symbol: str) -> str:
    """
    The market family of a symbol: 'metal', 'fx' or 'crypto'.

    Delegates to the Capital.com spec table for the CFD families so there is one
    definition of what a metal is, and uses the candle provider's routing for
    the crypto/CFD split.
    """
    from modules.candle_provider import is_binance
    if is_binance(symbol):
        return "crypto"
    return instrument_spec(symbol)["family"]


def execution_adapter_for(symbol: str) -> Optional[str]:
    """
    Which execution adapter serves `symbol`, or None when it cannot be routed.

    This is PURE ROUTING — it depends only on the symbol's shape, never on a
    venue call. That matters because it is consulted on every scan tick: a
    network round trip per symbol per scan would make the scanner slow and
    fragile, and would make "is this symbol routed?" change with venue uptime.

    Whether the venue can actually TRADE the instrument is a separate question
    with a separate answer (`instrument_is_tradeable`), asked once at the order
    boundary where a failure must refuse the order.
    """
    try:
        from modules.candle_provider import is_binance
    except Exception:
        return None

    if not symbol:
        return None
    return ADAPTER_BINANCE if is_binance(symbol) else ADAPTER_CAPITAL


def instrument_is_tradeable(symbol: str) -> Tuple[bool, str]:
    """
    Whether the venue will actually accept an order for `symbol`.

    Returns (ok, reason). This one DOES consult the venue, because the answer
    depends on the venue's own specification:

      * Capital.com — a resolvable epic AND dealing rules with a positive
        minimum. An instrument we cannot look up cannot be sized, and sizing it
        blindly is how an order is rejected or, worse, mis-sized.
      * Binance — lot rules with a positive step. A delisted symbol has none.

    A venue failure returns False with the reason, so the caller refuses the
    order rather than guessing. This is the check that must fail closed.
    """
    if not symbol:
        return False, "no symbol"

    adapter = execution_adapter_for(symbol)
    if adapter is None:
        return False, "symbol could not be routed to an execution adapter"

    try:
        if adapter == ADAPTER_BINANCE:
            from modules.market_data import get_lot_size_rules
            rules = get_lot_size_rules(symbol) or {}
            step = float(rules.get("step_size") or 0)
            if step <= 0:
                return False, f"exchange returned no step size for {symbol}"
            return True, "ok"

        from modules.market_data_forex import get_dealing_rules, resolve_epic
        if not resolve_epic(symbol):
            return False, f"no broker epic for {symbol}"
        rules = get_dealing_rules(symbol) or {}
        if float(rules.get("min_deal_size") or 0) <= 0:
            return False, f"broker returned no dealing rules for {symbol}"
        return True, "ok"

    except Exception as e:
        # The venue could not be asked. Fail closed.
        return False, f"venue check failed for {symbol}: {e}"


def is_supported_symbol(symbol: str) -> bool:
    """Convenience boolean over `instrument_is_tradeable`."""
    return instrument_is_tradeable(symbol)[0]


def position_manager_for(symbol: str) -> Optional[str]:
    """
    Which position manager owns `symbol`'s open trades.

    The two venues keep their trades in different tables with different
    lifecycle rules, so this is not cosmetic: sending a Binance position through
    the Capital.com manager would look for a deal id that does not exist and
    silently leave the position unmanaged.
    """
    adapter = execution_adapter_for(symbol)
    if adapter == ADAPTER_CAPITAL:
        return "modules.forex_position_manager"
    if adapter == ADAPTER_BINANCE:
        return "modules.position_manager"
    return None


def describe_symbol(symbol: str, check_venue: bool = True) -> Dict:
    """
    The full routing record for one symbol, for the audit and the API.

    Returns the market type, data provider, execution adapter, position manager
    and scanning function, plus `supported` and a reason when it is not. This is
    the single source of truth the migration report and the dashboard both read.

    `check_venue=False` reports routing only, without a venue call — used by the
    API path where a network round trip per symbol would be unacceptable.
    """
    try:
        from modules.candle_provider import provider_for
        provider = provider_for(symbol)
    except Exception:
        provider = None

    try:
        kind = instrument_kind(symbol)
    except Exception:
        kind = None

    adapter = execution_adapter_for(symbol)
    if check_venue:
        supported, reason = instrument_is_tradeable(symbol)
    else:
        supported, reason = (adapter is not None), (
            "ok" if adapter is not None else "not routable")

    return {
        "symbol": symbol,
        "market_type": kind,
        "data_provider": provider,
        "execution_adapter": adapter,
        "position_manager": position_manager_for(symbol),
        "scan_function": "modules.silver_bullet.run_silver_bullet_scan",
        "strategy": STRATEGY_SILVER_BULLET,
        "supported": supported,
        "unsupported_reason": None if supported else reason,
        "venue_checked": check_venue,
    }
#
#  The Silver Bullet engine is the unified strategy. The CRT/SMC forex path is
#  kept alive only for the dashboard data it publishes (CRT levels, Kronos bias)
#  and MUST NOT submit orders during the migration.
#
#  The rule itself lives in `modules/strategy_guard`, shared with the Binance
#  executor, so the two venues cannot disagree about which strategy may trade.
#  Duplicating it here would leave one venue open the moment the other changed.
#
#  It FAILS CLOSED. An unreadable or missing flag denies the order. The whole
#  point is that an old strategy must never submit an order merely because the
#  new scanner is unavailable, misconfigured, or mid-deploy — so "I could not
#  read the flag" resolves to "do not trade", never to "trade".
# ══════════════════════════════════════════════════════════════════════════════

from modules.strategy_guard import (  # noqa: E402
    RETIRED_STRATEGIES,
    STRATEGY_LEGACY_CRT,
    STRATEGY_LEGACY_SMC,
    STRATEGY_SILVER_BULLET,
    legacy_entries_enabled,
    order_source_allowed,
    refuse_order,
)

# Kept as a module attribute so an operator (or a test) can flip it in place.
LEGACY_FOREX_ENTRIES_ENABLED = False


# ── Pip / lot helpers ─────────────────────────────────────────────────────────

def _pip_size(symbol: str) -> float:
    """Pip size for a symbol. See `instrument_spec` for the contract table."""
    return instrument_spec(symbol)["pip_size"]


def _pip_value_per_lot(symbol: str) -> float:
    """
    USD value of 1 pip for 1 standard lot.

    An approximation for non-USD quote currencies — see `instrument_spec`.
    """
    return instrument_spec(symbol)["pip_value_per_lot"]


def _contract_size(symbol: str) -> float:
    """
    Units of the instrument in 1 standard lot.

    Capital.com's order `size` field is in UNITS, not lots, so a risk-based
    lot figure must be multiplied by this before it is sent. Sending lots
    directly produces 'error.invalid.size.minvalue'.
    """
    return instrument_spec(symbol)["contract_size"]


# ── Confidence-tier sizing ────────────────────────────────────────────────────
#
# NOTE ON PROVENANCE: these tiers are NOT copied from the master specification —
# that document was not available when this was written. They are conservative
# defaults chosen to be strictly safer than the values this module used before
# (which were 95 -> 2.0x, 90 -> 1.5x, 85 -> 1.0x), and every number here is
# env-overridable. Treat them as a starting point to be reconciled against the
# spec, not as the spec.
#
# The band that matters is 88-89: that is the strategy's hard floor, so it is
# the marginal case and gets LESS than full size. Sizing the marginal band at
# 1.0x — which the previous table did, since 85 <= 88 — would put the most
# capital behind the weakest setups the engine is willing to take.
#
# (threshold, multiplier), highest threshold first.
CONFIDENCE_SIZE_TIERS = (
    (96, 1.50),   # elite
    (93, 1.25),   # strong
    (90, 1.00),   # full
    (88, 0.75),   # marginal — the floor itself
)

# A tier multiplier may never exceed this, whatever the table or config says.
# It is the ceiling the compounding and drawdown multipliers are validated
# against, so a misconfigured tier cannot scale a position without bound.
SILVER_MAX_SIZE_MULTIPLIER = 1.50

# Floor on the combined multiplier, so a deep drawdown reduces size rather
# than rounding a live setup down to nothing.
SILVER_MIN_SIZE_MULTIPLIER = 0.25

# Partial take-profit plan: (level, fraction of the ORIGINAL position).
# TP3 takes the remainder rather than a fraction, because by then the position
# has already been reduced twice and any fraction would leave dust.
PARTIAL_TAKE_PROFIT_PLAN = (
    (1, 0.50),
    (2, 0.25),
    (3, None),
)

# Trailing stop distance, in ATR, once TP1 has been taken.
TRAIL_ATR_MULTIPLE = 1.0

# A TP3 derived from a liquidity target is only used when it is at least this
# many R away. Closer than that and the "target" is inside the noise, so the
# fallback multiple is used instead.
TP3_MIN_R = 2.0
TP3_FALLBACK_R = 3.0
# A liquidity target further than this is treated as stale rather than as a
# real objective, so TP3 falls back instead of aiming at an unreachable level.
TP3_MAX_R = 12.0

# The high-confidence extension: at or above this score, a liquidity target
# beyond TP3_FALLBACK_R is honoured instead of being clipped to it.
TP3_EXTENSION_CONFIDENCE = 96

# Stop geometry, taken from the strategy engine so the entry path and the
# execution path cannot disagree about how wide a stop may be. Imported lazily
# inside the functions that need them so this module stays importable even if
# the engine is mid-edit, and defaulted here as the fallback.
SL_ATR_BUFFER = 0.5
SL_MAX_ATR = 6.0


def confidence_size_multiplier(confidence: float) -> float:
    """
    Size multiplier for a confidence score.

    A score below the strategy floor returns 0.0 — not the smallest tier —
    because "below the floor" means "do not trade", and returning a small
    positive number would let a caller that forgot its own gate open a
    position the engine already rejected.
    """
    try:
        score = float(confidence)
    except (TypeError, ValueError):
        return 0.0

    if score < MIN_TRADE_CONFIDENCE:
        return 0.0

    for threshold, mult in CONFIDENCE_SIZE_TIERS:
        if score >= threshold:
            return min(float(mult), SILVER_MAX_SIZE_MULTIPLIER)
    return 0.0


def drawdown_size_multiplier(balance: float) -> float:
    """
    Capital-protection multiplier from the existing risk manager.

    Returns 1.0 when the risk manager is unavailable, so a failure there
    cannot silently halve every position; the hard caps below still apply.
    """
    try:
        from modules.risk_manager import get_drawdown_guard
        return float(get_drawdown_guard(balance))
    except Exception as e:
        logger.warning(f"[capital] drawdown guard unavailable ({e}) — using 1.0")
        return 1.0


def effective_size_multiplier(confidence: float, balance: float) -> Tuple[float, Dict]:
    """
    Combine the confidence tier with the drawdown guard, then clamp.

    Returns (multiplier, detail). The order matters and is the point:

      1. the tier comes from the score,
      2. the drawdown guard scales it DOWN,
      3. the product is clamped to [MIN, MAX].

    Clamping LAST is what makes the hard cap actually hard. Applying the cap
    first and the drawdown multiplier afterwards would let a 1.5x tier times a
    1.0x guard pass at 1.5x, and a misconfigured guard above 1.0 could exceed
    the cap entirely.
    """
    tier = confidence_size_multiplier(confidence)
    guard = drawdown_size_multiplier(balance)

    # A guard above 1.0 would be a risk INCREASE, which the guard's contract
    # ("reduce risk if in drawdown") never intends. Clamp it rather than trust
    # the caller.
    guard = max(0.0, min(1.0, guard))

    if tier <= 0:
        return 0.0, {"tier": 0.0, "guard": guard, "combined": 0.0,
                     "reason": f"confidence {confidence} below the "
                               f"{MIN_TRADE_CONFIDENCE} floor"}

    combined = tier * guard
    clamped = max(SILVER_MIN_SIZE_MULTIPLIER, min(SILVER_MAX_SIZE_MULTIPLIER, combined))

    return clamped, {
        "tier": tier,
        "guard": guard,
        "combined": round(combined, 4),
        "clamped": round(clamped, 4),
        "cap": SILVER_MAX_SIZE_MULTIPLIER,
        "capped": clamped != combined,
    }


# ── Instrument specification ──────────────────────────────────────────────────

def instrument_spec(symbol: str) -> Dict:
    """
    Contract, pip and precision metadata for a Capital.com instrument.

    "Lot" does NOT mean the same thing across these instruments, and this is
    the single place that fact is recorded:

      * FX      1 lot = 100,000 units of the BASE currency. Capital.com's order
                `size` is in those base units.
      * Metals  1 lot = 100 oz (gold) or 5,000 oz (silver). The order `size`
                is in ounces, so the contract multiplier differs from FX.
      * Crypto  (BTC/ETH) has no lot at all — Binance quantity is in the base
                asset and is constrained by a step size, not a lot multiple.
                That path lives in modules/executor.py and must not share this
                table.

    `pip_value_per_lot` is quoted in USD and is an APPROXIMATION for pairs
    whose quote currency is not USD: it is only exact when the account is
    USD-denominated and the quote currency is USD. The risk ceiling below
    therefore does not rely on it alone — it is cross-checked against the
    broker's own minimum deal size.
    """
    s = (symbol or "").upper().replace("/", "")
    spec = {
        # The symbol is normalised so two spellings of the same instrument
        # produce identical specs — a caller comparing specs must not see a
        # difference that does not exist.
        "symbol": s,
        "family": "fx",
        "contract_size": 100000.0,
        "pip_size": 0.0001,
        "pip_value_per_lot": 10.0,
        "price_decimals": 5,
    }
    if s.startswith("XAU"):
        spec.update(family="metal", contract_size=100.0, pip_size=0.01,
                    pip_value_per_lot=1.0, price_decimals=2)
    elif s.startswith("XAG"):
        spec.update(family="metal", contract_size=5000.0, pip_size=0.01,
                    pip_value_per_lot=50.0, price_decimals=3)
    elif s.endswith("JPY"):
        # A JPY pair is quoted in JPY, so the pip value in a USD account moves
        # with USDJPY. 7.0 is the long-run approximation the module already
        # used; it is a known source of error and is logged as such.
        spec.update(pip_size=0.01, pip_value_per_lot=7.0, price_decimals=3)
    return spec


def validate_instrument(symbol: str, rules: Optional[Dict] = None) -> Tuple[bool, str, Dict]:
    """
    Check an instrument is tradeable and that our assumptions match the broker.

    Returns (ok, reason, spec). The spec is returned even when ok is False so a
    caller can log what it believed.

    This is where "do not assume" is enforced: the broker's own
    `minDealSize` is compared against the size our contract assumption implies
    for a 1-lot trade. A disagreement means one of the two is wrong about what
    a unit is, and continuing would size the position off a bad multiplier.
    """
    if not symbol:
        return False, "no symbol", {}

    spec = instrument_spec(symbol)

    from config import CAPITAL_EPIC_MAP
    known = symbol.upper().replace("/", "") in {
        k.upper().replace("/", "") for k in CAPITAL_EPIC_MAP
    }
    if not known and spec["family"] == "fx" and not symbol.upper().endswith("USD"):
        # An unlisted cross has no verified contract assumption. It is allowed
        # through — resolve_epic will reject it if the broker does not have it —
        # but the caller is told the spec is inferred rather than known.
        spec["verified"] = False
    else:
        spec["verified"] = True

    if rules:
        min_size = rules.get("min_deal_size") or 0.0
        if min_size > 0:
            spec["broker_min_size"] = min_size
            # A broker minimum at or above a full lot means our contract
            # multiplier is the wrong scale for this instrument.
            if min_size >= spec["contract_size"]:
                return (False,
                        f"broker minimum size {min_size} >= assumed contract "
                        f"size {spec['contract_size']} — unit assumption is wrong "
                        f"for {symbol}", spec)
    return True, "ok", spec


def validate_order(symbol: str, size: float, price: float,
                   rules: Optional[Dict] = None) -> Tuple[bool, str]:
    """
    Validate a prospective order against the broker's constraints.

    Checks, in order: a finite positive size, the broker minimum, the broker
    maximum, alignment to the broker's increment, and a sane notional. Returns
    (ok, reason) — never raises.
    """
    try:
        if not symbol:
            return False, "no symbol"

        try:
            size = float(size)
            price = float(price)
        except (TypeError, ValueError):
            return False, "size and price must be numeric"

        if not math.isfinite(size) or not math.isfinite(price):
            return False, "size and price must be finite"
        if size <= 0:
            return False, f"size {size} must be positive"
        if price <= 0:
            return False, f"price {price} must be positive"

        rules = rules or {}
        min_size = rules.get("min_deal_size") or 0.0
        max_size = rules.get("max_deal_size") or 0.0
        increment = rules.get("min_increment") or 0.0

        if min_size > 0 and size < min_size:
            return False, f"size {size} below broker minimum {min_size}"
        if max_size > 0 and size > max_size:
            return False, f"size {size} above broker maximum {max_size}"

        if increment > 0:
            steps = size / increment
            if abs(steps - round(steps)) > 1e-6:
                return False, (f"size {size} is not a multiple of the broker "
                               f"increment {increment}")

        return True, "ok"

    except Exception as e:
        return False, f"validation error: {e}"


def snap_to_increment(size: float, increment: float) -> float:
    """
    Round a size DOWN to the broker's increment.

    Down, never up: rounding up can push a correctly-sized position past the
    risk cap, and past the broker maximum. Rounding down only ever reduces
    exposure.
    """
    try:
        size = float(size)
        increment = float(increment or 0.0)
        if increment <= 0:
            return round(size, 4)
        snapped = math.floor(size / increment + 1e-9) * increment
        decimals = max(0, int(round(-math.log10(increment)))) + 2
        return round(snapped, decimals)
    except Exception:
        return 0.0


# ── Stop and target calculation ───────────────────────────────────────────────

def calculate_stops_and_targets(symbol: str, direction: str, entry: float,
                                sweep_wick: float, atr: float,
                                confidence: float,
                                liquidity_target: Optional[float] = None,
                                atr_buffer: float = SL_ATR_BUFFER,
                                max_atr: float = SL_MAX_ATR
                                ) -> Optional[Dict]:
    """
    Derive the stop and the three targets for a Silver Bullet entry.

    Stop: beyond the sweep wick by `atr_buffer` ATR. The wick is the level the
    setup says was defended, so a stop inside it would be stopped out by the
    same move that created the setup.

    Targets: TP1 at 1R, TP2 at 2R, TP3 at the liquidity target when one is
    supplied and usable, otherwise at 3R. The high-confidence extension honours
    a liquidity target beyond 3R when the score is at or above
    TP3_EXTENSION_CONFIDENCE.

    Returns None when the setup is untradeable: a non-positive or non-finite
    price, a missing ATR, a stop on the wrong side of entry, a stop wider than
    `max_atr` ATR, or a stop so tight the R multiple is meaningless.
    """
    try:
        # Prefer the engine's constants so a change there cannot leave the
        # execution path enforcing a different stop ceiling than the entry path.
        if atr_buffer is None or max_atr is None:
            from modules.forex_signal_engine import (SL_ATR_BUFFER as _buf,
                                                     SL_MAX_ATR as _max)
            atr_buffer = _buf if atr_buffer is None else atr_buffer
            max_atr = _max if max_atr is None else max_atr

        entry = float(entry)
        sweep_wick = float(sweep_wick)
        atr = float(atr)
        confidence = float(confidence)

        if not all(math.isfinite(v) for v in (entry, sweep_wick, atr, confidence)):
            logger.warning(f"[capital] {symbol} non-finite stop input — rejected")
            return None
        if entry <= 0 or sweep_wick <= 0:
            logger.warning(f"[capital] {symbol} non-positive price — rejected")
            return None
        if atr <= 0:
            logger.warning(f"[capital] {symbol} no ATR — cannot size a stop")
            return None
        if direction not in ("BUY", "SELL"):
            return None

        if direction == "BUY":
            sl = sweep_wick - (atr_buffer * atr)
        else:
            sl = sweep_wick + (atr_buffer * atr)

        # The stop must be on the losing side of the entry, or the trade has
        # no risk to define and every R multiple below is meaningless.
        if direction == "BUY" and sl >= entry:
            logger.warning(f"[capital] {symbol} BUY stop {sl} >= entry {entry} — rejected")
            return None
        if direction == "SELL" and sl <= entry:
            logger.warning(f"[capital] {symbol} SELL stop {sl} <= entry {entry} — rejected")
            return None

        risk = abs(entry - sl)

        # A stop tighter than 0.5 ATR is inside the instrument's own noise.
        # Widening it raises the R denominator rather than tightening the stop,
        # which is the same rule the entry path applies.
        min_risk = 0.5 * atr
        if risk < min_risk:
            sl = entry - min_risk if direction == "BUY" else entry + min_risk
            risk = abs(entry - sl)

        if risk > max_atr * atr:
            logger.warning(f"[capital] {symbol} stop {risk / atr:.2f} ATR exceeds "
                           f"the {max_atr} ATR ceiling — rejected")
            return None

        sign = 1 if direction == "BUY" else -1

        tp3 = None
        target_r = None
        if liquidity_target:
            try:
                lt = float(liquidity_target)
                if math.isfinite(lt) and lt > 0:
                    target_r = (lt - entry) * sign / risk
            except (TypeError, ValueError):
                target_r = None

        extended = confidence >= TP3_EXTENSION_CONFIDENCE
        used_liquidity_target = False

        if target_r is not None and target_r >= TP3_MIN_R:
            if target_r <= TP3_FALLBACK_R or extended:
                tp3 = float(liquidity_target)
                used_liquidity_target = True
            else:
                # Beyond 3R but the score is not high enough to reach for it.
                tp3 = entry + sign * risk * TP3_FALLBACK_R
        else:
            tp3 = entry + sign * risk * TP3_FALLBACK_R

        if target_r is not None and target_r > TP3_MAX_R:
            logger.info(f"[capital] {symbol} liquidity target {target_r:.1f}R is "
                        f"beyond the {TP3_MAX_R}R ceiling — using "
                        f"{TP3_FALLBACK_R}R instead")
            tp3 = entry + sign * risk * TP3_FALLBACK_R
            used_liquidity_target = False

        tp1 = entry + sign * risk * 1.0
        tp2 = entry + sign * risk * 2.0

        return {
            "direction": direction,
            "entry": round(entry, 5),
            "stop_loss": round(sl, 5),
            "tp1": round(tp1, 5),
            "tp2": round(tp2, 5),
            "tp3": round(tp3, 5),
            "risk": round(risk, 5),
            "risk_atr": round(risk / atr, 3),
            "atr": round(atr, 5),
            "tp3_r": round(abs(tp3 - entry) / risk, 3),
            # True only when TP3 is actually the liquidity target. Reporting it
            # from the confidence alone would claim an extension on a setup
            # whose target the ceiling had just discarded.
            "tp3_extended": bool(used_liquidity_target
                                 and target_r is not None
                                 and target_r > TP3_FALLBACK_R),
            "liquidity_target": float(liquidity_target) if liquidity_target else None,
        }

    except Exception as e:
        logger.error(f"[capital] stop/target error {symbol}: {e}")
        return None


def partial_close_size(original_size: float, level: int,
                       already_closed: float = 0.0) -> float:
    """
    Units to close at a partial level, given what has already been closed.

    TP3 returns everything still open rather than a fraction, so the position
    is never left holding a sliver too small for the broker to accept.
    """
    try:
        original_size = float(original_size)
        already_closed = float(already_closed or 0.0)
    except (TypeError, ValueError):
        return 0.0

    remaining = original_size - already_closed
    if remaining <= 0:
        return 0.0

    for lvl, fraction in PARTIAL_TAKE_PROFIT_PLAN:
        if lvl == level:
            if fraction is None:
                return remaining
            return min(original_size * fraction, remaining)
    return 0.0


# ── Position sizing ───────────────────────────────────────────────────────────

def calculate_position_size(symbol: str, entry: float, sl: float,
                            confidence: float, balance: float) -> float:
    """
    Return a Capital.com order size in UNITS (not lots).

    risk_pct    = forex_risk_pct(balance)  — scales down for small accounts
    risk_amount = balance * risk_pct
    risk_pips   = |entry - sl| / pip_size
    lots        = risk_amount / (risk_pips * pip_value_per_lot)
    size        = lots * contract_size

    The result is snapped to the instrument's minDealSize / minSizeIncrement
    from Capital.com's dealing rules, because the broker rejects anything
    smaller than its minimum. On tight stops the minimum can imply more risk
    than the configured target — that is logged so it is never silent.
    """
    try:
        from config import (forex_risk_pct, FOREX_MIN_TRADEABLE_BALANCE,
                            FOREX_MAX_IMPLIED_RISK_PCT)
        from modules.market_data_forex import get_dealing_rules

        if balance <= 0:
            logger.warning(f"[capital] {symbol} no balance available — skipping")
            return 0.0

        if balance < FOREX_MIN_TRADEABLE_BALANCE:
            logger.warning(f"[capital] {symbol} balance ${balance:.2f} below the "
                           f"${FOREX_MIN_TRADEABLE_BALANCE:.0f} minimum — skipping")
            return 0.0

        risk_pct = forex_risk_pct(balance)

        # A user-set override wins over the balance-scaled default, so the
        # setting is authoritative rather than advisory.
        try:
            from modules.risk_settings import get_settings
            override = get_settings().get("forex_risk_pct")
            if override:
                risk_pct = float(override)
        except Exception:
            pass

        risk_amount = balance * risk_pct
        spec = instrument_spec(symbol)
        pip = spec["pip_size"]
        pvpl = spec["pip_value_per_lot"]
        contract = spec["contract_size"]

        risk_pips = abs(entry - sl) / pip
        if risk_pips < 1:
            logger.warning(f"[capital] {symbol} stop too tight ({risk_pips:.2f} pips)")
            return 0.0

        lots = risk_amount / (risk_pips * pvpl)

        # ── Confidence tier x drawdown guard, clamped to the hard cap ────────
        # The multiplier is applied to the RISK, not to the final size, so the
        # implied-risk ceiling below still measures the real exposure. Scaling
        # the size afterwards would let a 1.5x tier push a position past the
        # ceiling the ceiling exists to enforce.
        mult, mult_detail = effective_size_multiplier(confidence, balance)
        if mult <= 0:
            logger.warning(f"[capital] {symbol} {mult_detail.get('reason')} — skipping")
            return 0.0
        lots *= mult

        size = lots * contract

        # ── Respect the broker's dealing rules ───────────────────────────────
        rules = get_dealing_rules(symbol)
        min_size = rules.get("min_deal_size") or 0.0
        increment = rules.get("min_increment") or 0.0
        max_size = rules.get("max_deal_size") or 0.0

        if increment > 0:
            size = snap_to_increment(size, increment)
        else:
            size = round(size, 4)

        if min_size > 0 and size < min_size:
            implied = (min_size / contract) * risk_pips * pvpl
            logger.warning(
                f"[capital] {symbol} risk-based size {size} below broker minimum "
                f"{min_size} — raising to minimum (implied risk ${implied:.2f} vs "
                f"target ${risk_amount:.2f})"
            )
            size = min_size

        if max_size > 0 and size > max_size:
            logger.warning(f"[capital] {symbol} size {size} capped at broker max {max_size}")
            size = max_size

        if size <= 0:
            logger.warning(f"[capital] {symbol} computed size is zero — skipping")
            return 0.0

        # ── Final risk ceiling ───────────────────────────────────────────────
        # The broker minimum can force a position far larger than the target
        # risk, and a tier multiplier can raise it further. Refuse the trade
        # rather than open something oversized: a fixed tier must never
        # silently override the hard risk limit.
        implied_risk = (size / contract) * risk_pips * pvpl
        implied_pct = implied_risk / balance if balance > 0 else 1.0
        if implied_pct > FOREX_MAX_IMPLIED_RISK_PCT:
            logger.warning(
                f"[capital] {symbol} skipped — size {size} implies "
                f"${implied_risk:.2f} risk ({implied_pct*100:.1f}% of ${balance:.2f}), "
                f"above the {FOREX_MAX_IMPLIED_RISK_PCT*100:.0f}% ceiling"
            )
            return 0.0

        # The validation gate the broker would apply, applied here first so a
        # doomed order is never sent.
        ok, why = validate_order(symbol, size, entry, rules)
        if not ok:
            logger.warning(f"[capital] {symbol} order rejected before sending: {why}")
            return 0.0

        logger.info(f"[capital] {symbol} size: {size} units "
                    f"(={size / contract:.4f} lots, risk=${implied_risk:.2f} "
                    f"@{risk_pct*100:.1f}% target, stop={risk_pips:.1f}pips "
                    f"conf={confidence}% tier={mult_detail['tier']}x "
                    f"guard={mult_detail['guard']}x -> {mult}x"
                    f"{' CAPPED' if mult_detail.get('capped') else ''} "
                    f"min={min_size} inc={increment})")
        return size

    except Exception as e:
        logger.error(f"[capital] position size error {symbol}: {e}")
        return 0.0


# ── Place order ───────────────────────────────────────────────────────────────

def place_forex_order(signal_data: Dict, kronos_bias: Dict,
                      strategy: Optional[str] = None) -> Dict:
    """
    Open a Capital.com position and record it in the ForexTrade table.

    signal_data keys: symbol, signal, entry_price, stop_loss, take_profit,
                      confidence, crt_setup, pdh, pdl

    `strategy` identifies the caller and is REQUIRED to be
    `STRATEGY_SILVER_BULLET` for an order to be sent. It defaults to None, which
    is DENIED, so a caller written before the lock existed cannot submit by
    omission — see `order_source_allowed`.
    """
    try:
        allowed, why = order_source_allowed(strategy)
        if not allowed:
            symbol = (signal_data or {}).get("symbol", "?")
            logger.warning(f"[capital] order REFUSED for {symbol}: {why}")
            return {"success": False, "error": f"entry blocked: {why}",
                    "blocked": True, "strategy": strategy}

        from modules.market_data_forex import place_order, get_capital_balance

        symbol     = signal_data["symbol"]
        signal     = signal_data["signal"]          # BUY / SELL
        entry      = signal_data["entry_price"]
        sl         = signal_data["stop_loss"]
        tp         = signal_data["take_profit"]
        confidence = signal_data["confidence"]

        bal = get_capital_balance()
        balance = bal.get("balance", 0) or 10000.0

        size = calculate_position_size(symbol, entry, sl, confidence, balance)
        if size <= 0:
            return {"success": False, "error": "Invalid position size"}

        result = place_order(symbol, signal, size, sl, tp)
        if not result.get("success"):
            return {"success": False, "error": result.get("error", "order failed")}

        # Record in DB (metaapi_position_id stores the Capital.com dealId)
        db = SessionLocal()
        try:
            # The initial risk and stop are captured HERE, before any partial or
            # stop move, because every R multiple and the trailing logic are
            # measured from them. Re-deriving them later from a moved stop would
            # shrink R with every trail and make the targets meaningless.
            fill = float(result.get("fill_price") or entry)
            initial_risk = abs(fill - float(sl))

            trade = ForexTrade(
                symbol=symbol,
                signal=signal,
                confidence=confidence,
                entry_price=fill,
                stop_loss=sl,
                take_profit=tp,
                tp1=signal_data.get("tp1"),
                tp2=signal_data.get("tp2", tp),
                tp3=signal_data.get("tp3"),
                entry_type=signal_data.get("entry_type"),
                partial_tp_hit=False,
                tp1_done=False,
                tp2_done=False,
                breakeven_done=False,
                trailing_active=False,
                peak_price=fill,
                initial_stop=sl,
                initial_risk=round(initial_risk, 8),
                original_lots=size,
                lots=size,
                session_name=signal_data.get("session"),
                session_expires_at=_parse_expiry(signal_data.get("expires_at")),
                vp_confluence=signal_data.get("vp_confluence"),
                partial_close_pct=0.0,
                kronos_bias=(kronos_bias or {}).get("bias", "NEUTRAL"),
                crt_setup=signal_data.get("crt_setup", "NONE"),
                pdh=signal_data.get("pdh"),
                pdl=signal_data.get("pdl"),
                crt_timeframe=signal_data.get("crt_timeframe"),
                confirm_timeframe=signal_data.get("confirm_timeframe"),
                entry_timeframe=signal_data.get("entry_timeframe"),
                poi=signal_data.get("poi"),
                metaapi_position_id=result.get("deal_id"),
                outcome="OPEN",
            )
            db.add(trade)
            db.commit()
            db.refresh(trade)
            logger.info(
                f"[forex] ENTRY {signal} {symbol} @ {fill:.5f} | "
                f"{signal_data.get('entry_type', '?')} | conf={confidence:.0f}% | "
                f"SL={sl:.5f} | TP1={trade.tp1} | TP2={trade.tp2} | TP3={trade.tp3} | "
                f"risk={initial_risk:.5f} size={size}"
            )
            result["trade_id"] = trade.id
            result["initial_risk"] = initial_risk
        except Exception as e:
            logger.error(f"[capital] db record error: {e}")
            db.rollback()
        finally:
            db.close()

        return result

    except Exception as e:
        logger.error(f"[capital] place_forex_order error: {e}")
        return {"success": False, "error": str(e)}


def _parse_expiry(value) -> Optional[datetime]:
    """Parse a session expiry from an ISO string, tolerating None and junk."""
    if not value:
        return None
    if isinstance(value, datetime):
        return value.replace(tzinfo=None)
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).replace(tzinfo=None)
    except (TypeError, ValueError):
        return None


# ── Close position ────────────────────────────────────────────────────────────

def close_forex_position(deal_id: str, trade_id: int, pnl: float = None) -> Dict:
    """
    Close a Capital.com position and update the ForexTrade row.

    When `pnl` is not supplied the realised P&L is read from the broker
    before closing, so manual closes are recorded with the real figure
    rather than defaulting to zero.

    Returns {success, pnl, symbol, error}.
    """
    try:
        from modules.market_data_forex import close_position

        result = close_position(deal_id)
        if not result.get("success"):
            logger.error(f"[capital] close failed for {deal_id}: {result.get('error')}")
            return {"success": False, "error": result.get("error", "close failed")}

        realised = result.get("pnl") if pnl is None else pnl
        realised = float(realised or 0.0)

        db = SessionLocal()
        try:
            trade = db.query(ForexTrade).filter(ForexTrade.id == trade_id).first()
            if trade:
                trade.outcome = "WIN" if realised >= 0 else "LOSS"
                trade.pnl = round(realised, 4)
                trade.closed_at = datetime.utcnow()
                db.commit()
                logger.info(f"[forex] CLOSED {trade.symbol} {trade.signal} — "
                            f"P&L ${realised:+.2f} (trade id={trade_id})")
                result["symbol"] = result.get("symbol") or trade.symbol
        except Exception as e:
            logger.error(f"[capital] db update error: {e}")
            db.rollback()
        finally:
            db.close()

        result["pnl"] = round(realised, 2)
        return result

    except Exception as e:
        logger.error(f"[capital] close_forex_position error: {e}")
        return {"success": False, "error": str(e)}


def close_all_forex_positions() -> Dict:
    """
    Close every open Capital.com position and settle the matching rows.

    Returns {success, closed, failed, total_pnl, results}.
    """
    results = []
    total_pnl = 0.0
    failed = 0

    db = SessionLocal()
    try:
        open_trades = db.query(ForexTrade).filter(ForexTrade.outcome == "OPEN").all()
        pending = [
            {"id": t.id, "symbol": t.symbol, "deal_id": t.metaapi_position_id}
            for t in open_trades
        ]
    finally:
        db.close()

    if not pending:
        return {"success": True, "closed": 0, "failed": 0,
                "total_pnl": 0.0, "results": []}

    for item in pending:
        if not item["deal_id"]:
            # Never reached the broker — just settle the row locally
            _settle_local(item["id"], 0.0)
            results.append({"symbol": item["symbol"], "success": True, "pnl": 0.0})
            continue

        res = close_forex_position(item["deal_id"], item["id"])
        if res.get("success"):
            pnl = float(res.get("pnl") or 0.0)
            total_pnl += pnl
            results.append({"symbol": item["symbol"], "success": True, "pnl": pnl})
        else:
            failed += 1
            results.append({"symbol": item["symbol"], "success": False,
                            "error": res.get("error")})

    logger.info(f"[forex] CLOSE ALL — {len(pending) - failed} closed, "
                f"{failed} failed, total P&L ${total_pnl:+.2f}")

    return {
        "success": failed == 0,
        "closed": len(pending) - failed,
        "failed": failed,
        "total_pnl": round(total_pnl, 2),
        "results": results,
    }


def _settle_local(trade_id: int, pnl: float) -> None:
    """Mark a trade closed without a broker call (no deal id recorded)."""
    db = SessionLocal()
    try:
        trade = db.query(ForexTrade).filter(ForexTrade.id == trade_id).first()
        if trade:
            trade.outcome = "WIN" if pnl >= 0 else "LOSS"
            trade.pnl = round(float(pnl), 4)
            trade.closed_at = datetime.utcnow()
            db.commit()
    except Exception as e:
        logger.error(f"[capital] local settle error: {e}")
        db.rollback()
    finally:
        db.close()
