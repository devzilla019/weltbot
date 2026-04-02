from config import BUY_THRESHOLD, SELL_THRESHOLD
from modules.market_data import get_market_snapshot
from modules.sentiment   import get_sentiment
from modules.onchain     import get_onchain

WEIGHTS = {
    "rsi":       0.20,
    "macd":      0.20,
    "trend":     0.20,
    "sentiment": 0.20,
    "volume":    0.10,
    "onchain":   0.10,
}

def compute_signal(symbol, learned_bias=0.0):
    market    = get_market_snapshot(symbol)
    sentiment = get_sentiment(symbol)
    onchain   = get_onchain(symbol)
    if "error" in market:
        return {"error": market["error"], "symbol": symbol}
    sub_scores = {
        "rsi":       market["rsi_score"],
        "macd":      market["macd_score"],
        "trend":     market["trend"]["score"],
        "sentiment": sentiment["score"],
        "volume":    market["volume"]["score"],
        "onchain":   onchain["score"],
    }
    raw_score  = sum(sub_scores[k] * WEIGHTS[k] for k in WEIGHTS)
    raw_score  = max(-1.0, min(1.0, raw_score + learned_bias * 0.1))
    confidence = round(min(95.0, abs(raw_score) * 100), 1)
    if raw_score >= BUY_THRESHOLD:
        signal = "BUY"
    elif raw_score <= SELL_THRESHOLD:
        signal = "SELL"
    else:
        signal = "HOLD"
    reasoning = []
    for factor, score in sub_scores.items():
        if abs(score) >= 0.3:
            direction = "bullish" if score > 0 else "bearish"
            reasoning.append(f"{factor.upper()} {direction} ({score:+.2f})")
    if not reasoning:
        reasoning = ["Signals mixed — insufficient conviction"]
    return {
        "symbol":     symbol,
        "signal":     signal,
        "confidence": confidence,
        "raw_score":  round(raw_score, 4),
        "sub_scores": sub_scores,
        "reasoning":  reasoning,
        "market":     market,
        "sentiment":  sentiment,
        "onchain":    onchain,
    }