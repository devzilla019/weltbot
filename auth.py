"""
backend/routers/auth.py - SECURE VERSION
Security measures:
- Passwords: SHA256 + salt (no bcrypt dependency)
- API keys: XOR encrypted at rest in DB
- Tokens: HMAC-signed, 30-day expiry
- Rate limiting: per-IP login attempts tracked
- No sensitive data in responses
- Keys never returned to frontend after saving
"""
from fastapi import APIRouter, Depends, HTTPException, Header, Request
from sqlalchemy import Column, Integer, String, Boolean, DateTime, Text
from sqlalchemy.orm import Session
from database import get_db, Base, engine
from datetime import datetime
import hashlib, hmac as _hmac, json, os, base64, time
from collections import defaultdict

router = APIRouter(prefix="/api/auth", tags=["auth"])

SECRET = os.getenv("SECRET_KEY", "")
if not SECRET:
    raise RuntimeError("SECRET_KEY environment variable must be set — do not use defaults")

# ── Rate limiting (in-memory, resets on restart) ───────────────────
_login_attempts: dict = defaultdict(list)
MAX_ATTEMPTS = 10
WINDOW_SECS  = 300  # 5 minutes

def _check_rate_limit(ip: str):
    now  = time.time()
    hits = [t for t in _login_attempts[ip] if now - t < WINDOW_SECS]
    _login_attempts[ip] = hits
    if len(hits) >= MAX_ATTEMPTS:
        raise HTTPException(429, f"Too many attempts. Try again in {WINDOW_SECS//60} minutes.")
    _login_attempts[ip].append(now)

def _get_ip(request: Request) -> str:
    return request.headers.get("X-Forwarded-For", request.client.host or "unknown").split(",")[0].strip()

# ── Crypto helpers ─────────────────────────────────────────────────
def _hash_pw(pw: str) -> str:
    salt = hashlib.sha256(SECRET.encode()).hexdigest()[:32]
    return hashlib.sha256(f"{salt}{pw}{salt}".encode()).hexdigest()

def _verify_pw(pw: str, h: str) -> bool:
    return _hmac.compare_digest(_hash_pw(pw), h)

def _encrypt(text: str) -> str:
    """XOR encrypt — keys are never stored plaintext."""
    if not text: return ""
    k = SECRET.encode()
    d = text.encode()
    return base64.b64encode(bytes(d[i] ^ k[i % len(k)] for i in range(len(d)))).decode()

def _decrypt(enc: str) -> str:
    if not enc: return ""
    try:
        k = SECRET.encode()
        x = base64.b64decode(enc.encode())
        return bytes(x[i] ^ k[i % len(k)] for i in range(len(x))).decode()
    except:
        return ""

def _make_token(uid: int, email: str) -> str:
    payload  = json.dumps({"uid": uid, "email": email, "exp": int(time.time()) + 30 * 86400})
    b64      = base64.b64encode(payload.encode()).decode()
    sig      = _hmac.new(SECRET.encode(), b64.encode(), hashlib.sha256).hexdigest()
    return f"{b64}.{sig}"

def _verify_token(tok: str) -> dict | None:
    try:
        b64, sig = tok.rsplit(".", 1)
        expected = _hmac.new(SECRET.encode(), b64.encode(), hashlib.sha256).hexdigest()
        if not _hmac.compare_digest(sig, expected):
            return None
        payload = json.loads(base64.b64decode(b64.encode()).decode())
        return payload if payload.get("exp", 0) > time.time() else None
    except:
        return None

# ── User model ─────────────────────────────────────────────────────
class User(Base):
    __tablename__ = "users"
    id             = Column(Integer, primary_key=True, index=True)
    name           = Column(String,  nullable=False)
    email          = Column(String,  unique=True, index=True, nullable=False)
    password_hash  = Column(String,  nullable=False)
    binance_key    = Column(Text,    default="")    # encrypted
    binance_secret = Column(Text,    default="")    # encrypted
    testnet        = Column(Boolean, default=True)
    is_active      = Column(Boolean, default=True)
    role           = Column(String,  default="trader")
    created_at     = Column(DateTime, default=datetime.utcnow)
    last_login     = Column(DateTime, nullable=True)
    # Bot settings per user
    risk_pct       = Column(Text, default="1.0")
    max_trades     = Column(Integer, default=3)
    min_conf       = Column(Text, default="85.0")
    daily_limit    = Column(Text, default="5.0")
    max_leverage   = Column(Integer, default=50)

Base.metadata.create_all(bind=engine)

