"""
backend/modules/market_data_forex.py
Capital.com REST API market data for Forex/Metals.

Pure synchronous — Capital.com is a session-based REST API.
A single CapitalSession handles login + auto-renewal (10 min expiry).
All functions fail gracefully (return None / empty list) on any error.
"""
import logging
import threading
import time
from datetime import datetime
from typing import Optional, List, Dict

import pandas as pd
import requests

logger = logging.getLogger(__name__)

# ── Resolution mapping (bot format -> Capital.com resolution) ─────────────────
_RES_MAP = {
    "1m": "MINUTE", "5m": "MINUTE_5", "15m": "MINUTE_15", "30m": "MINUTE_30",
    "1h": "HOUR", "4h": "HOUR_4", "1d": "DAY", "1w": "WEEK",
    # already-Capital formats pass through
    "MINUTE": "MINUTE", "MINUTE_5": "MINUTE_5", "MINUTE_15": "MINUTE_15",
    "MINUTE_30": "MINUTE_30", "HOUR": "HOUR", "HOUR_4": "HOUR_4",
    "DAY": "DAY", "WEEK": "WEEK",
}

_last_error: Optional[str] = None


def get_last_error() -> Optional[str]:
    return _last_error


def _num(v, default: float = 0.0) -> float:
    """Coerce a value to float, tolerating None / dict / str.

    Capital.com sometimes nests values, e.g.
      balance = {"balance": 10000, "deposit": 10000, "profitLoss": 0}
    """
    if v is None:
        return default
    if isinstance(v, dict):
        for key in ("balance", "amount", "value", "mid", "lastTraded"):
            if key in v:
                return _num(v[key], default)
        return default
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


# ── Session ───────────────────────────────────────────────────────────────────

