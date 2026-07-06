"""
backend/modules/risk_manager.py
AGGRESSIVE COMPOUNDING VERSION
- Kelly Criterion position sizing
- Full compound growth (uses updated balance every trade)
- Dynamic risk % based on confidence and win streak
- Scales aggressively on high-confidence setups
"""

import os
from config import (
    MAX_RISK_PCT,
    DEFAULT_PORTFOLIO,
    LEVERAGE_TIERS,
    HIGH_LEV_ASSETS,
    MIN_CONFIDENCE,
)

# ── Kelly Criterion ────────────────────────────────────────────────────────────
# Kelly % = W - (L/R)
# W = win rate, L = loss rate, R = reward/risk ratio
# We use fractional Kelly (50%) for safety

def kelly_fraction(win_rate: float, avg_rr: float) -> float:
    """
    Full Kelly = win_rate - (loss_rate / avg_rr)
    We use 55% Kelly for aggressive but controlled growth.
    """
    if avg_rr <= 0 or win_rate <= 0:
        return 0.01
    loss_rate = 1.0 - win_rate
    full_kelly = win_rate - (loss_rate / avg_rr)
    # Cap at 55% Kelly — aggressive but not reckless
    fractional = full_kelly * 0.55
    # Hard bounds: min 1%, max 8% per trade
    return max(0.01, min(0.08, fractional))


def get_dynamic_risk_pct(confidence: float, win_rate: float = 0.50, avg_rr: float = 2.95) -> float:
    """
    Dynamic risk % based on:
    1. Kelly Criterion (current win rate + R:R)
    2. Confidence score boost
    3. Hard caps for safety
    """
    base_kelly = kelly_fraction(win_rate, avg_rr)

    # Confidence multiplier — higher confidence = more risk
    if confidence >= 98:
        conf_mult = 2.0    # 2x Kelly for extreme conviction
    elif confidence >= 95:
        conf_mult = 1.6    # 1.6x
    elif confidence >= 90:
        conf_mult = 1.3    # 1.3x
    else:
        conf_mult = 1.0    # base Kelly

    risk = base_kelly * conf_mult

    # Hard caps
    risk = max(0.02, min(0.10, risk))  # 2% min, 10% max

    return round(risk, 4)


def get_leverage(confidence: float, symbol: str) -> int:
    """Dynamic leverage based on confidence tier."""
    if confidence >= 98 and symbol in HIGH_LEV_ASSETS:
        return 100
    elif confidence >= 95:
        return 50
    elif confidence >= 90:
        return 20
    elif confidence >= 85:
        return 10
    return 10


def calculate_risk(
    price: float,
    signal: str,
    confidence: float,
    atr: float,
    balance: float,
    win_rate: float = 0.50,
    avg_rr: float   = 2.95,
    symbol: str     = "",
) -> dict:
    """
    COMPOUNDING POSITION SIZER
    Uses current balance (not fixed default) for every calculation.
    This is the key to 10x growth — profits immediately increase next position.
    """
    if price <= 0 or balance <= 0:
        return _empty_risk()

    # Use actual live balance for compounding
    effective_balance = max(balance, 1.0)

    # Dynamic risk % using Kelly
    risk_pct = get_dynamic_risk_pct(confidence, win_rate, avg_rr)

    # Dollar risk this trade
    risk_usd = effective_balance * risk_pct

    # Stop distance
    if atr > 0:
        stop_pct = (atr * 0.5) / price  # tighter stop = bigger position
    else:
        # Fallback based on confidence (tighter stop for higher confidence)
        if confidence >= 95:
            stop_pct = 0.008   # 0.8%
        elif confidence >= 90:
            stop_pct = 0.012   # 1.2%
        else:
            stop_pct = 0.015   # 1.5%

    stop_pct = max(stop_pct, 0.003)  # never tighter than 0.3%

    # Position size in USD notional
    position_usd = risk_usd / stop_pct

    # Get leverage
    leverage = get_leverage(confidence, symbol)

    # Margin required
    margin_required = position_usd / leverage

    # Cap margin at 40% of balance (safety — never go all-in)
    max_margin = effective_balance * 0.40
    if margin_required > max_margin:
        margin_required = max_margin
        position_usd    = margin_required * leverage
        risk_usd        = position_usd * stop_pct

    # Units
    position_units = position_usd / price if price > 0 else 0

    # R:R
    stop_dist = price * stop_pct
    rr        = avg_rr
    if confidence >= 95:
        rr = 3.0
    elif confidence >= 90:
        rr = 2.5

    if signal == "BUY":
        stop_loss   = round(price - stop_dist, 8)
        take_profit = round(price + stop_dist * rr, 8)
    else:
        stop_loss   = round(price + stop_dist, 8)
        take_profit = round(price - stop_dist * rr, 8)

    return {
        "signal":             signal,
        "position_size_usdt": round(position_usd, 4),
        "position_size_units":round(position_units, 6),
        "stop_loss":          stop_loss,
        "take_profit":        take_profit,
        "risk_usd":           round(risk_usd, 4),
        "risk_pct":           round(risk_pct * 100, 2),
        "risk_reward":        rr,
        "leverage":           leverage,
        "margin_used":        round(margin_required, 4),
        "portfolio_used_pct": round(margin_required / effective_balance * 100, 2),
        "stop_pct":           round(stop_pct * 100, 3),
        "kelly_fraction":     round(risk_pct * 100, 2),
        "balance_used":       round(effective_balance, 2),
    }