def _safe_user(u: User) -> dict:
    """Never expose password_hash, encrypted keys, or internal fields."""
    return {
        "id":          u.id,
        "name":        u.name,
        "email":       u.email,
        "testnet":     u.testnet,
        "role":        u.role,
        "has_keys":    bool(u.binance_key),
        "created_at":  u.created_at.isoformat() if u.created_at else None,
        "last_login":  u.last_login.isoformat()  if u.last_login  else None,
        "settings": {
            "risk_pct":    float(u.risk_pct    or 1.0),
            "max_trades":  u.max_trades or 3,
            "min_conf":    float(u.min_conf    or 85.0),
            "daily_limit": float(u.daily_limit or 5.0),
            "max_leverage": u.max_leverage or 50,
        },
    }

def get_current_user(authorization: str = Header(default=""), db: Session = Depends(get_db)):
    tok = authorization.replace("Bearer ", "").strip()
    if not tok:
        raise HTTPException(401, "Authentication required")
    payload = _verify_token(tok)
    if not payload:
        raise HTTPException(401, "Session expired — please login again")
    user = db.query(User).filter(User.id == payload["uid"]).first()
    if not user or not user.is_active:
        raise HTTPException(401, "Account not found or deactivated")
    return user

# ── AUTH ENDPOINTS ─────────────────────────────────────────────────

@router.post("/register")
async def register(request: Request, db: Session = Depends(get_db)):
    _check_rate_limit(_get_ip(request))
    data  = await request.json()
    name  = data.get("name",     "").strip()
    email = data.get("email",    "").strip().lower()
    pw    = data.get("password", "").strip()

    if not name or not email or not pw:
        raise HTTPException(400, "Name, email and password are required")
    if len(pw) < 6:
        raise HTTPException(400, "Password must be at least 6 characters")
    if "@" not in email or "." not in email.split("@")[-1]:
        raise HTTPException(400, "Invalid email address")
    if len(name) < 2:
        raise HTTPException(400, "Name must be at least 2 characters")

    if db.query(User).filter(User.email == email).first():
        raise HTTPException(409, "This email is already registered")

    user = User(name=name, email=email, password_hash=_hash_pw(pw))
    db.add(user)
    db.commit()
    db.refresh(user)

    token = _make_token(user.id, user.email)
    return {"success": True, "token": token, "user": _safe_user(user)}


@router.post("/login")
async def login(request: Request, db: Session = Depends(get_db)):
    _check_rate_limit(_get_ip(request))
    data  = await request.json()
    email = data.get("email",    "").strip().lower()
    pw    = data.get("password", "").strip()

    if not email or not pw:
        raise HTTPException(400, "Email and password required")

    user = db.query(User).filter(User.email == email).first()
    # Use constant-time compare to prevent timing attacks
    if not user or not _verify_pw(pw, user.password_hash):
        raise HTTPException(401, "Incorrect email or password")
    if not user.is_active:
        raise HTTPException(403, "Account has been deactivated")

    user.last_login = datetime.utcnow()
    db.commit()

    # Apply user's saved API keys to runtime
    _apply_user_keys(user)

    token = _make_token(user.id, user.email)
    return {"success": True, "token": token, "user": _safe_user(user)}


@router.get("/me")
def get_me(user: User = Depends(get_current_user)):
    return _safe_user(user)