class CapitalSession:
    """
    Manages the Capital.com session (CST + X-SECURITY-TOKEN).
    Auto-renews after 9 minutes of inactivity (session expires at 10 min).
    """

    # Backoff schedule (seconds) applied after consecutive login failures.
    # Prevents hammering Capital.com and tripping the 429 rate limiter.
    _BACKOFF = [30, 60, 120, 300, 600]

    def __init__(self):
        self.cst: Optional[str] = None
        self.security_token: Optional[str] = None
        self.last_login: float = 0.0
        self._lock = threading.Lock()
        self._fail_count: int = 0
        self._next_attempt: float = 0.0
        self._last_login_error: Optional[str] = None

    def _configured(self) -> bool:
        from config import CAPITAL_API_KEY, CAPITAL_EMAIL, CAPITAL_PASSWORD
        return bool(CAPITAL_API_KEY and CAPITAL_EMAIL and CAPITAL_PASSWORD)

    def _backoff_remaining(self) -> float:
        return max(0.0, self._next_attempt - time.time())

    def login(self, force: bool = False) -> bool:
        """Authenticate and store CST + X-SECURITY-TOKEN (with backoff on failure)."""
        global _last_error
        from config import CAPITAL_API_KEY, CAPITAL_EMAIL, CAPITAL_PASSWORD, CAPITAL_BASE_URL

        if not self._configured():
            _last_error = "Capital.com not configured (CAPITAL_API_KEY / EMAIL / PASSWORD)"
            return False

        # Respect the backoff window unless explicitly forced
        if not force:
            remaining = self._backoff_remaining()
            if remaining > 0:
                _last_error = (f"login backoff active ({remaining:.0f}s) — "
                               f"last error: {self._last_login_error}")
                return False

        try:
            url = f"{CAPITAL_BASE_URL}/api/v1/session"
            headers = {"X-CAP-API-KEY": CAPITAL_API_KEY, "Content-Type": "application/json"}
            body = {
                "identifier": CAPITAL_EMAIL,
                "password": CAPITAL_PASSWORD,
                "encryptionEnabled": False,
            }
            resp = requests.post(url, headers=headers, json=body, timeout=20)

            if resp.status_code not in (200, 201):
                detail = resp.text[:200]
                # Friendly hints for the common Capital.com errors
                if "error.null.accountId" in detail:
                    hint = ("Capital.com returned error.null.accountId — the API key is not "
                            "linked to a demo account. Create the API key from the DEMO "
                            "account (capital.com demo dashboard → Settings → API integrations), "
                            "and make sure CAPITAL_DEMO=true.")
                elif "error.too-many.requests" in detail or resp.status_code == 429:
                    hint = ("Capital.com rate limit hit (429). Backing off — this usually "
                            "clears within a few minutes.")
                elif resp.status_code == 401:
                    hint = ("Capital.com rejected the credentials (401). Check CAPITAL_EMAIL "
                            "and CAPITAL_PASSWORD are your Capital.com login, and that 2FA "
                            "is enabled on the account.")
                else:
                    hint = detail

                self._last_login_error = f"HTTP {resp.status_code}: {detail}"
                _last_error = f"login HTTP {resp.status_code}: {detail} — {hint}"
                self._fail_count += 1
                wait = self._BACKOFF[min(self._fail_count - 1, len(self._BACKOFF) - 1)]
                self._next_attempt = time.time() + wait
                logger.error(f"[capital] login failed ({self._fail_count}): {_last_error} "
                             f"— retrying in {wait}s")
                return False

            self.cst = resp.headers.get("CST")
            self.security_token = resp.headers.get("X-SECURITY-TOKEN")
            if not self.cst or not self.security_token:
                _last_error = "login succeeded but tokens missing in response headers"
                self._fail_count += 1
                self._next_attempt = time.time() + 60
                logger.error(f"[capital] {_last_error}")
                return False

            self.last_login = time.time()
            self._fail_count = 0
            self._next_attempt = 0.0
            self._last_login_error = None
            _last_error = None
            logger.info("[capital] session established")
            return True

        except Exception as e:
            _last_error = str(e)
            self._fail_count += 1
            wait = self._BACKOFF[min(self._fail_count - 1, len(self._BACKOFF) - 1)]
            self._next_attempt = time.time() + wait
            logger.error(f"[capital] login error: {e} — retrying in {wait}s")
            return False

    def _ensure_session(self) -> bool:
        """Re-login if the session is missing or older than 9 minutes."""
        with self._lock:
            if not self.cst or not self.security_token:
                return self.login()
            if (time.time() - self.last_login) > 540:   # 9 minutes
                logger.info("[capital] session expiring — renewing")
                return self.login()
            return True

    def _auth_headers(self) -> Dict[str, str]:
        from config import CAPITAL_API_KEY
        return {
            "X-CAP-API-KEY": CAPITAL_API_KEY,
            "CST": self.cst or "",
            "X-SECURITY-TOKEN": self.security_token or "",
            "Content-Type": "application/json",
        }

    def get(self, path: str, params: Optional[dict] = None) -> Optional[requests.Response]:
        global _last_error
        if not self._ensure_session():
            return None
        from config import CAPITAL_BASE_URL
        try:
            resp = requests.get(f"{CAPITAL_BASE_URL}{path}", headers=self._auth_headers(),
                                params=params, timeout=20)
            if resp.status_code == 401:
                # token expired mid-flight — re-login once and retry
                if self.login():
                    resp = requests.get(f"{CAPITAL_BASE_URL}{path}", headers=self._auth_headers(),
                                        params=params, timeout=20)
            if resp.status_code not in (200, 201):
                _last_error = f"HTTP {resp.status_code}: {resp.text[:200]}"
                logger.error(f"[capital] GET {path}: {_last_error}")
                return None
            _last_error = None
            return resp
        except Exception as e:
            _last_error = str(e)
            logger.error(f"[capital] GET {path} error: {e}")
            return None

    def post(self, path: str, body: dict) -> Optional[requests.Response]:
        global _last_error
        if not self._ensure_session():
            return None
        from config import CAPITAL_BASE_URL
        try:
            resp = requests.post(f"{CAPITAL_BASE_URL}{path}", headers=self._auth_headers(),
                                 json=body, timeout=20)
            if resp.status_code == 401:
                if self.login():
                    resp = requests.post(f"{CAPITAL_BASE_URL}{path}", headers=self._auth_headers(),
                                         json=body, timeout=20)
            if resp.status_code not in (200, 201):
                _last_error = f"HTTP {resp.status_code}: {resp.text[:200]}"
                logger.error(f"[capital] POST {path}: {_last_error}")
                return None
            _last_error = None
            return resp
        except Exception as e:
            _last_error = str(e)
            logger.error(f"[capital] POST {path} error: {e}")
            return None

    def delete(self, path: str) -> Optional[requests.Response]:
        global _last_error
        if not self._ensure_session():
            return None
        from config import CAPITAL_BASE_URL
        try:
            resp = requests.delete(f"{CAPITAL_BASE_URL}{path}", headers=self._auth_headers(), timeout=20)
            if resp.status_code == 401:
                if self.login():
                    resp = requests.delete(f"{CAPITAL_BASE_URL}{path}", headers=self._auth_headers(), timeout=20)
            if resp.status_code not in (200, 201):
                _last_error = f"HTTP {resp.status_code}: {resp.text[:200]}"
                logger.error(f"[capital] DELETE {path}: {_last_error}")
                return None
            _last_error = None
            return resp
        except Exception as e:
            _last_error = str(e)
            logger.error(f"[capital] DELETE {path} error: {e}")
            return None