def _empty_risk() -> dict:
    return {
        "signal":"HOLD","position_size_usdt":0,"position_size_units":0,
        "stop_loss":None,"take_profit":None,"risk_usd":0,"risk_pct":0,
        "risk_reward":0,"leverage":10,"margin_used":0,"portfolio_used_pct":0,
        "stop_pct":0,"kelly_fraction":0,"balance_used":0,
    }


# ── Compounding tracker ────────────────────────────────────────────────────────

_compound_stats = {
    "trades":   0,
    "wins":     0,
    "losses":   0,
    "peak":     0.0,
    "win_streak": 0,
    "loss_streak": 0,
}

def update_compound_stats(won: bool, pnl: float, balance: float):
    """Call after every closed trade to update Kelly inputs."""
    global _compound_stats
    _compound_stats["trades"] += 1
    _compound_stats["peak"] = max(_compound_stats["peak"], balance)
    if won:
        _compound_stats["wins"]       += 1
        _compound_stats["win_streak"] += 1
        _compound_stats["loss_streak"] = 0
    else:
        _compound_stats["losses"]      += 1
        _compound_stats["loss_streak"] += 1
        _compound_stats["win_streak"]   = 0

def get_live_kelly_inputs() -> tuple[float, float]:
    """
    Return (win_rate, avg_rr) from live trade history.
    Falls back to conservative defaults with few trades.
    """
    t = _compound_stats["trades"]
    w = _compound_stats["wins"]
    if t < 10:
        return 0.50, 2.95   # conservative default until enough data
    win_rate = w / t
    # Clamp win rate — never let Kelly go crazy
    win_rate = max(0.35, min(0.75, win_rate))
    return win_rate, 2.95   # keep R:R fixed at 2.95 (from your data)

def get_drawdown_guard(balance: float) -> float:
    """
    Reduce risk if in drawdown to protect capital.
    Returns a multiplier (1.0 = full, 0.5 = half size).
    """
    peak = _compound_stats["peak"] or balance
    dd   = (peak - balance) / peak if peak > 0 else 0
    loss_streak = _compound_stats["loss_streak"]

    if dd > 0.15 or loss_streak >= 4:
        return 0.25   # 25% of normal risk — capital protection mode
    elif dd > 0.10 or loss_streak >= 3:
        return 0.50   # 50% of normal
    elif dd > 0.05 or loss_streak >= 2:
        return 0.75   # 75% of normal
    return 1.0        # full risk


def calculate_risk_with_compounding(
    price: float,
    signal: str,
    confidence: float,
    atr: float,
    balance: float,
    symbol: str = "",
) -> dict:
    """
    Full compounding version — uses live win rate from trade history.
    This is what the bot calls for every trade.
    """
    win_rate, avg_rr = get_live_kelly_inputs()
    guard            = get_drawdown_guard(balance)
    result           = calculate_risk(price, signal, confidence, atr, balance, win_rate, avg_rr, symbol)
    # Apply drawdown guard
    if guard < 1.0:
        factor = guard
        result["position_size_usdt"]  *= factor
        result["position_size_units"] *= factor
        result["risk_usd"]            *= factor
        result["margin_used"]         *= factor
        result["portfolio_used_pct"]  *= factor
        result["risk_pct"]            *= factor
        result["kelly_fraction"]      *= factor
    return result
