import math
from config import MAX_RISK_PCT, DEFAULT_PORTFOLIO

def calculate_risk(entry_price, signal, confidence,
                   atr=None, portfolio_value=DEFAULT_PORTFOLIO):
    if entry_price <= 0 or signal == "HOLD":
        return {
            "signal":             "HOLD",
            "position_size":      0,
            "stop_loss":          None,
            "take_profit":        None,
            "risk_usd":           0,
            "risk_reward":        0,
            "portfolio_used_pct": 0,
        }
    stop_dist = atr * 1.5 if atr and atr > 0 else entry_price * 0.02
    stop_pct  = stop_dist / entry_price
    if signal == "BUY":
        stop_loss   = round(entry_price - stop_dist, 6)
        take_profit = round(entry_price + stop_dist * 2.5, 6)
    else:
        stop_loss   = round(entry_price + stop_dist, 6)
        take_profit = round(entry_price - stop_dist * 2.5, 6)
    risk_usd    = portfolio_value * MAX_RISK_PCT
    conf_factor = math.sqrt(confidence / 100)
    position    = (risk_usd * conf_factor) / stop_pct
    position    = round(min(position, portfolio_value * 0.20), 2)
    actual_risk = round(position * stop_pct, 2)
    return {
        "signal":             signal,
        "entry_price":        entry_price,
        "stop_loss":          stop_loss,
        "take_profit":        take_profit,
        "stop_dist":          round(stop_dist, 6),
        "stop_pct":           round(stop_pct * 100, 3),
        "position_size":      position,
        "risk_usd":           actual_risk,
        "risk_pct":           round(actual_risk / portfolio_value * 100, 3),
        "risk_reward":        2.5,
        "portfolio_used_pct": round(position / portfolio_value * 100, 1),
    }