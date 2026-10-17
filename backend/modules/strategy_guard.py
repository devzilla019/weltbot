"""
backend/modules/strategy_guard.py
The single gate that decides which strategy may submit an order.

Silver Bullet is the only signal-generation strategy in this application. The
CRT and SMC engines are retained on disk for reference, but no path that reaches
an execution adapter may use them.

WHY THIS IS A SEPARATE MODULE
-----------------------------
The lock has to hold for BOTH venues. Capital.com orders go through
`forex_executor.place_forex_order` and Binance orders through
`executor.place_order`, so a lock living in either one would leave the other
open. It also must not be duplicated: two copies of a security rule drift, and
the drift is invisible because each looks correct in isolation.

So the rule lives here once, and every execution adapter consults it.

IT FAILS CLOSED
---------------
Every failure mode denies:
  * an unreadable config flag denies,
  * an unidentified caller denies,
  * an unknown strategy name denies.

The point is that an old strategy must never submit an order merely because the
new scanner is unavailable, misconfigured, or mid-deploy. "I could not determine
that this is allowed" resolves to "do not trade", never to "trade".
"""
import logging
from typing import Optional, Tuple

logger = logging.getLogger(__name__)

# The only strategy permitted to create new trades.
STRATEGY_SILVER_BULLET = "SILVER_BULLET"

# Retired strategies. They may be named by a caller — so the refusal is
# explicit and logged rather than a confusing "unidentified" — but they are
# never permitted while the lock is engaged.
STRATEGY_LEGACY_CRT = "LEGACY_CRT"
STRATEGY_LEGACY_SMC = "LEGACY_SMC"

RETIRED_STRATEGIES = (STRATEGY_LEGACY_CRT, STRATEGY_LEGACY_SMC)

# Escape hatch for deliberately re-running a retired strategy. Off by default:
# the migration is the safe state, not the exception.
LEGACY_ENTRIES_ENABLED_DEFAULT = False


def legacy_entries_enabled() -> bool:
    """
    Whether a RETIRED strategy may submit orders. Fails closed.

    Reads config so an operator can flip it without a code change, but an
    unreadable config value denies rather than permits.
    """
    if LEGACY_ENTRIES_ENABLED_DEFAULT:
        return True
    try:
        from config import LEGACY_FOREX_ENTRIES_ENABLED as configured
        return bool(configured)
    except Exception:
        # The flag could not be read. Deny.
        return False


def order_source_allowed(strategy: Optional[str]) -> Tuple[bool, str]:
    """
    Whether an order attributed to `strategy` may be submitted.

    Returns (allowed, reason). `strategy=None` is DENIED: a caller that does not
    identify itself is, by construction, one that predates this check, and those
    are exactly the callers the lock exists to stop.
    """
    if strategy == STRATEGY_SILVER_BULLET:
        return True, "ok"

    if strategy in RETIRED_STRATEGIES:
        if legacy_entries_enabled():
            return True, f"{strategy} entries explicitly enabled"
        return False, (f"{strategy} is retired — Silver Bullet is the only "
                       f"strategy permitted to submit orders")

    return False, (f"unidentified order source {strategy!r} — refusing; only "
                   f"{STRATEGY_SILVER_BULLET} may submit orders")


def refuse_order(strategy: Optional[str], symbol: str = "?",
                 venue: str = "?") -> dict:
    """
    The standard refusal payload, so every adapter refuses identically.

    Returned rather than raised: the callers are job functions whose contract is
    a result dict, and raising would take down a scheduler tick for what is a
    routine, expected refusal.
    """
    allowed, why = order_source_allowed(strategy)
    if allowed:                     # pragma: no cover - caller misuse
        return {"success": False, "error": "not a refusal"}
    logger.warning(f"[{venue}] order REFUSED for {symbol}: {why}")
    return {"success": False, "error": f"entry blocked: {why}",
            "blocked": True, "strategy": strategy}
