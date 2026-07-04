"""
backend/routers/auth.py
WeltBot User Authentication
- Register / Login with JWT tokens
- Encrypted API key storage per user
- Testnet/Mainnet toggle per user
- Works cross-device — stored in server DB
"""
from fastapi import APIRouter, Depends, HTTPException, Header
from sqlalchemy import Column, Integer, String, Boolean, DateTime, Text
from sqlalchemy.orm import Session
from database import get_db, Base, engine
from datetime import datetime
import hashlib, hmac, json, os, base64, time

router = APIRouter(prefix="/api/auth", tags=["auth"])

SECRET = os.getenv("SECRET_KEY", "weltbot-zilla-syntrion-2026")

# ── simple crypto (no extra deps) ─────────────────────────────────
def _hash_pw(pw: str) -> str:
    return hashlib.sha256(f"{SECRET[:16]}{pw}{SECRET[:16]}".encode()).hexdigest()

def _verify_pw(pw: str, h: str) -> bool:
    return _hash_pw(pw) == h

def _encrypt(text: str) -> str:
    if not text: return ""
    k = SECRET.encode(); d = text.encode()
    return base64.b64encode(bytes(d[i]^k[i%len(k)] for i in range(len(d)))).decode()

def _decrypt(enc: str) -> str:
    if not enc: return ""
    try:
        k = SECRET.encode(); x = base64.b64decode(enc.encode())
        return bytes(x[i]^k[i%len(k)] for i in range(len(x))).decode()
    except: return ""

def _make_token(uid: int, email: str) -> str:
    p = json.dumps({"uid": uid, "email": email, "exp": int(time.time())+30*86400})
    b = base64.b64encode(p.encode()).decode()
    s = hmac.new(SECRET.encode(), b.encode(), hashlib.sha256).hexdigest()
    return f"{b}.{s}"

def _verify_token(tok: str) -> dict | None:
    try:
        b, s = tok.split(".")
        if not hmac.compare_digest(s, hmac.new(SECRET.encode(), b.encode(), hashlib.sha256).hexdigest()):
            return None
        p = json.loads(base64.b64decode(b.encode()).decode())
        return p if p.get("exp",0) > time.time() else None
    except: return None

# ── model ─────────────────────────────────────────────────────────
class User(Base):
    __tablename__ = "users"
    id             = Column(Integer, primary_key=True, index=True)
    name           = Column(String,  nullable=False)
    email          = Column(String,  unique=True, index=True, nullable=False)
    password_hash  = Column(String,  nullable=False)
    binance_key    = Column(Text,    default="")
    binance_secret = Column(Text,    default="")
    testnet        = Column(Boolean, default=True)
    is_active      = Column(Boolean, default=True)
    role           = Column(String,  default="trader")
    created_at     = Column(DateTime, default=datetime.utcnow)
    last_login     = Column(DateTime, nullable=True)

Base.metadata.create_all(bind=engine)

def _user_dict(u: User, has_keys=None) -> dict:
    return {
        "id": u.id, "name": u.name, "email": u.email,
        "testnet": u.testnet, "role": u.role,
        "has_keys": has_keys if has_keys is not None else bool(u.binance_key),
        "created_at": u.created_at.isoformat() if u.created_at else None,
        "last_login": u.last_login.isoformat() if u.last_login else None,
    }

def get_current_user(authorization: str = Header(default=""), db: Session = Depends(get_db)):
    tok = authorization.replace("Bearer ", "").strip()
    if not tok: raise HTTPException(401, "No token")
    p = _verify_token(tok)
    if not p:   raise HTTPException(401, "Invalid or expired token — please login again")
    u = db.query(User).filter(User.id == p["uid"]).first()
    if not u or not u.is_active: raise HTTPException(401, "Account not found")
    return u

