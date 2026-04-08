import math
from config import MAX_RISK_PCT, DEFAULT_PORTFOLIO


def calculate_risk(entry_price, signal, confidence,
                   atr=None, portfolio_value=DEFAULT_PORTFOLIO):
    if entry_price <= 0 or signal == "HOLD":
        return {
            "signal":              "HOLD",
            "position_size_usdt":  0,
            "position_size_units": 0,
            "stop_loss":           None,
            "take_profit":         None,
            "risk_usd":            0,
            "risk_reward":         0,
            "portfolio_used_pct":  0,
            "stop_pct":            0,
            "risk_pct":            0,
        }

    if atr and atr > 0:
        stop_dist = atr * 1.5
    else:
        stop_dist = entry_price * 0.02

    stop_pct  = stop_dist / entry_price
    stop_pct  = min(stop_pct, 0.05)
    stop_dist = stop_pct * entry_price

    if signal == "BUY":
        stop_loss   = round(entry_price - stop_dist, 8)
        take_profit = round(entry_price + stop_dist * 2.0, 8)
    else:
        stop_loss   = round(entry_price + stop_dist, 8)
        take_profit = round(entry_price - stop_dist * 2.0, 8)

    risk_usd      = portfolio_value * MAX_RISK_PCT
    conf_factor   = math.sqrt(max(confidence, 10.0) / 100.0)
    scaled_risk   = risk_usd * conf_factor
    position_usdt = scaled_risk / stop_pct
    position_usdt = min(position_usdt, portfolio_value * 0.15)
    position_usdt = max(position_usdt, 10.0)
    position_usdt = round(position_usdt, 4)

    position_units = round(position_usdt / entry_price, 8)
    actual_risk    = round(position_usdt * stop_pct, 4)

    return {
        "signal":              signal,
        "entry_price":         entry_price,
        "stop_loss":           stop_loss,
        "take_profit":         take_profit,
        "stop_dist":           round(stop_dist, 8),
        "stop_pct":            round(stop_pct * 100, 3),
        "position_size_usdt":  position_usdt,
        "position_size_units": position_units,
        "risk_usd":            actual_risk,
        "risk_pct":            round(actual_risk / portfolio_value * 100, 3),
        "risk_reward":         2.5,
        "portfolio_used_pct":  round(position_usdt / portfolio_value * 100, 1),
    }