import { useState, useEffect } from "react";
import { useApp }  from "../context/AppContext";
import { makeApi } from "../api";

export default function SettingsModal({ onClose, onRefresh }) {
  const { user, setUser, theme, setTheme, showToast } = useApp();
  const api = makeApi(user);

  const [section,    setSection]    = useState("apikeys");
  const [apiKey,     setApiKey]     = useState("");
  const [apiSecret,  setApiSecret]  = useState("");
  const [showKey,    setShowKey]    = useState(false);
  const [showSec,    setShowSec]    = useState(false);
  const [saving,     setSaving]     = useState(false);
  const [apiStatus,  setApiStatus]  = useState(null);
  const [testnet,    setTestnet]    = useState(true);
  const [botSettings,setBotSettings]= useState(null);
  const [riskPct,    setRiskPct]    = useState("1.0");
  const [maxTrades,  setMaxTrades]  = useState("3");
  const [minConf,    setMinConf]    = useState("85");
  const [dailyLimit, setDailyLimit] = useState("5");
  const [editName,   setEditName]   = useState(user?.name || "");
  const [togglingNet,setTogglingNet]= useState(false);
  const [savingBot,  setSavingBot]  = useState(false);

  useEffect(() => {
    api.getApiKeyStatus().then(s => {
      setApiStatus(s);
      setTestnet(s.testnet ?? true);
    }).catch(() => {});
    api.getBotSettings?.().catch(() => {});
  }, []);

  const saveApiKeys = async () => {
    if (!apiKey.trim() || !apiSecret.trim()) {
      showToast("Both API key and secret are required", "error");
      return;
    }
    setSaving(true);
    try {
      const r = await api.updateApiKeys(apiKey.trim(), apiSecret.trim());
      if (r.success) {
        // Persist keys in user profile
        const updated = { ...user, binance_key: apiKey.trim(), binance_secret: apiSecret.trim() };
        localStorage.setItem("wb_user", JSON.stringify(updated));
        const users = JSON.parse(localStorage.getItem("wb_users") || "[]");
        const idx   = users.findIndex(u => u.id === user.id);
        if (idx >= 0) { users[idx] = updated; localStorage.setItem("wb_users", JSON.stringify(users)); }
        setUser(updated);
        showToast(r.message || "Keys connected!", "success");
        setApiKey(""); setApiSecret("");
        const s = await api.getApiKeyStatus();
        setApiStatus(s);
        onRefresh();
      } else {
        showToast(r.error || "Connection failed", "error");
      }
    } catch (e) {
      showToast(`Error: ${e.message}`, "error");
    } finally { setSaving(false); }
  };

  const toggleNetwork = async (isTestnet) => {
    setTogglingNet(true);
    try {
      const r = await api.toggleNetwork(isTestnet);
      if (r.success) {
        setTestnet(isTestnet);
        showToast(r.message, "success");
        onRefresh();
      }
    } catch { showToast("Network toggle failed", "error"); }
    finally { setTogglingNet(false); }
  };

  const saveBotSettings = async () => {
    setSavingBot(true);
    try {
      const r = await api.updateBotSettings({
        risk_pct:    parseFloat(riskPct),
        max_trades:  parseInt(maxTrades),
        min_conf:    parseFloat(minConf),
        daily_limit: parseFloat(dailyLimit),
      });
      if (r.success) showToast("Bot settings saved!", "success");
      else showToast(r.error || "Save failed", "error");
    } catch { showToast("Save failed", "error"); }
    finally { setSavingBot(false); }
  };

  const saveName = () => {
    if (!editName.trim()) return;
    const updated = { ...user, name: editName.trim() };
    localStorage.setItem("wb_user", JSON.stringify(updated));
    const users = JSON.parse(localStorage.getItem("wb_users") || "[]");
    const idx = users.findIndex(u => u.id === user.id);
    if (idx >= 0) { users[idx] = updated; localStorage.setItem("wb_users", JSON.stringify(users)); }
    setUser(updated);
    showToast("Name updated", "success");
  };

  const sidebarItems = [
    { key: "apikeys",    icon: "🔑", label: "API Keys" },
    { key: "network",    icon: "🌐", label: "Network" },
    { key: "bot",        icon: "🤖", label: "Bot Settings" },
    { key: "appearance", icon: "🎨", label: "Appearance" },
    { key: "account",    icon: "👤", label: "Account" },
    { key: "risk",       icon: "🛡", label: "Risk Guide" },
    { key: "about",      icon: "ℹ",  label: "About" },
  ];

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal modal-lg" onClick={e => e.stopPropagation()}
        style={{ padding: 0, display: "flex", flexDirection: "column", width: 580, maxHeight: "90vh" }}>

        {/* Header */}
        <div style={{ padding: "20px 24px 16px", borderBottom: "1px solid var(--border)", display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <div>
            <div className="modal-title">Settings</div>
            <div className="modal-subtitle">Manage your WeltBot configuration</div>
          </div>
          <button className="icon-btn" onClick={onClose}>✕</button>
        </div>

        <div style={{ display: "flex", flex: 1, overflow: "hidden" }}>
          {/* Sidebar */}
          <div style={{ width: 155, borderRight: "1px solid var(--border)", padding: "10px 8px", display: "flex", flexDirection: "column", gap: 2, flexShrink: 0 }}>
            {sidebarItems.map(s => (
              <button key={s.key} onClick={() => setSection(s.key)} style={{
                display: "flex", alignItems: "center", gap: 8, padding: "8px 10px",
                borderRadius: 6, border: "none", cursor: "pointer", textAlign: "left",
                fontSize: 12, fontWeight: 500, fontFamily: "var(--font-body)",
                background: section === s.key ? "var(--surface2)" : "transparent",
                color: section === s.key ? "var(--text)" : "var(--text2)",
              }}>
                <span style={{ fontSize: 14 }}>{s.icon}</span>{s.label}
              </button>
            ))}
          </div>

          {/* Content */}
          <div style={{ flex: 1, padding: "20px 24px", overflowY: "auto" }}>

            {/* ── API KEYS ── */}
            {section === "apikeys" && (
              <div>
                <div className="settings-title">Binance API Keys</div>
                {apiStatus && (
                  <div className={`info-box ${apiStatus.configured ? "info-box-green" : "info-box-red"}`} style={{ marginBottom: 14 }}>
                    {apiStatus.configured
                      ? `✓ Connected — Key: ${apiStatus.key_preview}`
                      : "✗ No keys configured — bot cannot trade without them"}
                  </div>
                )}
                <div className="info-box info-box-blue" style={{ marginBottom: 14 }}>
                  <strong>Demo Trading:</strong> Get keys from <span style={{ color: "var(--info)" }}>demo-fapi.binance.com</span> → Account → API Management → Create HMAC key.<br /><br />
                  <strong>Live Trading:</strong> Get keys from Binance.com → API Management. Enable <strong>Futures only</strong>. Disable withdrawals.
                </div>
                <div className="form-group">
                  <label className="form-label">API Key</label>
                  <div className="form-input-wrap">
                    <input className="form-input" type={showKey ? "text" : "password"} value={apiKey}
                      onChange={e => setApiKey(e.target.value)} placeholder="Paste your Binance API key" />
                    <button className="form-input-eye" onClick={() => setShowKey(!showKey)}>{showKey ? "○" : "●"}</button>
                  </div>
                </div>
                <div className="form-group">
                  <label className="form-label">Secret Key</label>
                  <div className="form-input-wrap">
                    <input className="form-input" type={showSec ? "text" : "password"} value={apiSecret}
                      onChange={e => setApiSecret(e.target.value)} placeholder="Paste your Binance secret key" />
                    <button className="form-input-eye" onClick={() => setShowSec(!showSec)}>{showSec ? "○" : "●"}</button>
                  </div>
                </div>
                <button className="btn btn-primary" style={{ width: "100%", justifyContent: "center" }}
                  onClick={saveApiKeys} disabled={saving}>
                  {saving ? "Connecting…" : "Save & Connect API Keys"}
                </button>
                <div className="info-box info-box-warn" style={{ marginTop: 12 }}>
                  ⚠ Keys are stored in your browser profile and sent securely to the server on save. They are never logged or shared.
                </div>
              </div>
            )}

            {/* ── NETWORK ── */}
            {section === "network" && (
              <div>
                <div className="settings-title">Network Mode</div>
                <div className="info-box info-box-blue" style={{ marginBottom: 16 }}>
                  Switch between Binance demo trading (testnet) and real trading (mainnet). Your API keys must match the selected mode.
                </div>
                <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10, marginBottom: 16 }}>
                  {[
                    { label: "🧪 Testnet", desc: "Demo trading with virtual funds. Safe for testing.", val: true },
                    { label: "🔴 Mainnet", desc: "Real trading with real money. Use with caution.", val: false },
                  ].map(({ label, desc, val }) => (
                    <div key={label} onClick={() => !togglingNet && toggleNetwork(val)}
                      style={{
                        padding: 16, borderRadius: 10, cursor: "pointer", transition: "all 0.15s",
                        border: `2px solid ${testnet === val ? "var(--info)" : "var(--border)"}`,
                        background: testnet === val ? "rgba(77,159,255,0.06)" : "var(--surface2)",
                      }}>
                      <div style={{ fontSize: 14, fontWeight: 700, marginBottom: 6 }}>{label}</div>
                      <div style={{ fontSize: 11, color: "var(--text2)", lineHeight: 1.5 }}>{desc}</div>
                      {testnet === val && <div style={{ marginTop: 8, fontSize: 10, color: "var(--info)", fontFamily: "var(--font-mono)" }}>● ACTIVE</div>}
                    </div>
                  ))}
                </div>
                {!testnet && (
                  <div className="info-box info-box-red">
                    ⚠ MAINNET MODE: Real money at risk. Ensure your API keys are from Binance.com (not demo-fapi). The bot will use real USDT from your futures wallet.
                  </div>
                )}
              </div>
            )}

            {/* ── BOT SETTINGS ── */}
            {section === "bot" && (
              <div>
                <div className="settings-title">Trading Parameters</div>
                <div className="form-row" style={{ marginBottom: 12 }}>
                  <div className="form-group" style={{ marginBottom: 0 }}>
                    <label className="form-label">Risk per Trade (%)</label>
                    <input className="form-input" type="number" min="0.1" max="5" step="0.1"
                      value={riskPct} onChange={e => setRiskPct(e.target.value)} />
                    <div style={{ fontSize: 10, color: "var(--text3)", marginTop: 4 }}>Recommended: 1%</div>
                  </div>
                  <div className="form-group" style={{ marginBottom: 0 }}>
                    <label className="form-label">Max Open Positions</label>
                    <input className="form-input" type="number" min="1" max="10"
                      value={maxTrades} onChange={e => setMaxTrades(e.target.value)} />
                    <div style={{ fontSize: 10, color: "var(--text3)", marginTop: 4 }}>Recommended: 3</div>
                  </div>
                </div>
                <div className="form-row" style={{ marginBottom: 16 }}>
                  <div className="form-group" style={{ marginBottom: 0 }}>
                    <label className="form-label">Min Confidence (%)</label>
                    <input className="form-input" type="number" min="70" max="99"
                      value={minConf} onChange={e => setMinConf(e.target.value)} />
                    <div style={{ fontSize: 10, color: "var(--text3)", marginTop: 4 }}>Higher = fewer but better trades</div>
                  </div>
                  <div className="form-group" style={{ marginBottom: 0 }}>
                    <label className="form-label">Daily Loss Limit (%)</label>
                    <input className="form-input" type="number" min="1" max="20"
                      value={dailyLimit} onChange={e => setDailyLimit(e.target.value)} />
                    <div style={{ fontSize: 10, color: "var(--text3)", marginTop: 4 }}>Bot pauses if hit</div>
                  </div>
                </div>

                <div className="settings-title">Leverage Tiers</div>
                <div className="info-box info-box-blue" style={{ marginBottom: 12 }}>
                  Leverage is assigned automatically based on confidence score. Higher confidence = higher leverage.
                </div>
                <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8, marginBottom: 16 }}>
                  {[
                    ["lev-100","100x","98%+","BTC/ETH only"],
                    ["lev-50","50x","95%+","All major pairs"],
                    ["lev-20","20x","90-94%","All assets"],
                    ["lev-10","10x","85-89%","All assets"],
                  ].map(([cls, lev, conf, note]) => (
                    <div key={lev} className="card-sm" style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                      <div>
                        <span className={`lev-badge ${cls}`}>{lev}</span>
                        <div style={{ fontSize: 10, color: "var(--text3)", marginTop: 3 }}>{note}</div>
                      </div>
                      <div style={{ fontSize: 12, fontFamily: "var(--font-mono)", color: "var(--text2)" }}>{conf}</div>
                    </div>
                  ))}
                </div>

                <button className="btn btn-primary" onClick={saveBotSettings} disabled={savingBot} style={{ width: "100%", justifyContent: "center" }}>
                  {savingBot ? "Saving…" : "Apply Settings"}
                </button>
                <div className="info-box info-box-warn" style={{ marginTop: 10 }}>
                  Settings apply immediately to the running bot. To persist after restart, update Railway environment variables too.
                </div>
              </div>
            )}

            {/* ── APPEARANCE ── */}
            {section === "appearance" && (
              <div>
                <div className="settings-title">Theme</div>
                <div className="settings-row">
                  <div>
                    <div className="settings-row-label">Color Mode</div>
                    <div className="settings-row-desc">Dark is recommended for trading</div>
                  </div>
                  <div className="theme-selector">
                    {[["dark","🌙 Dark"],["light","☀ Light"]].map(([t,l]) => (
                      <button key={t} className={`theme-btn ${theme===t?"active":""}`} onClick={() => setTheme(t)}>{l}</button>
                    ))}
                  </div>
                </div>
                <div className="settings-row">
                  <div>
                    <div className="settings-row-label">Accent Color</div>
                    <div className="settings-row-desc">Primary interface color</div>
                  </div>
                  <div className="color-picker">
                    {[["#4d9fff","Blue"],["#00e5a0","Green"],["#a78bfa","Purple"],["#f59e0b","Amber"],["#f43f5e","Rose"]].map(([c,n]) => (
                      <div key={c} className="color-swatch" style={{ background: c }} title={n}
                        onClick={() => { document.documentElement.style.setProperty("--info", c); showToast(`Accent: ${n}`); }} />
                    ))}
                  </div>
                </div>
              </div>
            )}

            {/* ── ACCOUNT ── */}
            {section === "account" && (
              <div>
                <div className="settings-title">Profile</div>
                <div style={{ display: "flex", alignItems: "center", gap: 14, padding: "14px 0", borderBottom: "1px solid var(--border)", marginBottom: 16 }}>
                  <div style={{ width: 52, height: 52, borderRadius: "50%", background: "linear-gradient(135deg,var(--info),var(--purple))", display: "flex", alignItems: "center", justifyContent: "center", fontSize: 22, fontWeight: 700, color: "#fff" }}>
                    {user?.name?.charAt(0)?.toUpperCase() || "U"}
                  </div>
                  <div>
                    <div style={{ fontSize: 16, fontWeight: 600 }}>{user?.name}</div>
                    <div style={{ fontSize: 12, color: "var(--text3)" }}>{user?.email}</div>
                    <div style={{ fontSize: 10, color: "var(--text3)", marginTop: 2, fontFamily: "var(--font-mono)" }}>
                      TRADER · Joined {user?.created_at ? new Date(user.created_at).toLocaleDateString() : "—"}
                    </div>
                  </div>
                </div>
                <div className="form-group">
                  <label className="form-label">Display Name</label>
                  <div style={{ display: "flex", gap: 8 }}>
                    <input className="form-input" value={editName} onChange={e => setEditName(e.target.value)} />
                    <button className="btn btn-ghost" onClick={saveName}>Save</button>
                  </div>
                </div>
                <div className="form-group">
                  <label className="form-label">Email</label>
                  <input className="form-input" value={user?.email || ""} disabled style={{ opacity: 0.6 }} />
                </div>
              </div>
            )}

            {/* ── RISK GUIDE ── */}
            {section === "risk" && (
              <div>
                <div className="settings-title">Risk Management</div>
                <div className="info-box info-box-warn" style={{ marginBottom: 14 }}>
                  ⚠ WeltBot has multiple safeguards. Understand all of them before using real funds.
                </div>
                {[
                  ["🛡","1% Risk Per Trade","Each trade risks exactly 1% of your balance. 10 losses in a row = only 10% loss."],
                  ["📉","5% Daily Loss Stop","Bot auto-pauses if account loses 5% in one day. Prevents catastrophic losses."],
                  ["⏱","4-Hour SL Cooldown","After a stop-loss on any asset, that asset is blocked for 4 hours."],
                  ["📊","Max 3 Positions","Never more than 3 open trades simultaneously."],
                  ["🎯","Liquidation Guard","If liquidation price is within 2.5x ATR, leverage is automatically reduced."],
                  ["🔒","100x Whitelist","Extreme leverage only for BTC and ETH — most liquid assets with lowest gap risk."],
                  ["📡","HTF Bias Filter","Blocks countertrend trades. 4H bearish = no BUY signals taken."],
                  ["📰","News Blackout","Trading pauses 15min before high-impact economic events."],
                ].map(([icon, title, desc]) => (
                  <div key={title} style={{ display: "flex", gap: 12, padding: "11px 0", borderBottom: "1px solid var(--border)" }}>
                    <span style={{ fontSize: 18, flexShrink: 0 }}>{icon}</span>
                    <div>
                      <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 3 }}>{title}</div>
                      <div style={{ fontSize: 11, color: "var(--text2)", lineHeight: 1.6 }}>{desc}</div>
                    </div>
                  </div>
                ))}
              </div>
            )}

            {/* ── ABOUT ── */}
            {section === "about" && (
              <div>
                <div style={{ textAlign: "center", padding: "14px 0 20px" }}>
                  <div style={{ fontFamily: "var(--font-display)", fontSize: 34, fontWeight: 800, marginBottom: 4 }}>
                    <span style={{ color: "var(--info)" }}>WELT</span>BOT
                  </div>
                  <div style={{ fontSize: 11, color: "var(--text3)", fontFamily: "var(--font-mono)" }}>Version 5.0 · Autonomous Crypto Trading</div>
                </div>
                {[
                  ["Strategy", "Smart Money Concepts v5.0 — BOS + Fib + OB + MA + HTF Bias"],
                  ["Entry Filter", "4H + 1H directional bias blocks countertrend trades"],
                  ["Leverage", "Dynamic 10x / 20x / 50x / 100x based on confidence"],
                  ["News", "ForexFactory blackout + Twitter @Deltaone @unusual_whale @financialjuice"],
                  ["Backend", "Python FastAPI + APScheduler + SQLite"],
                  ["Hosting", "Railway (backend) + Vercel (frontend)"],
                  ["Built by", "Zilla · Syntrion Lab"],
                ].map(([k, v]) => (
                  <div key={k} style={{ display: "flex", justifyContent: "space-between", padding: "9px 0", borderBottom: "1px solid var(--border)", fontSize: 12 }}>
                    <span style={{ color: "var(--text3)" }}>{k}</span>
                    <span style={{ color: "var(--text)", textAlign: "right", maxWidth: 260 }}>{v}</span>
                  </div>
                ))}
                <div style={{ textAlign: "center", marginTop: 20, fontSize: 11, color: "var(--text3)" }}>
                  Built with ⚡ by <span style={{ color: "var(--info)", fontWeight: 600 }}>Zilla</span> · Syntrion Lab<br />
                  <span style={{ fontSize: 10, marginTop: 4, display: "block" }}>Not financial advice. Trade responsibly.</span>
                </div>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

