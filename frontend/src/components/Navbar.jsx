import { useApp } from "../context/AppContext";

export default function Navbar({ tab, setTab, botStatus, onSettings, ctx }) {
  const { user, logout } = useApp();
  const { handleStart, handleStop, handleScan, actionLoad, lastUpdate } = ctx;

  const isLive   = botStatus?.running && !botStatus?.paused;
  const isPaused = botStatus?.paused;
  const balance  = botStatus?.balance_usdt ?? 0;

  const statusLabel = isLive ? "LIVE" : isPaused ? "PAUSED" : "STOPPED";
  const statusClass = isLive ? "live" : isPaused ? "paused" : "stopped";

  const initials = user?.name
    ? user.name.split(" ").map(n => n[0]).join("").toUpperCase().slice(0, 2)
    : "U";

  return (
    <nav className="navbar">
      {/* Brand */}
      <div className="navbar-brand">
        <div className="brand-logo">
          <span className="w">WELT</span><span className="b">BOT</span>
        </div>
        <span className="brand-tag">v5.0</span>
        <div className={`status-pill ${statusClass}`}>
          <div className={`pulse-dot ${isLive ? "live" : ""}`} />
          {statusLabel}
        </div>
        {botStatus?.testnet && (
          <span style={{
            fontSize:9, color:"var(--purple)", padding:"2px 8px",
            borderRadius:4, background:"rgba(167,139,250,0.1)",
            border:"1px solid rgba(167,139,250,0.25)",
            fontFamily:"var(--font-mono)", letterSpacing:"0.1em",
          }}>TESTNET</span>
        )}
      </div>

      {/* Tabs */}
      <div className="navbar-center">
        {["overview","signals","trades"].map(t => (
          <button key={t} className={`nav-tab ${tab === t ? "active" : ""}`} onClick={() => setTab(t)}>
            {t === "overview" ? "📊 Overview" : t === "signals" ? "📡 Signals" : "📋 Trades"}
          </button>
        ))}
      </div>

      {/* Right */}
      <div className="navbar-right">
        {lastUpdate && (
          <span style={{ fontSize:10, color:"var(--text3)", fontFamily:"var(--font-mono)" }}>
            {lastUpdate}
          </span>
        )}

        <div className="balance-chip">
          <span className="bal">${balance.toLocaleString(undefined,{minimumFractionDigits:2,maximumFractionDigits:2})}</span>
          <span className="bal-label">USDT</span>
        </div>

        {/* Controls */}
        {!isLive
          ? <button className="btn btn-success btn-sm" onClick={handleStart} disabled={actionLoad}>
              {actionLoad ? "…" : "▶ Start"}
            </button>
          : <button className="btn btn-danger btn-sm" onClick={handleStop} disabled={actionLoad}>
              {actionLoad ? "…" : "■ Stop"}
            </button>
        }
        <button className="btn btn-scan btn-sm" onClick={handleScan} disabled={actionLoad}>
          ⟳ Scan
        </button>

        <button className="icon-btn" onClick={onSettings} title="Settings">⚙</button>

        {/* User */}
        <div className="user-chip" onClick={() => {}}>
          <div className="user-avatar">{initials}</div>
          <span className="user-name">{user?.name?.split(" ")[0] || "Trader"}</span>
        </div>

        <button className="icon-btn" onClick={logout} title="Sign out" style={{ fontSize:13 }}>
          ⎋
        </button>
      </div>
    </nav>
  );
}