# ── endpoints ─────────────────────────────────────────────────────
@router.post("/register")
async def register(data: dict, db: Session = Depends(get_db)):
    name = data.get("name","").strip()
    email = data.get("email","").strip().lower()
    pw   = data.get("password","").strip()
    if not name or not email or not pw:
        raise HTTPException(400, "Name, email and password required")
    if len(pw) < 6:
        raise HTTPException(400, "Password must be at least 6 characters")
    if "@" not in email:
        raise HTTPException(400, "Invalid email address")
    if db.query(User).filter(User.email == email).first():
        raise HTTPException(409, "Email already registered — please sign in")
    u = User(name=name, email=email, password_hash=_hash_pw(pw))
    db.add(u); db.commit(); db.refresh(u)
    return {"success": True, "token": _make_token(u.id, u.email), "user": _user_dict(u, False)}

@router.post("/login")
async def login(data: dict, db: Session = Depends(get_db)):
    email = data.get("email","").strip().lower()
    pw    = data.get("password","").strip()
    if not email or not pw: raise HTTPException(400, "Email and password required")
    u = db.query(User).filter(User.email == email).first()
    if not u or not _verify_pw(pw, u.password_hash):
        raise HTTPException(401, "Incorrect email or password")
    if not u.is_active: raise HTTPException(403, "Account deactivated")
    u.last_login = datetime.utcnow(); db.commit()
    return {"success": True, "token": _make_token(u.id, u.email), "user": _user_dict(u)}

@router.get("/me")
def get_me(u: User = Depends(get_current_user)):
    return _user_dict(u)

@router.post("/keys")
async def save_keys(data: dict, u: User = Depends(get_current_user), db: Session = Depends(get_db)):
    key = data.get("api_key","").strip()
    sec = data.get("api_secret","").strip()
    if not key or not sec: raise HTTPException(400, "Both API key and secret required")
    u.binance_key    = _encrypt(key)
    u.binance_secret = _encrypt(sec)
    db.commit()
    # Test connection
    try:
        import modules.market_data as md
        md.BINANCE_API_KEY = key; md.BINANCE_SECRET_KEY = sec
        md._cached_balance = 0.0; md._balance_ts = 0.0
        from modules.market_data import get_balance
        bal = get_balance()
        if bal > 0:
            return {"success": True, "message": f"✓ Connected! Balance: ${bal:,.2f} USDT", "balance": bal}
        return {"success": True, "message": "Keys saved. Balance $0 — check Futures permission is enabled.", "balance": 0}
    except Exception as e:
        return {"success": True, "message": f"Keys saved. Connection test: {str(e)[:80]}"}

@router.get("/keys/status")
def key_status(u: User = Depends(get_current_user)):
    dec = _decrypt(u.binance_key or "")
    return {
        "has_keys":    bool(u.binance_key),
        "key_preview": f"{dec[:6]}...{dec[-4:]}" if len(dec) > 10 else "not set",
        "testnet":     u.testnet,
    }

@router.post("/network")
async def toggle_network(data: dict, u: User = Depends(get_current_user), db: Session = Depends(get_db)):
    testnet = data.get("testnet", True)
    u.testnet = testnet; db.commit()
    # Apply live
    try:
        import modules.market_data as md
        md.BINANCE_TESTNET = testnet; md._cached_balance = 0.0; md._balance_ts = 0.0
        md.EXEC_URL = os.getenv("FUTURES_EXEC_URL","https://testnet.binancefuture.com") if testnet else "https://fapi.binance.com"
    except Exception as e: print(f"[auth] network toggle: {e}")
    mode = "TESTNET (demo)" if testnet else "MAINNET (live) 🔴"
    return {"success": True, "testnet": testnet, "message": f"Switched to {mode}"}

@router.put("/profile")
async def update_profile(data: dict, u: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if name := data.get("name","").strip():
        u.name = name; db.commit()
    return {"success": True, "name": u.name}

@router.post("/logout")
def logout(): return {"success": True}
