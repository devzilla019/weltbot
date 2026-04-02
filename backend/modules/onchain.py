import random

def get_onchain(symbol):
    is_crypto  = symbol in ["BTC-USD", "ETH-USD"]
    whale_prob = 0.22 if is_crypto else 0.08
    detected   = random.random() < whale_prob
    direction  = random.choice(["accumulation", "distribution"]) if detected else "none"
    size_usd   = random.randint(5_000_000, 150_000_000) if detected else 0
    if not detected:
        score = 0.0
    elif direction == "accumulation":
        score = round(random.uniform(0.3, 1.0), 3)
    else:
        score = round(random.uniform(-1.0, -0.3), 3)
    return {
        "symbol":    symbol,
        "detected":  detected,
        "direction": direction,
        "size_usd":  size_usd,
        "score":     score,
    }