_session = CapitalSession()


def get_session() -> CapitalSession:
    return _session


def reconnect() -> None:
    """Force a fresh login (bypasses backoff)."""
    _session.cst = None
    _session.security_token = None
    _session.login(force=True)


def session_status() -> Dict:
    """Diagnostic info about the Capital.com session (for the UI)."""
    return {
        "authenticated": bool(_session.cst and _session.security_token),
        "fail_count": _session._fail_count,
        "backoff_remaining": round(_session._backoff_remaining(), 1),
        "last_error": _session._last_login_error,
    }


# ── Candles ───────────────────────────────────────────────────────────────────

def get_candles(symbol: str, timeframe: str = "1h", limit: int = 400) -> Optional[pd.DataFrame]:
    """
    Fetch OHLCV candles from Capital.com.
    Returns DataFrame: timestamp, open, high, low, close, volume
    """
    from config import to_epic
    epic = to_epic(symbol)
    resolution = _RES_MAP.get(timeframe, "HOUR")

    resp = _session.get(f"/api/v1/prices/{epic}",
                        params={"resolution": resolution, "max": min(int(limit), 1000)})
    if resp is None:
        return None

    try:
        prices = resp.json().get("prices", [])
        if not prices:
            logger.warning(f"[capital] no candles for {epic} {resolution}")
            return None

        def _mid(node) -> float:
            """Capital.com price node: {"bid": x, "ask": y, "lastTraded": z}."""
            if isinstance(node, dict):
                for key in ("mid", "lastTraded", "bid", "ask"):
                    if node.get(key) is not None:
                        return _num(node[key])
                return 0.0
            return _num(node)

        rows = []
        for p in prices:
            try:
                rows.append({
                    "timestamp": p["snapshotTime"],
                    "open":  _mid(p.get("openPrice")),
                    "high":  _mid(p.get("highPrice")),
                    "low":   _mid(p.get("lowPrice")),
                    "close": _mid(p.get("closePrice")),
                    "volume": 0,
                })
            except (KeyError, TypeError, ValueError):
                continue

        if not rows:
            return None

        df = pd.DataFrame(rows)
        df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce")
        df = df.dropna(subset=["timestamp"]).sort_values("timestamp").reset_index(drop=True)
        return df

    except Exception as e:
        logger.error(f"[capital] candle parse error {epic}: {e}")
        return None


# ── Current price ─────────────────────────────────────────────────────────────

