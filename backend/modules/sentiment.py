from textblob import TextBlob
import requests
import time
import random

FINANCIAL_KEYWORDS = {
    "surge":         +0.30,
    "rally":         +0.25,
    "bullish":       +0.35,
    "adoption":      +0.25,
    "partnership":   +0.20,
    "upgrade":       +0.20,
    "listing":       +0.15,
    "etf":           +0.30,
    "institutional": +0.25,
    "hack":          -0.50,
    "ban":           -0.45,
    "crash":         -0.40,
    "bearish":       -0.35,
    "sec":           -0.30,
    "fraud":         -0.50,
    "bankrupt":      -0.60,
    "dump":          -0.30,
    "sell":          -0.15,
    "fear":          -0.25,
    "warning":       -0.20,
}

# Realistic mock headlines per asset — used as fallback
MOCK_HEADLINES = {
    "BTC": [
        "Bitcoin institutional demand rising as ETF inflows hit record",
        "BTC breaks key resistance level amid positive macro outlook",
        "Bitcoin network hash rate reaches all time high",
        "Whale wallets accumulating BTC at current price levels",
    ],
    "ETH": [
        "Ethereum staking yields continue attracting long term holders",
        "ETH layer 2 transaction volume hits new record",
        "Ethereum developer activity remains strong this quarter",
        "ETH burns accelerate reducing circulating supply",
    ],
    "SOL": [
        "Solana DeFi ecosystem TVL growing rapidly",
        "SOL network uptime improves significantly after upgrades",
        "Solana memecoin activity drives fee revenue higher",
    ],
    "BNB": [
        "BNB chain activity increases with new DeFi protocols",
        "Binance reports strong quarterly trading volumes",
    ],
    "XRP": [
        "XRP legal clarity boosts institutional interest",
        "Ripple partnership expands cross border payment network",
    ],
    "ADA": [
        "Cardano smart contract activity growing steadily",
        "ADA staking participation reaches new high",
    ],
    "AVAX": [
        "Avalanche subnet adoption accelerating across enterprises",
        "AVAX DeFi TVL recovering strongly",
    ],
    "DOGE": [
        "Dogecoin payment adoption growing among merchants",
        "DOGE social sentiment remains elevated",
    ],
    "LINK": [
        "Chainlink oracle network expands to new blockchains",
        "LINK staking v0.2 attracting significant deposits",
    ],
    "UNI": [
        "Uniswap v4 launch drives protocol fee growth",
        "UNI governance vote passes new fee switch proposal",
    ],
}

DEFAULT_HEADLINES = [
    "Crypto market shows mixed signals amid macro uncertainty",
    "Digital asset trading volumes remain steady this week",
    "Blockchain adoption continues across emerging markets",
]

_cache: dict = {}
_TTL = 600  # 10 minutes


def _fetch_alternative_news(symbol_base: str) -> list:
    feeds = [
        "https://cointelegraph.com/rss",
        "https://coindesk.com/arc/outboundfeeds/rss/",
    ]
    headlines = []
    for feed_url in feeds:
        try:
            resp = requests.get(feed_url, timeout=4, headers={"User-Agent": "Mozilla/5.0"})
            if resp.status_code != 200:
                continue
            import re
            titles = re.findall(r"<title><!\[CDATA\[(.*?)\]\]></title>", resp.text)
            if not titles:
                titles = re.findall(r"<title>(.*?)</title>", resp.text)
            sym = symbol_base.upper()
            full = sym if len(sym) > 3 else sym
            for title in titles[:40]:
                t = title.strip()
                if sym in t.upper() or "CRYPTO" in t.upper() or "BITCOIN" in t.upper() and sym == "BTC":
                    headlines.append((t, 1))
            if headlines:
                break
        except Exception:
            continue
    return headlines[:5]

def _apply_keyword_boost(text: str, base: float) -> float:
    boost = 0.0
    lower = text.lower()
    for kw, weight in FINANCIAL_KEYWORDS.items():
        if kw in lower:
            boost += weight
    return max(-1.0, min(1.0, base + boost * 0.4))


def _recency_weight(hours_ago: int) -> float:
    if hours_ago <= 2:  return 1.0
    if hours_ago <= 12: return 0.6
    return 0.3


def get_sentiment(symbol: str) -> dict:
    base = symbol.replace("/USDT", "").replace("-USD", "").upper()
    now  = time.time()

    if base in _cache and (now - _cache[base]["ts"]) < _TTL:
        return _cache[base]["data"]

    # Try real RSS first
    headlines = _fetch_alternative_news(base)

    # Fall back to mock if nothing found
    if not headlines:
        pool      = MOCK_HEADLINES.get(base, DEFAULT_HEADLINES)
        headlines = [(h, random.randint(1, 6)) for h in random.sample(pool, min(3, len(pool)))]

    weighted_sum = 0.0
    weight_total = 0.0

    for text, hours_ago in headlines:
        base_score = TextBlob(text).sentiment.polarity
        boosted    = _apply_keyword_boost(text, base_score)
        w          = _recency_weight(hours_ago)
        weighted_sum += boosted * w
        weight_total += w

    avg   = weighted_sum / weight_total if weight_total > 0 else 0.0
    label = "bullish" if avg > 0.08 else ("bearish" if avg < -0.08 else "neutral")

    result = {
        "symbol": symbol,
        "score":  round(avg, 4),
        "label":  label,
        "count":  len(headlines),
        "source": "rss" if headlines else "mock",
    }
    _cache[base] = {"ts": now, "data": result}
    return result