"""
WeltBot News Monitor v1.0
Sources:
  - ForexFactory economic calendar (high-impact events)
  - Twitter/X accounts: @Deltaone, @unusual_whale, @financialjuice
  - CryptoPanic API (free crypto news)

Behavior:
  - HIGH IMPACT event upcoming → pause new trades for 15 min before + 5 min after
  - Extreme bearish news → close longs, switch to SELL bias
  - Extreme bullish news → close shorts, switch to BUY bias
"""

import requests
import time
from datetime import datetime, timedelta, timezone

_news_cache = {"events": [], "last_fetch": 0, "blackout": False, "blackout_until": None}
_twitter_sentiment = {"bias": "neutral", "last_update": 0, "latest_post": ""}


def check_news_blackout() -> dict:
    """
    Returns whether we are in a news blackout period.
    Fetches ForexFactory calendar every 30 minutes.
    """
    now = time.time()
    if now - _news_cache["last_fetch"] > 1800:
        _fetch_forex_factory()

    if _news_cache["blackout_until"]:
        if datetime.now(timezone.utc) < _news_cache["blackout_until"]:
            remaining = (_news_cache["blackout_until"] - datetime.now(timezone.utc)).seconds
            return {
                "blackout": True,
                "reason":   f"High-impact event — resuming in {remaining}s",
                "until":    _news_cache["blackout_until"].isoformat(),
            }
        else:
            _news_cache["blackout"] = False
            _news_cache["blackout_until"] = None

    return {"blackout": False, "reason": None}


def _fetch_forex_factory():
    """Fetch ForexFactory calendar for high-impact USD events."""
    try:
        today = datetime.now(timezone.utc).strftime("%b%d.%Y").lower()
        resp  = requests.get(
            "https://nfs.faireconomy.media/ff_calendar_thisweek.json",
            timeout=10,
            headers={"User-Agent": "Mozilla/5.0"},
        )
        if resp.status_code != 200:
            return

        events = resp.json()
        high_impact = [
            e for e in events
            if e.get("impact") == "High"
            and e.get("currency") in ("USD", "BTC")
        ]

        now = datetime.now(timezone.utc)
        for event in high_impact:
            try:
                event_time_str = event.get("date", "")
                if not event_time_str:
                    continue
                event_time = datetime.fromisoformat(event_time_str.replace("Z", "+00:00"))
                window_start = event_time - timedelta(minutes=15)
                window_end   = event_time + timedelta(minutes=10)

                if window_start <= now <= window_end:
                    _news_cache["blackout"]       = True
                    _news_cache["blackout_until"] = window_end
                    print(f"[news] BLACKOUT — {event.get('title')} at {event_time_str}")
                    break
            except Exception:
                continue

        _news_cache["last_fetch"] = time.time()
        print(f"[news] Calendar fetched — {len(high_impact)} high-impact events this week")

    except Exception as e:
        print(f"[news] ForexFactory fetch error: {e}")


def get_twitter_sentiment(twitter_bearer_token: str = None) -> dict:
    """
    Fetches latest posts from @Deltaone, @unusual_whale, @financialjuice
    and parses for market sentiment.
    Returns: bullish / bearish / neutral + confidence boost amount
    """
    if not twitter_bearer_token:
        return {"bias": "neutral", "boost": 0, "source": None}

    accounts = ["Deltaone", "unusual_whale", "financialjuice"]
    bearish_keywords = [
        "crash", "dump", "sell", "bearish", "warning", "collapse",
        "liquidation", "ban", "hack", "fraud", "regulation", "restrict",
        "🔴", "⚠", "❗", "📉",
    ]
    bullish_keywords = [
        "pump", "rally", "buy", "bullish", "breakout", "surge",
        "moon", "all-time high", "ath", "accumulate", "institutional",
        "🟢", "📈", "🚀",
    ]

    bull_score = 0
    bear_score = 0
    latest     = []

    for account in accounts:
        try:
            resp = requests.get(
                f"https://api.twitter.com/2/tweets/search/recent",
                params={
                    "query":       f"from:{account}",
                    "max_results": 5,
                    "tweet.fields": "created_at,text",
                },
                headers={"Authorization": f"Bearer {twitter_bearer_token}"},
                timeout=10,
            )
            if resp.status_code != 200:
                continue

            tweets = resp.json().get("data", [])
            for tweet in tweets:
                text = tweet.get("text", "").lower()
                latest.append(f"@{account}: {text[:80]}")

                for kw in bullish_keywords:
                    if kw.lower() in text:
                        bull_score += 1
                for kw in bearish_keywords:
                    if kw.lower() in text:
                        bear_score += 1

        except Exception as e:
            print(f"[twitter] error fetching @{account}: {e}")

    if bear_score > bull_score + 2:
        bias  = "bearish"
        boost = -5
    elif bull_score > bear_score + 2:
        bias  = "bullish"
        boost = 5
    else:
        bias  = "neutral"
        boost = 0

    return {
        "bias":   bias,
        "boost":  boost,
        "bull":   bull_score,
        "bear":   bear_score,
        "latest": latest[:3],
    }


def get_news_summary() -> dict:
    """Returns current news state for dashboard display."""
    blackout = check_news_blackout()
    return {
        "blackout":   blackout["blackout"],
        "reason":     blackout.get("reason"),
        "twitter":    _twitter_sentiment,
        "next_check": datetime.now(timezone.utc).isoformat(),
    }