def get_current_price(symbol: str) -> float:
    """Return midpoint of bid/offer. 0.0 on error."""
    from config import to_epic
    epic = to_epic(symbol)

    resp = _session.get(f"/api/v1/markets/{epic}")
    if resp is None:
        return 0.0

    try:
        snap = resp.json().get("snapshot", {})
        bid = _num(snap.get("bid"))
        offer = _num(snap.get("offer"))
        if bid and offer:
            return (bid + offer) / 2
        return bid or offer or 0.0
    except Exception as e:
        logger.error(f"[capital] price parse error {epic}: {e}")
        return 0.0


# ── Open positions ────────────────────────────────────────────────────────────

def get_open_positions() -> List[Dict]:
    """
    Fetch open positions.
    Returns: id, symbol, signal, size, entry_price, current_price,
             unrealized_pnl, sl, tp
    """
    from config import from_epic

    resp = _session.get("/api/v1/positions")
    if resp is None:
        return []

    try:
        positions = resp.json().get("positions", [])
        out = []
        for item in positions:
            try:
                pos = item.get("position", {})
                market = item.get("market", {})
                direction = pos.get("direction", "BUY")
                bid = _num(market.get("bid"))
                offer = _num(market.get("offer"))
                current = (bid + offer) / 2 if (bid and offer) else (bid or offer or 0.0)
                sl = _num(pos.get("stopLevel")) if pos.get("stopLevel") else None
                tp = _num(pos.get("limitLevel")) if pos.get("limitLevel") else None
                out.append({
                    "id":             pos.get("dealId"),
                    "symbol":         from_epic(market.get("epic", "")),
                    "epic":           market.get("epic"),
                    "signal":         direction,
                    "size":           _num(pos.get("size")),
                    "entry_price":    _num(pos.get("openLevel")),
                    "current_price":  current,
                    "unrealized_pnl": _num(pos.get("upl")),
                    "sl":             sl,
                    "tp":             tp,
                    "open_time":      pos.get("createdDateUTC"),
                })
            except Exception as e:
                logger.warning(f"[capital] position parse error: {e}")
                continue
        return out

    except Exception as e:
        logger.error(f"[capital] positions parse error: {e}")
        return []


# ── Account balance ───────────────────────────────────────────────────────────

def get_capital_balance() -> Dict:
    """
    Fetch account balance.

    Capital.com returns:
      accounts[0].balance = {"balance": 10000, "deposit": 10000,
                             "profitLoss": 0, "available": 10000}
      accounts[0].currency = "USD"

    Returns: {balance, profit_loss, deposit, available, currency, connected}
    """
    empty = {"balance": 0.0, "profit_loss": 0.0, "deposit": 0.0,
             "available": 0.0, "currency": "USD", "connected": False}

    resp = _session.get("/api/v1/accounts")
    if resp is None:
        return empty

    try:
        accounts = resp.json().get("accounts", [])
        if not accounts:
            return empty

        a = accounts[0]
        raw = a.get("balance", {})

        # `balance` may be a nested dict OR a flat number
        if isinstance(raw, dict):
            balance     = _num(raw.get("balance"))
            deposit     = _num(raw.get("deposit"))
            profit_loss = _num(raw.get("profitLoss"))
            available   = _num(raw.get("available"), balance)
        else:
            balance     = _num(raw)
            deposit     = _num(a.get("deposit"))
            profit_loss = _num(a.get("profitLoss"))
            available   = _num(a.get("available"), balance)

        return {
            "balance":     balance,
            "profit_loss": profit_loss,
            "deposit":     deposit,
            "available":   available,
            "currency":    a.get("currency", "USD"),
            "account_id":  a.get("accountId"),
            "account_name": a.get("accountName"),
            "connected":   True,
        }
    except Exception as e:
        logger.error(f"[capital] balance parse error: {e}")
        return empty


# ── Order placement ───────────────────────────────────────────────────────────

