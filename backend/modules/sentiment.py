from textblob import TextBlob
import random
import time

FINANCIAL_KEYWORDS = {
    "etf approval":      +0.40,
    "institutional buy": +0.35,
    "short squeeze":     +0.30,
    "earnings beat":     +0.30,
    "upgrade":           +0.20,
    "sec investigation": -0.45,
    "bankruptcy":        -0.50,
    "hack":              -0.40,
    "earnings miss":     -0.35,
    "downgrade":         -0.25,
    "delisted":          -0.60,
}

MOCK_POOL = {
    "BTC-USD": [
        ("Bitcoin surges past key resistance as institutions accumulate", 0),
        ("Crypto market rallies amid positive macro outlook", 1),
        ("Bitcoin ETF inflows hit record high this week", 2),
        ("Bitcoin dips as profit-taking hits market", 8),
        ("Regulatory clarity boosts crypto confidence", 4),
    ],
    "ETH-USD": [
        ("Ethereum network activity reaches all-time high", 0),
        ("ETH staking rewards attract long-term holders", 3),
        ("Layer 2 adoption drives Ethereum demand", 6),
        ("Ethereum faces selling pressure ahead of upgrade", 10),
    ],
    "AAPL": [
        ("Apple reports record revenue driven by services", 1),
        ("iPhone demand softens in key markets", 5),
        ("Apple AI features to launch this quarter", 2),
        ("Apple faces antitrust probe in EU", 8),
    ],
    "MSFT": [
        ("Microsoft cloud growth beats expectations", 0),
        ("Azure AI revenue doubles year over year", 2),
        ("Microsoft faces antitrust scrutiny over acquisition", 12),
    ],
    "NVDA": [
        ("NVIDIA data center sales shatter records", 0),
        ("GPU demand continues to outstrip supply", 3),
        ("NVIDIA guidance raises Wall Street targets", 1),
        ("NVIDIA faces export control restrictions", 6),
    ],
}

_cache = {}

def _apply_keyword_boost(text, base):
    boost = 0.0
    lower = text.lower()
    for kw, weight in FINANCIAL_KEYWORDS.items():
        if kw in lower:
            boost += weight
    return max(-1.0, min(1.0, base + boost * 0.5))

def _recency_weight(hours_ago):
    if hours_ago <= 2:
        return 1.0
    if hours_ago <= 12:
        return 0.6
    return 0.3

def get_sentiment(symbol, ttl_seconds=300):
    now = time.time()
    if symbol in _cache and (now - _cache[symbol]["ts"]) < ttl_seconds:
        return _cache[symbol]["data"]
    pool      = MOCK_POOL.get(symbol, [("Market conditions remain mixed", 4)])
    headlines = random.sample(pool, min(4, len(pool)))
    weighted_sum = 0.0
    weight_total = 0.0
    for text, hours_ago in headlines:
        base    = TextBlob(text).sentiment.polarity
        boosted = _apply_keyword_boost(text, base)
        w       = _recency_weight(hours_ago)
        weighted_sum += boosted * w
        weight_total += w
    avg   = weighted_sum / weight_total if weight_total > 0 else 0.0
    label = "bullish" if avg > 0.10 else ("bearish" if avg < -0.10 else "neutral")
    result = {
        "symbol": symbol,
        "score":  round(avg, 4),
        "label":  label,
        "count":  len(headlines),
        "sample": [h[0] for h in headlines[:2]],
    }
    _cache[symbol] = {"ts": now, "data": result}
    return result