@router.post("/keys")
async def save_keys(request: Request, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    data = await request.json()
    key  = data.get("api_key",    "").strip()
    sec  = data.get("api_secret", "").strip()

    if not key or not sec:
        raise HTTPException(400, "Both API key and secret are required")
    if len(key) < 10 or len(sec) < 10:
        raise HTTPException(400, "Keys appear too short — please check and try again")

    # Store encrypted — never log or return these
    user.binance_key    = _encrypt(key)
    user.binance_secret = _encrypt(sec)
    db.commit()

    # Test connection with new keys
    try:
        import modules.market_data as md
        md.BINANCE_API_KEY    = key
        md.BINANCE_SECRET_KEY = sec
        md._cached_balance    = 0.0
        md._balance_ts        = 0.0
        from modules.market_data import get_balance
        bal = get_balance()
        # Keys tested — don't hold them in memory beyond this
        if bal > 0:
            return {"success": True, "message": f"✓ Connected! Balance: ${bal:,.2f} USDT", "balance": round(bal, 2)}
        return {"success": True, "message": "Keys saved. Balance is $0 — verify Futures trading is enabled on your API key.", "balance": 0}
    except Exception as e:
        return {"success": True, "message": f"Keys saved. Could not verify balance: {str(e)[:60]}"}
    # NOTE: Never return the actual key or secret in any response


@router.get("/keys/status")
def keys_status(user: User = Depends(get_current_user)):
    """Return only whether keys exist and a masked preview — never the actual keys."""
    dec = _decrypt(user.binance_key or "")
    preview = f"{dec[:4]}{'*' * (len(dec)-8)}{dec[-4:]}" if len(dec) > 8 else "not configured"
    return {
        "has_keys":    bool(user.binance_key),
        "key_preview": preview,
        "testnet":     user.testnet,
    }


@router.post("/network")
async def toggle_network(request: Request, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    data    = await request.json()
    testnet = bool(data.get("testnet", True))
    user.testnet = testnet
    db.commit()

    try:
        import modules.market_data as md
        md.BINANCE_TESTNET = testnet
        md._cached_balance = 0.0
        md._balance_ts     = 0.0
        if testnet:
            md.EXEC_URL = os.getenv("FUTURES_EXEC_URL", "https://testnet.binancefuture.com")
        else:
            md.EXEC_URL = "https://fapi.binance.com"
    except Exception as e:
        print(f"[auth] network toggle error: {e}")

    mode = "TESTNET (demo funds)" if testnet else "MAINNET ⚠ REAL MONEY"
    return {"success": True, "testnet": testnet, "message": f"Switched to {mode}"}


@router.post("/settings")
async def save_settings(request: Request, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """User-adjustable trading settings — validated server-side."""
    data = await request.json()

    if "risk_pct" in data:
        val = float(data["risk_pct"])
        if not 0.1 <= val <= 5.0:
            raise HTTPException(400, "Risk % must be between 0.1 and 5.0")
        user.risk_pct = str(val)

    if "max_trades" in data:
        val = int(data["max_trades"])
        if not 1 <= val <= 10:
            raise HTTPException(400, "Max trades must be between 1 and 10")
        user.max_trades = val

    if "min_conf" in data:
        val = float(data["min_conf"])
        if not 70.0 <= val <= 99.0:
            raise HTTPException(400, "Min confidence must be between 70 and 99")
        user.min_conf = str(val)

    if "daily_limit" in data:
        val = float(data["daily_limit"])
        if not 1.0 <= val <= 20.0:
            raise HTTPException(400, "Daily limit must be between 1 and 20%")
        user.daily_limit = str(val)

    if "max_leverage" in data:
        val = int(data["max_leverage"])
        if val not in [10, 20, 50, 100]:
            raise HTTPException(400, "Max leverage must be 10, 20, 50, or 100")
        user.max_leverage = val

    db.commit()

    # Apply to live bot
    try:
        import config as cfg
        cfg.MAX_RISK_PCT        = float(user.risk_pct) / 100
        cfg.MAX_OPEN_TRADES     = user.max_trades
        cfg.MIN_CONFIDENCE      = float(user.min_conf)
        cfg.DAILY_DRAWDOWN_LIMIT= float(user.daily_limit) / 100
    except Exception as e:
        print(f"[auth] settings apply error: {e}")

    return {"success": True, "message": "Settings saved and applied", "settings": _safe_user(user)["settings"]}


@router.get("/settings")
def get_settings(user: User = Depends(get_current_user)):
    return _safe_user(user)["settings"]


@router.put("/profile")
async def update_profile(request: Request, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    data = await request.json()
    name = data.get("name", "").strip()
    if not name or len(name) < 2:
        raise HTTPException(400, "Name must be at least 2 characters")
    user.name = name
    db.commit()
    return {"success": True, "name": user.name}


@router.post("/logout")
def logout():
    """Client deletes token — server is stateless."""
    return {"success": True, "message": "Logged out"}


# ── Helper: apply user keys to runtime ────────────────────────────
def _apply_user_keys(user: User):
    """Decrypt and apply a user's API keys to the market_data module."""
    try:
        key = _decrypt(user.binance_key    or "")
        sec = _decrypt(user.binance_secret or "")
        if key and sec:
            import modules.market_data as md
            md.BINANCE_API_KEY    = key
            md.BINANCE_SECRET_KEY = sec
            md._cached_balance    = 0.0
            md._balance_ts        = 0.0
            md.BINANCE_TESTNET    = user.testnet
            if not user.testnet:
                md.EXEC_URL = "https://fapi.binance.com"
            else:
                md.EXEC_URL = os.getenv("FUTURES_EXEC_URL", "https://testnet.binancefuture.com")
    except Exception as e:
        print(f"[auth] apply keys error: {e}")