def place_order(symbol: str, signal: str, size: float, sl: float, tp: float) -> Dict:
    """
    Open a position on Capital.com.
    Returns: {success, deal_id, fill_price, error}
    """
    from config import to_epic
    epic = to_epic(symbol)

    body = {
        "epic": epic,
        "direction": signal,          # BUY / SELL
        "size": round(float(size), 2),
        "guaranteedStop": False,
    }
    if sl:
        body["stopLevel"] = round(float(sl), 5)
    if tp:
        body["profitLevel"] = round(float(tp), 5)

    resp = _session.post("/api/v1/positions", body)
    if resp is None:
        return {"success": False, "error": _last_error or "order request failed"}

    try:
        deal_ref = resp.json().get("dealReference")
        if not deal_ref:
            return {"success": False, "error": "no dealReference returned"}

        # Confirm the deal to get the fill price + dealId
        confirm = _session.get(f"/api/v1/confirms/{deal_ref}")
        if confirm is None:
            return {"success": False, "error": "order placed but confirm failed",
                    "deal_reference": deal_ref}

        c = confirm.json()
        status = c.get("status", "")
        if status not in ("ACCEPTED", "OPEN", "EXECUTED"):
            return {"success": False, "error": f"deal status={status}",
                    "deal_reference": deal_ref}

        deal_id = c.get("dealId")
        fill = float(c.get("level", 0) or 0)
        logger.info(f"[capital] order filled — {signal} {epic} size={size} @ {fill}")
        return {
            "success": True,
            "deal_id": deal_id,
            "fill_price": fill,
            "deal_reference": deal_ref,
        }

    except Exception as e:
        logger.error(f"[capital] order confirm error {epic}: {e}")
        return {"success": False, "error": str(e)}


# ── Close position ────────────────────────────────────────────────────────────

def close_position(deal_id: str) -> Dict:
    """Close an open position by dealId. Returns {success, error}."""
    resp = _session.delete(f"/api/v1/positions/{deal_id}")
    if resp is None:
        return {"success": False, "error": _last_error or "close request failed"}
    logger.info(f"[capital] position closed — dealId={deal_id}")
    return {"success": True}


# ── Compatibility shims ───────────────────────────────────────────────────────

def get_account_info() -> Optional[Dict]:
    """Alias for get_capital_balance() with legacy field names."""
    b = get_capital_balance()
    if not b.get("connected"):
        return None
    return {
        "balance":     b["balance"],
        "equity":      b["balance"] + b["profit_loss"],
        "margin":      0.0,
        "free_margin": b["available"],
        "currency":    b["currency"],
        "leverage":    0,
        "profit":      b["profit_loss"],
    }


# ── Health check (Test Connection button) ─────────────────────────────────────

def test_connection() -> Dict:
    """Full connectivity test used by /api/forex/test-connection."""
    from config import CAPITAL_API_KEY, CAPITAL_EMAIL, CAPITAL_PASSWORD, CAPITAL_DEMO, FOREX_ENABLED

    report = {
        "provider": "capital.com",
        "environment": "demo" if CAPITAL_DEMO else "live",
        "forex_enabled": FOREX_ENABLED,
        "api_key_set": bool(CAPITAL_API_KEY),
        "email_set": bool(CAPITAL_EMAIL),
        "password_set": bool(CAPITAL_PASSWORD),
        "connected": False,
        "account": None,
        "symbols_ok": [],
        "symbols_failed": [],
        "error": None,
    }

    if not FOREX_ENABLED:
        report["error"] = "FOREX_ENABLED is false — set it to true on Railway"
        return report
    if not (CAPITAL_API_KEY and CAPITAL_EMAIL and CAPITAL_PASSWORD):
        report["error"] = "CAPITAL_API_KEY / CAPITAL_EMAIL / CAPITAL_PASSWORD missing"
        return report

    # Force a fresh login attempt so the button always gives a real answer
    _session.cst = None
    _session.security_token = None
    _session.login(force=True)

    bal = get_capital_balance()
    if bal.get("connected"):
        report["connected"] = True
        report["account"] = bal
    else:
        report["error"] = _last_error or "Could not read account balance"
        report["session"] = session_status()
        return report

    for sym in ("EURUSD", "XAUUSD"):
        df = get_candles(sym, timeframe="1h", limit=5)
        if df is not None and len(df) > 0:
            report["symbols_ok"].append(sym)
        else:
            report["symbols_failed"].append(sym)

    return report
