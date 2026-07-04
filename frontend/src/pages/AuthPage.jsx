import { useState } from "react";
import { useApp }  from "../context/AppContext";
import { authApi } from "../api";

const DISCLAIMERS = [
  "⚠ RISK WARNING: Crypto futures trading involves substantial risk of loss",
  "💡 WeltBot is an algorithmic tool, not financial advice — always do your own research",
  "🔐 Your API keys are encrypted and stored securely in the server database",
  "📉 High leverage amplifies losses as well as gains — always use risk management",
  "⚠ Never invest money you cannot afford to lose",
  "🤖 Past performance does not guarantee future results",
  "💡 Always test on testnet before switching to mainnet with real funds",
  "⚠ WeltBot is for educational purposes only — trade responsibly",
];

export default function AuthPage() {
  const { setSession, showToast } = useApp();
  const [tab,      setTab]      = useState("login");
  const [name,     setName]     = useState("");
  const [email,    setEmail]    = useState("");
  const [password, setPassword] = useState("");
  const [showPw,   setShowPw]   = useState(false);
  const [loading,  setLoading]  = useState(false);
  const [error,    setError]    = useState("");

  const handleSubmit = async () => {
    setError("");
    if (!email || !password) { setError("Email and password are required"); return; }
    if (tab === "register" && !name) { setError("Name is required"); return; }
    if (password.length < 6) { setError("Password must be at least 6 characters"); return; }

    setLoading(true);
    try {
      let result;
      if (tab === "register") {
        result = await authApi.register(name.trim(), email.trim().toLowerCase(), password);
        showToast(`Welcome to WeltBot, ${result.user.name}! 🎉`, "success");
      } else {
        result = await authApi.login(email.trim().toLowerCase(), password);
        showToast(`Welcome back, ${result.user.name}!`, "success");
      }
      setSession(result.token, result.user);
    } catch (e) {
      setError(e.message || "Something went wrong");
    } finally {
      setLoading(false);
    }
  };

  const doubled = [...DISCLAIMERS, ...DISCLAIMERS];

  return (
    <div className="auth-page">
      {/* Disclaimer ticker */}
      <div className="disclaimer-wrap" style={{ position:"fixed", top:0, left:0, right:0, zIndex:999 }}>
        <div className="disclaimer-inner">
          {doubled.map((item, i) => (
            <span key={i} className="disclaimer-item">
              {item}
              <span style={{ color:"var(--text3)", margin:"0 16px" }}>·</span>
            </span>
          ))}
        </div>
      </div>

      <div style={{ marginTop: 28 }} />

      <div className="auth-card animate-in">
        {/* Logo */}
        <div className="auth-logo">
          <div className="auth-logo-text">
            <span className="w">WELT</span><span className="b">BOT</span>
          </div>
          <div className="auth-logo-sub">Autonomous Crypto Trading · v5.0</div>
          <div style={{ display:"flex", justifyContent:"center", marginTop:10 }}>
            <div style={{
              display:"inline-flex", gap:6, padding:"4px 14px", borderRadius:20,
              background:"rgba(77,159,255,0.08)", border:"1px solid rgba(77,159,255,0.2)",
              fontSize:10, color:"var(--info)", fontFamily:"var(--font-mono)",
            }}>
              ✦ Smart Money Concepts · HTF Directional Bias · Multi-Asset
            </div>
          </div>
        </div>

        {/* Tabs */}
        <div className="auth-tabs">
          <button className={`auth-tab ${tab==="login"?"active":""}`} onClick={() => { setTab("login"); setError(""); }}>
            Sign In
          </button>
          <button className={`auth-tab ${tab==="register"?"active":""}`} onClick={() => { setTab("register"); setError(""); }}>
            Create Account
          </button>
        </div>

        {/* Error */}
        {error && (
          <div className="info-box info-box-red" style={{ marginBottom:14, fontSize:12 }}>
            ✕ {error}
          </div>
        )}

        {/* Fields */}
        {tab === "register" && (
          <div className="form-group">
            <label className="form-label">Full Name</label>
            <input className="form-input" placeholder="Your name" value={name}
              onChange={e => setName(e.target.value)} autoFocus />
          </div>
        )}

        <div className="form-group">
          <label className="form-label">Email Address</label>
          <input className="form-input" type="email" placeholder="you@example.com"
            value={email} onChange={e => setEmail(e.target.value)}
            autoFocus={tab === "login"} />
        </div>

        <div className="form-group">
          <label className="form-label">Password</label>
          <div className="form-input-wrap">
            <input className="form-input" type={showPw?"text":"password"} placeholder="••••••••"
              value={password} onChange={e => setPassword(e.target.value)}
              onKeyDown={e => e.key === "Enter" && handleSubmit()} />
            <button className="form-input-eye" onClick={() => setShowPw(!showPw)}>
              {showPw ? "○" : "●"}
            </button>
          </div>
        </div>

        {tab === "register" && (
          <div className="info-box info-box-blue" style={{ marginBottom:14, fontSize:11 }}>
            ℹ After registering, go to <strong>Settings → API Keys</strong> to connect your Binance account.
            You can use demo keys from <span style={{ color:"var(--info)" }}>demo-fapi.binance.com</span> to start safely.
          </div>
        )}

        <button
          className="btn btn-primary"
          style={{ width:"100%", justifyContent:"center", padding:"12px", fontSize:13 }}
          onClick={handleSubmit}
          disabled={loading}
        >
          {loading ? "Please wait…" : tab === "login" ? "Sign In to WeltBot" : "Create Account"}
        </button>

        <div className="auth-footer">
          {tab === "login"
            ? <>No account? <a href="#" onClick={e => { e.preventDefault(); setTab("register"); setError(""); }}>Create one free</a></>
            : <>Already registered? <a href="#" onClick={e => { e.preventDefault(); setTab("login"); setError(""); }}>Sign in</a></>
          }
        </div>
      </div>

      <div className="built-by" style={{ position:"fixed", bottom:0, left:0, right:0 }}>
        Built with ⚡ by <span>Zilla</span> · Syntrion Lab · WeltBot v5.0 · Not financial advice
      </div>
    </div>
  );
}

