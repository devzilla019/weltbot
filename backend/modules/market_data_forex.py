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


# ── Session ───────────────────────────────────────────────────────────────────

class CapitalSession:
    """
    Manages the Capital.com session (CST + X-SECURITY-TOKEN).
    Auto-renews after 9 minutes of inactivity (session expires at 10 min).
    """

    def __init__(self):
        self.cst: Optional[str] = None
        self.security_token: Optional[str] = None
        self.last_login: float = 0.0
        self._lock = threading.Lock()

    def _configured(self) -> bool:
        from config import CAPITAL_API_KEY, CAPITAL_EMAIL, CAPITAL_PASSWORD
        return bool(CAPITAL_API_KEY and CAPITAL_EMAIL and CAPITAL_PASSWORD)

    def login(self) -> bool:
        """Authenticate and store CST + X-SECURITY-TOKEN."""
        global _last_error
        from config import CAPITAL_API_KEY, CAPITAL_EMAIL, CAPITAL_PASSWORD, CAPITAL_BASE_URL

        if not self._configured():
            _last_error = "Capital.com not configured (CAPITAL_API_KEY / EMAIL / PASSWORD)"
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
                _last_error = f"login HTTP {resp.status_code}: {resp.text[:200]}"
                logger.error(f"[capital] login failed: {_last_error}")
                return False

            self.cst = resp.headers.get("CST")
            self.security_token = resp.headers.get("X-SECURITY-TOKEN")
            if not self.cst or not self.security_token:
                _last_error = "login succeeded but tokens missing in response headers"
                logger.error(f"[capital] {_last_error}")
                return False

            self.last_login = time.time()
            _last_error = None
            logger.info("[capital] session established")
            return True

        except Exception as e:
            _last_error = str(e)
            logger.error(f"[capital] login error: {e}")
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
    """Force a fresh login."""
    _session.cst = None
    _session.security_token = None
    _session.login()


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

        rows = []
        for p in prices:
            try:
                rows.append({
                    "timestamp": p["snapshotTime"],
                    "open":  float(p["openPrice"]["mid"]),
                    "high":  float(p["highPrice"]["mid"]),
                    "low":   float(p["lowPrice"]["mid"]),
                    "close": float(p["closePrice"]["mid"]),
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
        bid = float(snap.get("bid", 0) or 0)
        offer = float(snap.get("offer", 0) or 0)
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
                bid = float(market.get("bid", 0) or 0)
                offer = float(market.get("offer", 0) or 0)
                current = (bid + offer) / 2 if (bid and offer) else (bid or offer or 0.0)
                out.append({
                    "id":             pos.get("dealId"),
                    "symbol":         from_epic(market.get("epic", "")),
                    "epic":           market.get("epic"),
                    "signal":         direction,
                    "size":           float(pos.get("size", 0) or 0),
                    "entry_price":    float(pos.get("openLevel", 0) or 0),
                    "current_price":  current,
                    "unrealized_pnl": float(pos.get("upl", 0) or 0),
                    "sl":             float(pos["stopLevel"]) if pos.get("stopLevel") else None,
                    "tp":             float(pos["limitLevel"]) if pos.get("limitLevel") else None,
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
        balance = float(a.get("balance", 0) or 0)
        profit_loss = float(a.get("profitLoss", 0) or 0)
        deposit = float(a.get("deposit", 0) or 0)
        return {
            "balance":     balance,
            "profit_loss": profit_loss,
            "deposit":     deposit,
            "available":   float(a.get("available", balance) or balance),
            "currency":    a.get("currency", "USD"),
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

    bal = get_capital_balance()
    if bal.get("connected"):
        report["connected"] = True
        report["account"] = bal
    else:
        report["error"] = _last_error or "Could not read account balance"
        return report

    for sym in ("EURUSD", "XAUUSD"):
        df = get_candles(sym, timeframe="1h", limit=5)
        if df is not None and len(df) > 0:
            report["symbols_ok"].append(sym)
        else:
            report["symbols_failed"].append(sym)

    return report
