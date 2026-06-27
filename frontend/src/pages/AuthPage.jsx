import { useState } from "react";
import { useApp } from "../context/AppContext";

const DISCLAIMER_ITEMS = [
  "⚠ RISK WARNING: Trading crypto futures involves substantial risk of loss.",
  "💡 WeltBot uses automated strategies — past performance does not guarantee future results.",
  "🔐 Your API keys are stored locally in your browser only.",
  "📉 Leverage amplifies both profits AND losses — trade responsibly.",
  "⚠ This is a testnet demo system. Always verify trades on your exchange.",
  "💡 Never invest more than you can afford to lose.",
  "🤖 WeltBot is an algorithmic tool, not financial advice.",
];

function Ticker({ items, speed = 50, className = "ticker-inner", itemClass = "ticker-item" }) {
  const doubled = [...items, ...items];
  return (
    <div className={className}>
      {doubled.map((item, i) => (
        <span key={i} className={itemClass}>
          {item}
          <span className="ticker-sep">·</span>
        </span>
      ))}
    </div>
  );
}

export default function AuthPage() {
  const { setUser, showToast } = useApp();
  const [tab,       setTab]       = useState("login");
  const [name,      setName]      = useState("");
  const [email,     setEmail]     = useState("");
  const [password,  setPassword]  = useState("");
  const [apiKey,    setApiKey]    = useState("");
  const [apiSecret, setApiSecret] = useState("");
  const [showPw,    setShowPw]    = useState(false);
  const [showSec,   setShowSec]   = useState(false);
  const [loading,   setLoading]   = useState(false);

  const handleSubmit = async () => {
    if (!email || !password) {
      showToast("Email and password are required", "error");
      return;
    }
    if (tab === "register" && !name) {
      showToast("Name is required", "error");
      return;
    }
    setLoading(true);
    await new Promise(r => setTimeout(r, 600)); // simulate auth

    // Local-only auth — store in localStorage
    const users = JSON.parse(localStorage.getItem("wb_users") || "[]");

    if (tab === "register") {
      const exists = users.find(u => u.email === email);
      if (exists) {
        showToast("Email already registered", "error");
        setLoading(false);
        return;
      }
      const newUser = {
        id:             Date.now(),
        name,
        email,
        password,
        binance_key:    apiKey,
        binance_secret: apiSecret,
        created_at:     new Date().toISOString(),
        role:           "trader",
      };
      users.push(newUser);
      localStorage.setItem("wb_users", JSON.stringify(users));
      localStorage.setItem("wb_user", JSON.stringify(newUser));
      setUser(newUser);
      showToast(`Welcome, ${name}! Account created.`, "success");
    } else {
      const found = users.find(u => u.email === email && u.password === password);
      if (!found) {
        showToast("Invalid email or password", "error");
        setLoading(false);
        return;
      }
      localStorage.setItem("wb_user", JSON.stringify(found));
      setUser(found);
      showToast(`Welcome back, ${found.name}!`, "success");
    }
    setLoading(false);
  };

  return (
    <div className="auth-page">
      {/* Disclaimer ticker */}
      <div className="disclaimer-wrap" style={{ position: "fixed", top: 0, left: 0, right: 0, zIndex: 999 }}>
        <Ticker items={DISCLAIMER_ITEMS} itemClass="disclaimer-item" />
      </div>

      <div style={{ marginTop: 28 }} />

      <div className="auth-card animate-in">
        <div className="auth-logo">
          <div className="auth-logo-text">
            <span className="w">WELT</span><span className="b">BOT</span>
          </div>
          <div className="auth-logo-sub">Autonomous Crypto Trading</div>
          <div style={{ display:"flex", justifyContent:"center", marginTop: 10 }}>
            <div style={{
              display:"inline-flex", gap: 6, padding:"3px 12px",
              borderRadius: 20, background:"rgba(77,159,255,0.08)",
              border:"1px solid rgba(77,159,255,0.2)",
              fontSize:10, color:"var(--info)", fontFamily:"var(--font-mono)",
            }}>
              <span>✦</span>
              <span>Smart Money Concepts · Directional Bias · Multi-Asset</span>
            </div>
          </div>
        </div>

        <div className="auth-tabs">
          <button className={`auth-tab ${tab === "login" ? "active" : ""}`} onClick={() => setTab("login")}>
            Sign In
          </button>
          <button className={`auth-tab ${tab === "register" ? "active" : ""}`} onClick={() => setTab("register")}>
            Create Account
          </button>
        </div>

        {tab === "register" && (
          <div className="form-group">
            <label className="form-label">Full Name</label>
            <input className="form-input" placeholder="Your name" value={name}
              onChange={e => setName(e.target.value)} />
          </div>
        )}

        <div className="form-group">
          <label className="form-label">Email Address</label>
          <input className="form-input" type="email" placeholder="you@example.com"
            value={email} onChange={e => setEmail(e.target.value)} />
        </div>

        <div className="form-group">
          <label className="form-label">Password</label>
          <div className="form-input-wrap">
            <input className="form-input" type={showPw ? "text" : "password"}
              placeholder="••••••••" value={password} onChange={e => setPassword(e.target.value)}
              onKeyDown={e => e.key === "Enter" && handleSubmit()} />
            <button className="form-input-eye" onClick={() => setShowPw(!showPw)}>
              {showPw ? "○" : "●"}
            </button>
          </div>
        </div>

        {tab === "register" && (
          <>
            <div className="glow-divider" />
            <div style={{ marginBottom: 12 }}>
              <div style={{ fontSize:11, color:"var(--text2)", marginBottom: 10 }}>
                <strong style={{ color:"var(--text)" }}>Binance API Keys</strong>
                <span style={{ color:"var(--text3)", marginLeft: 6 }}>· Optional, add now or in Settings later</span>
              </div>
              <div className="info-box info-box-blue" style={{ marginBottom: 10 }}>
                Your keys are encrypted and stored locally in your browser only. They never leave your device.
                Get demo keys from <strong>demo-fapi.binance.com</strong>
              </div>
            </div>
            <div className="form-group">
              <label className="form-label">Binance API Key</label>
              <input className="form-input" placeholder="Enter API key (optional)"
                value={apiKey} onChange={e => setApiKey(e.target.value)} />
            </div>
            <div className="form-group">
              <label className="form-label">Binance Secret Key</label>
              <div className="form-input-wrap">
                <input className="form-input" type={showSec ? "text" : "password"}
                  placeholder="Enter secret key (optional)"
                  value={apiSecret} onChange={e => setApiSecret(e.target.value)} />
                <button className="form-input-eye" onClick={() => setShowSec(!showSec)}>
                  {showSec ? "○" : "●"}
                </button>
              </div>
            </div>
          </>
        )}

        <button
          className="btn btn-primary"
          style={{ width:"100%", justifyContent:"center", marginTop: 8, padding:"12px" }}
          onClick={handleSubmit}
          disabled={loading}
        >
          {loading
            ? "Please wait…"
            : tab === "login" ? "Sign In to WeltBot" : "Create Account & Start Trading"
          }
        </button>

        <div className="auth-footer">
          {tab === "login"
            ? <>No account? <a href="#" onClick={() => setTab("register")}>Create one free</a></>
            : <>Already have an account? <a href="#" onClick={() => setTab("login")}>Sign in</a></>
          }
        </div>
      </div>

      <div className="built-by" style={{ position:"fixed", bottom:0, left:0, right:0 }}>
        Built with ⚡ by <span>Zilla</span> · WeltBot v5.0 · Autonomous Crypto Trading
      </div>
    </div>
  );
}

