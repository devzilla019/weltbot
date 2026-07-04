#!/bin/bash
echo "╔══════════════════════════════════════════╗"
echo "║   WeltBot v5.0 — Complete Frontend       ║"
echo "╚══════════════════════════════════════════╝"
F="/c/Users/Lotim/weltbot/frontend"
mkdir -p "$F/src/components" "$F/src/pages" "$F/src/context"

cat > "$F/index.html" << 'WBEOF'
<!DOCTYPE html>
<html lang="en" data-theme="dark">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <meta name="description" content="WeltBot — Autonomous Crypto Trading Bot with Smart Money Concepts" />
    <meta name="theme-color" content="#070b12" />
    <title>WeltBot — Autonomous Crypto Trading</title>
    <link rel="icon" type="image/svg+xml" href="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'><text y='.9em' font-size='90'>⚡</text></svg>" />
  </head>
  <body>
    <div id="root"></div>
    <script type="module" src="/src/main.jsx"></script>
  </body>
</html>

WBEOF
echo "  ✓ index.html"

cat > "$F/vite.config.js" << 'WBEOF'
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: { port: 5173 },
});

WBEOF
echo "  ✓ vite.config.js"

cat > "$F/package.json" << 'WBEOF'
{
  "name": "weltbot-frontend",
  "private": true,
  "version": "5.0.0",
  "type": "module",
  "scripts": {
    "dev":     "vite",
    "build":   "vite build",
    "preview": "vite preview"
  },
  "dependencies": {
    "react":     "^18.2.0",
    "react-dom": "^18.2.0"
  },
  "devDependencies": {
    "@vitejs/plugin-react": "^4.2.1",
    "vite":                 "^5.2.0"
  }
}

WBEOF
echo "  ✓ package.json"

cat > "$F/src/main.jsx" << 'WBEOF'
import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App.jsx";
import "./index.css";

ReactDOM.createRoot(document.getElementById("root")).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);

WBEOF
echo "  ✓ src/main.jsx"

cat > "$F/src/api.js" << 'WBEOF'
const BASE = import.meta.env.VITE_API_URL || "http://localhost:8000";

const req = async (method, path, body, token) => {
  const headers = { "Content-Type": "application/json" };
  if (token) headers["Authorization"] = `Bearer ${token}`;
  const r = await fetch(`${BASE}${path}`, {
    method,
    headers,
    body: body ? JSON.stringify(body) : undefined,
  });
  const data = await r.json();
  if (!r.ok) throw new Error(data.detail || `HTTP ${r.status}`);
  return data;
};

// Auth API — no token needed
export const authApi = {
  register:   (name, email, pw) => req("POST", "/api/auth/register", { name, email, password: pw }),
  login:      (email, pw)       => req("POST", "/api/auth/login",    { email, password: pw }),
  getMe:      (token)           => req("GET",  "/api/auth/me",       null, token),
  saveKeys:   (token, key, sec) => req("POST", "/api/auth/keys",     { api_key: key, api_secret: sec }, token),
  getKeyStat: (token)           => req("GET",  "/api/auth/keys/status", null, token),
  toggleNet:  (token, testnet)  => req("POST", "/api/auth/network",  { testnet }, token),
  updateName: (token, name)     => req("PUT",  "/api/auth/profile",  { name }, token),
};

// Bot API — uses auth token
export const makeApi = (token) => ({
  getBotStatus:      ()       => req("GET",    "/api/bot/status",                   null,   token),
  startBot:          ()       => req("POST",   "/api/bot/start",                    null,   token),
  stopBot:           ()       => req("POST",   "/api/bot/stop",                     null,   token),
  scanNow:           ()       => req("POST",   "/api/bot/scan-now",                 null,   token),
  getAllSignals:      ()       => req("GET",    "/api/signals/",                     null,   token),
  getTrades:         ()       => req("GET",    "/api/trades/",                      null,   token),
  clearTrades:       ()       => req("DELETE", "/api/trades/clear",                 null,   token),
  closeTrade:        (id)     => req("POST",   `/api/trades/${id}/close`,           null,   token),
  getSummary:        ()       => req("GET",    "/api/analytics/summary",            null,   token),
  getPortfolio:      ()       => req("GET",    "/api/analytics/portfolio",          null,   token),
  updateBotSettings: (d)      => req("POST",   "/api/analytics/settings/bot",       d,      token),
  getBotSettings:    ()       => req("GET",    "/api/analytics/settings/bot",       null,   token),
});

WBEOF
echo "  ✓ src/api.js"

cat > "$F/src/index.css" << 'WBEOF'
@import url('https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@300;400;500;600;700&family=JetBrains+Mono:wght@300;400;500;600&family=Syne:wght@700;800&display=swap');

/* ── TOKENS ─────────────────────────────────────────────────────── */
:root {
  --font-display: 'Syne', sans-serif;
  --font-body:    'Space Grotesk', sans-serif;
  --font-mono:    'JetBrains Mono', monospace;

  --buy:    #00e5a0;
  --sell:   #ff4d6d;
  --info:   #4d9fff;
  --warn:   #f5a623;
  --purple: #a78bfa;
  --gold:   #fbbf24;

  --radius-sm: 6px;
  --radius-md: 10px;
  --radius-lg: 16px;
  --radius-xl: 24px;
}

/* DARK THEME (default) */
[data-theme="dark"] {
  --bg:       #070b12;
  --bg2:      #0c1220;
  --bg3:      #111827;
  --surface:  #141d2e;
  --surface2: #1a2540;
  --surface3: #1e2d47;
  --border:   rgba(255,255,255,0.06);
  --border2:  rgba(255,255,255,0.1);
  --text:     #e8edf5;
  --text2:    #94a3b8;
  --text3:    #4b5e7a;
  --glow:     rgba(77,159,255,0.15);
  --ticker-bg: rgba(10,16,28,0.95);
}

/* LIGHT THEME */
[data-theme="light"] {
  --bg:       #f0f4f8;
  --bg2:      #ffffff;
  --bg3:      #f8fafc;
  --surface:  #ffffff;
  --surface2: #f1f5f9;
  --surface3: #e2e8f0;
  --border:   rgba(0,0,0,0.08);
  --border2:  rgba(0,0,0,0.14);
  --text:     #0f172a;
  --text2:    #475569;
  --text3:    #94a3b8;
  --glow:     rgba(77,159,255,0.08);
  --ticker-bg: rgba(240,244,248,0.97);
  --buy:    #059669;
  --sell:   #dc2626;
  --info:   #2563eb;
  --warn:   #d97706;
}

/* ── RESET ───────────────────────────────────────────────────────── */
*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

html { scroll-behavior: smooth; }

body {
  background: var(--bg);
  color: var(--text);
  font-family: var(--font-body);
  font-size: 13px;
  line-height: 1.6;
  min-height: 100vh;
  transition: background 0.3s, color 0.3s;
}

[data-theme="dark"] body {
  background-image:
    radial-gradient(ellipse 70% 40% at 20% 0%, rgba(77,159,255,0.06) 0%, transparent 60%),
    radial-gradient(ellipse 50% 30% at 85% 90%, rgba(0,229,160,0.04) 0%, transparent 50%);
}

::-webkit-scrollbar { width: 4px; height: 4px; }
::-webkit-scrollbar-track { background: transparent; }
::-webkit-scrollbar-thumb { background: var(--text3); border-radius: 2px; }

/* ── APP ROOT ────────────────────────────────────────────────────── */
.app-root { min-height: 100vh; display: flex; flex-direction: column; }

/* ── TICKER BANNER ───────────────────────────────────────────────── */
.ticker-wrap {
  position: sticky;
  top: 0;
  z-index: 200;
  background: var(--ticker-bg);
  backdrop-filter: blur(12px);
  border-bottom: 1px solid var(--border);
  overflow: hidden;
  height: 34px;
  display: flex;
  align-items: center;
}
.ticker-inner {
  display: flex;
  align-items: center;
  white-space: nowrap;
  animation: ticker-scroll 40s linear infinite;
  gap: 60px;
}
.ticker-wrap:hover .ticker-inner { animation-play-state: paused; }
@keyframes ticker-scroll {
  from { transform: translateX(0); }
  to   { transform: translateX(-50%); }
}
.ticker-item {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  font-family: var(--font-mono);
  font-size: 11px;
  color: var(--text2);
  padding: 0 4px;
}
.ticker-item span { color: var(--warn); font-weight: 600; }
.ticker-sep { color: var(--text3); font-size: 10px; }

/* ── NAVBAR ──────────────────────────────────────────────────────── */
.navbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 24px;
  height: 58px;
  background: var(--bg2);
  border-bottom: 1px solid var(--border);
  position: sticky;
  top: 34px;
  z-index: 150;
  backdrop-filter: blur(12px);
}
.navbar-brand {
  display: flex;
  align-items: center;
  gap: 12px;
}
.brand-logo {
  font-family: var(--font-display);
  font-size: 22px;
  font-weight: 800;
  letter-spacing: -0.03em;
  line-height: 1;
}
.brand-logo .w { color: var(--info); }
.brand-logo .b { color: var(--text); }
.brand-tag {
  font-family: var(--font-mono);
  font-size: 9px;
  color: var(--text3);
  letter-spacing: 0.12em;
  border: 1px solid var(--border2);
  padding: 2px 7px;
  border-radius: 20px;
  text-transform: uppercase;
}
.navbar-center {
  display: flex;
  align-items: center;
  gap: 4px;
}
.nav-tab {
  padding: 6px 14px;
  border-radius: var(--radius-sm);
  font-size: 12px;
  font-weight: 500;
  color: var(--text2);
  cursor: pointer;
  border: none;
  background: transparent;
  transition: all 0.15s;
}
.nav-tab:hover { background: var(--surface2); color: var(--text); }
.nav-tab.active {
  background: var(--surface2);
  color: var(--text);
  border: 1px solid var(--border2);
}
.navbar-right {
  display: flex;
  align-items: center;
  gap: 10px;
}

/* Status pill */
.status-pill {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 4px 12px;
  border-radius: 20px;
  font-family: var(--font-mono);
  font-size: 10px;
  font-weight: 600;
  letter-spacing: 0.08em;
  border: 1px solid;
}
.status-pill.live {
  background: rgba(0,229,160,0.08);
  border-color: rgba(0,229,160,0.25);
  color: var(--buy);
}
.status-pill.stopped {
  background: rgba(255,77,109,0.08);
  border-color: rgba(255,77,109,0.2);
  color: var(--sell);
}
.status-pill.paused {
  background: rgba(245,166,35,0.08);
  border-color: rgba(245,166,35,0.25);
  color: var(--warn);
}
.pulse-dot {
  width: 6px; height: 6px;
  border-radius: 50%;
  background: currentColor;
}
.pulse-dot.live { animation: pulse 2s ease infinite; }
@keyframes pulse {
  0%,100% { opacity:1; box-shadow: 0 0 0 0 rgba(0,229,160,0.5); }
  50%      { opacity:0.7; box-shadow: 0 0 0 5px transparent; }
}

/* Balance chip */
.balance-chip {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
}
.balance-chip .bal {
  font-family: var(--font-display);
  font-size: 16px;
  font-weight: 700;
  color: var(--buy);
  line-height: 1;
}
.balance-chip .bal-label {
  font-family: var(--font-mono);
  font-size: 8px;
  color: var(--text3);
  letter-spacing: 0.1em;
}

/* User chip */
.user-chip {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 5px 12px 5px 6px;
  border-radius: 20px;
  background: var(--surface2);
  border: 1px solid var(--border);
  cursor: pointer;
  transition: all 0.15s;
}
.user-chip:hover { border-color: var(--border2); }
.user-avatar {
  width: 26px; height: 26px;
  border-radius: 50%;
  background: linear-gradient(135deg, var(--info), var(--purple));
  display: flex; align-items: center; justify-content: center;
  font-size: 11px; font-weight: 700; color: #fff;
}
.user-name { font-size: 12px; font-weight: 500; }

/* ── ICON BUTTON ─────────────────────────────────────────────────── */
.icon-btn {
  width: 34px; height: 34px;
  border-radius: var(--radius-sm);
  border: 1px solid var(--border);
  background: var(--surface2);
  color: var(--text2);
  display: flex; align-items: center; justify-content: center;
  cursor: pointer;
  font-size: 15px;
  transition: all 0.15s;
}
.icon-btn:hover { border-color: var(--border2); color: var(--text); }

/* ── BUTTONS ─────────────────────────────────────────────────────── */
.btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 8px 18px;
  border-radius: var(--radius-sm);
  font-family: var(--font-mono);
  font-size: 11px;
  font-weight: 500;
  letter-spacing: 0.04em;
  border: none;
  cursor: pointer;
  transition: all 0.15s;
  white-space: nowrap;
}
.btn:hover { opacity: 0.85; transform: translateY(-1px); }
.btn:active { transform: translateY(0); }
.btn:disabled { opacity: 0.4; cursor: not-allowed; transform: none !important; }
.btn-primary { background: var(--info); color: #fff; }
.btn-success { background: var(--buy); color: #000; font-weight: 700; }
.btn-danger  { background: rgba(255,77,109,0.15); color: var(--sell); border: 1px solid rgba(255,77,109,0.3); }
.btn-ghost   { background: var(--surface2); color: var(--text2); border: 1px solid var(--border); }
.btn-scan    { background: rgba(77,159,255,0.12); color: var(--info); border: 1px solid rgba(77,159,255,0.25); }
.btn-sm { padding: 5px 12px; font-size: 10px; }
.btn-xs { padding: 3px 9px; font-size: 10px; border-radius: 4px; }

/* ── CARDS ───────────────────────────────────────────────────────── */
.card {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  padding: 16px;
}
.card-sm {
  background: var(--surface2);
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  padding: 10px 12px;
}

/* ── TAGS ────────────────────────────────────────────────────────── */
.tag {
  display: inline-flex;
  align-items: center;
  padding: 2px 9px;
  border-radius: 4px;
  font-family: var(--font-mono);
  font-size: 10px;
  font-weight: 600;
  letter-spacing: 0.06em;
  border: 1px solid;
}
.tag-BUY  { background: rgba(0,229,160,0.1); color: var(--buy); border-color: rgba(0,229,160,0.25); }
.tag-SELL { background: rgba(255,77,109,0.1); color: var(--sell); border-color: rgba(255,77,109,0.25); }
.tag-HOLD { background: rgba(245,166,35,0.1); color: var(--warn); border-color: rgba(245,166,35,0.25); }
.tag-WIN  { background: rgba(0,229,160,0.1); color: var(--buy); border-color: rgba(0,229,160,0.2); }
.tag-LOSS { background: rgba(255,77,109,0.1); color: var(--sell); border-color: rgba(255,77,109,0.2); }
.tag-OPEN { background: rgba(77,159,255,0.1); color: var(--info); border-color: rgba(77,159,255,0.2); }

/* Leverage badge */
.lev-badge {
  display: inline-flex;
  align-items: center;
  padding: 1px 7px;
  border-radius: 20px;
  font-family: var(--font-mono);
  font-size: 10px;
  font-weight: 700;
  border: 1px solid;
}
.lev-100 { background: rgba(251,191,36,0.12); color: var(--gold); border-color: rgba(251,191,36,0.3); }
.lev-50  { background: rgba(167,139,250,0.12); color: var(--purple); border-color: rgba(167,139,250,0.3); }
.lev-20  { background: rgba(0,229,160,0.1); color: var(--buy); border-color: rgba(0,229,160,0.25); }
.lev-10  { background: rgba(77,159,255,0.1); color: var(--info); border-color: rgba(77,159,255,0.25); }

/* Bias badge */
.bias-badge {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 2px 8px;
  border-radius: 4px;
  font-family: var(--font-mono);
  font-size: 9px;
  font-weight: 600;
  letter-spacing: 0.06em;
  text-transform: uppercase;
}
.bias-bullish { background: rgba(0,229,160,0.08); color: var(--buy); }
.bias-bearish { background: rgba(255,77,109,0.08); color: var(--sell); }
.bias-neutral { background: rgba(255,255,255,0.05); color: var(--text3); }

/* ── TABLE ───────────────────────────────────────────────────────── */
.data-table { width: 100%; border-collapse: collapse; }
.data-table th {
  font-family: var(--font-mono);
  font-size: 9px;
  text-transform: uppercase;
  letter-spacing: 0.1em;
  color: var(--text3);
  padding: 8px 12px;
  text-align: left;
  border-bottom: 1px solid var(--border);
  font-weight: 400;
  white-space: nowrap;
}
.data-table td {
  padding: 9px 12px;
  border-bottom: 1px solid rgba(255,255,255,0.02);
  font-size: 12px;
  vertical-align: middle;
}
[data-theme="light"] .data-table td {
  border-bottom: 1px solid rgba(0,0,0,0.04);
}
.data-table tr:hover td { background: var(--surface2); }
.data-table .mono { font-family: var(--font-mono); font-size: 11px; }

/* ── STAT CARDS ──────────────────────────────────────────────────── */
.stat-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(110px, 1fr));
  gap: 8px;
}
.stat-card {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  padding: 14px;
  text-align: center;
  transition: border-color 0.2s;
}
.stat-card:hover { border-color: var(--border2); }
.stat-label {
  font-family: var(--font-mono);
  font-size: 9px;
  text-transform: uppercase;
  letter-spacing: 0.1em;
  color: var(--text3);
  margin-bottom: 6px;
}
.stat-value {
  font-family: var(--font-display);
  font-size: 18px;
  font-weight: 700;
  line-height: 1;
}

/* ── SIGNAL CARD ─────────────────────────────────────────────────── */
.signal-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(180px, 1fr));
  gap: 8px;
}
.signal-card {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  padding: 12px;
  cursor: pointer;
  transition: all 0.15s;
  position: relative;
  overflow: hidden;
}
.signal-card::before {
  content: '';
  position: absolute;
  top: 0; left: 0; right: 0;
  height: 2px;
  background: var(--border);
  transition: background 0.2s;
}
.signal-card.signal-BUY::before  { background: var(--buy); }
.signal-card.signal-SELL::before { background: var(--sell); }
.signal-card:hover { border-color: var(--border2); transform: translateY(-1px); }
.signal-card.selected { border-color: var(--info); box-shadow: 0 0 0 1px var(--info); }
.signal-asset {
  font-family: var(--font-display);
  font-size: 14px;
  font-weight: 700;
  margin-bottom: 2px;
}
.signal-asset .pair { font-size: 10px; color: var(--text3); font-family: var(--font-mono); font-weight: 400; }
.signal-price {
  font-family: var(--font-mono);
  font-size: 13px;
  font-weight: 500;
  margin-bottom: 8px;
}
.signal-stages {
  display: flex;
  gap: 3px;
  margin-bottom: 8px;
}
.stage-pill {
  flex: 1;
  height: 20px;
  border-radius: 3px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-family: var(--font-mono);
  font-size: 8px;
  font-weight: 600;
  letter-spacing: 0.06em;
  background: var(--surface2);
  color: var(--text3);
  border: 1px solid var(--border);
  transition: all 0.15s;
}
.stage-pill.done-BUY  { background: rgba(0,229,160,0.12); color: var(--buy); border-color: rgba(0,229,160,0.2); }
.stage-pill.done-SELL { background: rgba(255,77,109,0.1); color: var(--sell); border-color: rgba(255,77,109,0.2); }
.signal-reason {
  font-size: 10px;
  color: var(--text3);
  line-height: 1.4;
  min-height: 14px;
}
.signal-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-top: 8px;
}

/* ── POSITION CARD ───────────────────────────────────────────────── */
.position-card {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  padding: 14px;
  transition: border-color 0.2s;
}
.position-card.profit { border-color: rgba(0,229,160,0.2); }
.position-card.loss   { border-color: rgba(255,77,109,0.2); }
.pos-progress {
  height: 3px;
  background: var(--surface2);
  border-radius: 2px;
  margin: 10px 0;
  overflow: hidden;
}
.pos-progress-fill {
  height: 100%;
  border-radius: 2px;
  transition: width 0.6s ease;
}

/* ── MODAL ───────────────────────────────────────────────────────── */
.modal-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0,0,0,0.6);
  backdrop-filter: blur(6px);
  z-index: 500;
  display: flex;
  align-items: center;
  justify-content: center;
  animation: fadeIn 0.15s ease;
}
.modal {
  background: var(--bg2);
  border: 1px solid var(--border2);
  border-radius: var(--radius-xl);
  padding: 28px;
  width: 440px;
  max-width: 92vw;
  max-height: 90vh;
  overflow-y: auto;
  animation: slideUp 0.2s ease;
}
.modal-lg { width: 560px; }
.modal-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  margin-bottom: 20px;
}
.modal-title {
  font-family: var(--font-display);
  font-size: 20px;
  font-weight: 700;
}
.modal-subtitle {
  font-size: 12px;
  color: var(--text2);
  margin-top: 2px;
}

/* ── FORM ────────────────────────────────────────────────────────── */
.form-group { margin-bottom: 14px; }
.form-label {
  font-family: var(--font-mono);
  font-size: 10px;
  text-transform: uppercase;
  letter-spacing: 0.08em;
  color: var(--text3);
  margin-bottom: 6px;
  display: block;
}
.form-input {
  width: 100%;
  padding: 10px 14px;
  background: var(--surface);
  border: 1px solid var(--border2);
  border-radius: var(--radius-sm);
  color: var(--text);
  font-family: var(--font-mono);
  font-size: 12px;
  outline: none;
  transition: border-color 0.15s;
}
.form-input:focus { border-color: var(--info); }
.form-input::placeholder { color: var(--text3); }
.form-input-wrap { position: relative; }
.form-input-wrap .form-input { padding-right: 40px; }
.form-input-eye {
  position: absolute;
  right: 12px;
  top: 50%;
  transform: translateY(-50%);
  background: none;
  border: none;
  color: var(--text3);
  cursor: pointer;
  font-size: 14px;
  padding: 0;
}
.form-row { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }

/* ── INFO BOX ────────────────────────────────────────────────────── */
.info-box {
  padding: 10px 14px;
  border-radius: var(--radius-sm);
  font-size: 11px;
  line-height: 1.6;
}
.info-box-blue {
  background: rgba(77,159,255,0.06);
  border: 1px solid rgba(77,159,255,0.15);
  color: var(--text2);
}
.info-box-green {
  background: rgba(0,229,160,0.06);
  border: 1px solid rgba(0,229,160,0.15);
  color: var(--buy);
}
.info-box-red {
  background: rgba(255,77,109,0.06);
  border: 1px solid rgba(255,77,109,0.2);
  color: var(--sell);
}
.info-box-warn {
  background: rgba(245,166,35,0.06);
  border: 1px solid rgba(245,166,35,0.2);
  color: var(--warn);
}

/* ── TOAST ───────────────────────────────────────────────────────── */
.toast {
  position: fixed;
  bottom: 24px;
  right: 24px;
  z-index: 9999;
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 12px 20px;
  border-radius: var(--radius-md);
  font-family: var(--font-mono);
  font-size: 12px;
  max-width: 340px;
  animation: slideRight 0.25s ease;
  border: 1px solid;
}
.toast-icon { font-size: 14px; }
.toast-info    { background: var(--surface2); color: var(--info); border-color: rgba(77,159,255,0.3); }
.toast-success { background: rgba(0,229,160,0.1); color: var(--buy); border-color: rgba(0,229,160,0.3); }
.toast-error   { background: rgba(255,77,109,0.1); color: var(--sell); border-color: rgba(255,77,109,0.3); }
.toast-warn    { background: rgba(245,166,35,0.1); color: var(--warn); border-color: rgba(245,166,35,0.3); }

/* ── DISCLAIMER TICKER ───────────────────────────────────────────── */
.disclaimer-wrap {
  background: linear-gradient(90deg, rgba(255,77,109,0.08), rgba(245,166,35,0.08), rgba(255,77,109,0.08));
  border-bottom: 1px solid rgba(255,77,109,0.15);
  overflow: hidden;
  height: 28px;
  display: flex;
  align-items: center;
}
.disclaimer-inner {
  display: flex;
  align-items: center;
  white-space: nowrap;
  animation: ticker-scroll 60s linear infinite;
  gap: 80px;
}
.disclaimer-item {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-family: var(--font-mono);
  font-size: 10px;
  color: var(--warn);
  font-weight: 500;
}
.disclaimer-icon { font-size: 11px; }

/* ── AUTH PAGE ───────────────────────────────────────────────────── */
.auth-page {
  min-height: 100vh;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 24px;
  position: relative;
}
[data-theme="dark"] .auth-page::before {
  content: '';
  position: fixed;
  inset: 0;
  background:
    radial-gradient(ellipse 60% 50% at 50% 0%, rgba(77,159,255,0.1), transparent),
    radial-gradient(ellipse 40% 40% at 80% 100%, rgba(0,229,160,0.06), transparent);
  pointer-events: none;
}
.auth-card {
  background: var(--bg2);
  border: 1px solid var(--border2);
  border-radius: var(--radius-xl);
  padding: 36px;
  width: 420px;
  max-width: 100%;
  position: relative;
  z-index: 1;
}
.auth-logo {
  text-align: center;
  margin-bottom: 28px;
}
.auth-logo-text {
  font-family: var(--font-display);
  font-size: 36px;
  font-weight: 800;
  letter-spacing: -0.04em;
  line-height: 1;
  margin-bottom: 8px;
}
.auth-logo-text .w { color: var(--info); }
.auth-logo-text .b { color: var(--text); }
.auth-logo-sub {
  font-family: var(--font-mono);
  font-size: 11px;
  color: var(--text3);
  letter-spacing: 0.12em;
  text-transform: uppercase;
}
.auth-tabs {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 4px;
  background: var(--surface2);
  border-radius: var(--radius-sm);
  padding: 3px;
  margin-bottom: 24px;
}
.auth-tab {
  padding: 8px;
  border-radius: 4px;
  text-align: center;
  font-size: 12px;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.15s;
  border: none;
  background: transparent;
  color: var(--text2);
}
.auth-tab.active {
  background: var(--surface);
  color: var(--text);
  border: 1px solid var(--border2);
}
.auth-footer {
  text-align: center;
  margin-top: 20px;
  font-size: 11px;
  color: var(--text3);
}
.auth-footer a {
  color: var(--info);
  text-decoration: none;
}

/* ── SETTINGS PANEL ──────────────────────────────────────────────── */
.settings-section { margin-bottom: 24px; }
.settings-title {
  font-family: var(--font-mono);
  font-size: 10px;
  text-transform: uppercase;
  letter-spacing: 0.1em;
  color: var(--text3);
  margin-bottom: 12px;
  padding-bottom: 8px;
  border-bottom: 1px solid var(--border);
}
.settings-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 10px 0;
  border-bottom: 1px solid var(--border);
}
.settings-row:last-child { border-bottom: none; }
.settings-row-label { font-size: 13px; font-weight: 500; }
.settings-row-desc { font-size: 11px; color: var(--text3); margin-top: 1px; }

/* Toggle switch */
.toggle {
  position: relative;
  width: 40px;
  height: 22px;
  flex-shrink: 0;
}
.toggle input { display: none; }
.toggle-track {
  position: absolute;
  inset: 0;
  border-radius: 11px;
  background: var(--surface3);
  border: 1px solid var(--border2);
  cursor: pointer;
  transition: all 0.2s;
}
.toggle input:checked + .toggle-track { background: var(--info); border-color: var(--info); }
.toggle-thumb {
  position: absolute;
  width: 16px; height: 16px;
  border-radius: 50%;
  background: #fff;
  top: 2px; left: 2px;
  transition: transform 0.2s;
  pointer-events: none;
}
.toggle input:checked ~ .toggle-thumb { transform: translateX(18px); }

/* Theme selector */
.theme-selector {
  display: flex;
  gap: 6px;
}
.theme-btn {
  padding: 6px 14px;
  border-radius: var(--radius-sm);
  font-size: 11px;
  font-weight: 500;
  cursor: pointer;
  border: 1px solid var(--border);
  background: var(--surface2);
  color: var(--text2);
  transition: all 0.15s;
}
.theme-btn.active {
  border-color: var(--info);
  color: var(--info);
  background: rgba(77,159,255,0.08);
}

/* Color selector */
.color-picker {
  display: flex;
  gap: 8px;
}
.color-swatch {
  width: 22px; height: 22px;
  border-radius: 50%;
  cursor: pointer;
  border: 2px solid transparent;
  transition: border-color 0.15s;
}
.color-swatch.active { border-color: var(--text); }

/* ── PAGE LAYOUT ─────────────────────────────────────────────────── */
.page-body {
  flex: 1;
  padding: 20px 24px 40px;
  max-width: 1440px;
  margin: 0 auto;
  width: 100%;
}
.page-grid {
  display: grid;
  grid-template-columns: 1fr 290px;
  gap: 16px;
}

/* ── SECTION HEADER ──────────────────────────────────────────────── */
.section-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 12px;
}
.section-title {
  font-family: var(--font-mono);
  font-size: 10px;
  text-transform: uppercase;
  letter-spacing: 0.1em;
  color: var(--text3);
}
.section-sub {
  font-size: 10px;
  color: var(--text3);
  margin-top: 2px;
}

/* ── NEWS TICKER ─────────────────────────────────────────────────── */
.news-badge {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 12px;
  border-radius: var(--radius-sm);
  font-size: 11px;
  font-family: var(--font-mono);
}
.news-badge.blackout {
  background: rgba(255,77,109,0.1);
  border: 1px solid rgba(255,77,109,0.25);
  color: var(--sell);
}
.news-badge.clear {
  background: rgba(0,229,160,0.06);
  border: 1px solid rgba(0,229,160,0.15);
  color: var(--buy);
}

/* ── ANIMATIONS ──────────────────────────────────────────────────── */
@keyframes fadeIn  { from { opacity:0; } to { opacity:1; } }
@keyframes slideUp { from { opacity:0; transform:translateY(16px); } to { opacity:1; transform:translateY(0); } }
@keyframes slideRight { from { opacity:0; transform:translateX(20px); } to { opacity:1; transform:translateX(0); } }

.animate-in { animation: fadeIn 0.3s ease forwards; }

/* ── DIVIDER ─────────────────────────────────────────────────────── */
.glow-divider {
  height: 1px;
  background: linear-gradient(90deg, transparent, var(--info), transparent);
  opacity: 0.2;
  margin: 16px 0;
}

/* ── BUILT BY ────────────────────────────────────────────────────── */
.built-by {
  text-align: center;
  padding: 16px;
  font-family: var(--font-mono);
  font-size: 10px;
  color: var(--text3);
  letter-spacing: 0.08em;
  border-top: 1px solid var(--border);
}
.built-by span { color: var(--info); font-weight: 600; }

/* ── RESPONSIVE ──────────────────────────────────────────────────── */
@media (max-width: 900px) {
  .page-grid { grid-template-columns: 1fr; }
  .navbar-center { display: none; }
  .signal-grid { grid-template-columns: repeat(auto-fill, minmax(150px,1fr)); }
}
@media (max-width: 600px) {
  .page-body { padding: 12px 12px 40px; }
  .navbar { padding: 0 12px; }
  .stat-grid { grid-template-columns: repeat(4,1fr); }
}

/* ── SCROLLABLE TABLE ────────────────────────────────────────────── */
.table-wrap { overflow-x: auto; }

/* ── EMPTY STATE ─────────────────────────────────────────────────── */
.empty-state {
  text-align: center;
  padding: 40px 20px;
  color: var(--text3);
  font-size: 12px;
}
.empty-state .empty-icon { font-size: 32px; margin-bottom: 10px; opacity: 0.4; }

/* ── LEVERAGE GUIDE ──────────────────────────────────────────────── */
.lev-guide {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
  align-items: center;
}

/* ── RISK PANEL ──────────────────────────────────────────────────── */
.risk-panel { position: sticky; top: 100px; }
.reasoning-list {
  list-style: none;
  display: flex;
  flex-direction: column;
  gap: 6px;
  margin-top: 10px;
}
.reasoning-list li {
  display: flex;
  gap: 8px;
  font-size: 11px;
  color: var(--text2);
  line-height: 1.5;
}
.reasoning-list li::before {
  content: '→';
  color: var(--info);
  flex-shrink: 0;
  margin-top: 1px;
}

/* ── WATERMARK ───────────────────────────────────────────────────── */
[data-theme="dark"] .auth-page::after {
  content: 'WELTBOT';
  position: fixed;
  bottom: 40px;
  left: 50%;
  transform: translateX(-50%);
  font-family: var(--font-display);
  font-size: 120px;
  font-weight: 800;
  color: rgba(255,255,255,0.015);
  pointer-events: none;
  letter-spacing: -0.04em;
  user-select: none;
}

WBEOF
echo "  ✓ src/index.css"

cat > "$F/src/App.jsx" << 'WBEOF'
import { useState, useEffect } from "react";
import AuthPage   from "./pages/AuthPage";
import Dashboard  from "./pages/Dashboard";
import { AppCtx } from "./context/AppContext";

export default function App() {
  const [user,  setUser]  = useState(null);
  const [token, setToken] = useState(null);
  const [theme, setTheme] = useState(() => localStorage.getItem("wb_theme") || "dark");
  const [toast, setToast] = useState(null);
  const [booting, setBooting] = useState(true);

  // Restore session from localStorage
  useEffect(() => {
    const t = localStorage.getItem("wb_token");
    const u = localStorage.getItem("wb_user");
    if (t && u) {
      try {
        setToken(t);
        setUser(JSON.parse(u));
      } catch { clearSession(); }
    }
    setBooting(false);
  }, []);

  useEffect(() => {
    document.documentElement.setAttribute("data-theme", theme);
    localStorage.setItem("wb_theme", theme);
  }, [theme]);

  const setSession = (tok, usr) => {
    localStorage.setItem("wb_token", tok);
    localStorage.setItem("wb_user",  JSON.stringify(usr));
    setToken(tok);
    setUser(usr);
  };

  const clearSession = () => {
    localStorage.removeItem("wb_token");
    localStorage.removeItem("wb_user");
    setToken(null);
    setUser(null);
  };

  const showToast = (msg, type = "info", duration = 4000) => {
    setToast({ msg, type, id: Date.now() });
    setTimeout(() => setToast(null), duration);
  };

  const logout = () => {
    clearSession();
    showToast("Logged out");
  };

  if (booting) return (
    <div style={{ minHeight:"100vh", display:"flex", alignItems:"center", justifyContent:"center", background:"var(--bg)" }}>
      <div style={{ fontFamily:"var(--font-display)", fontSize:32, fontWeight:800 }}>
        <span style={{ color:"var(--info)" }}>WELT</span>BOT
      </div>
    </div>
  );

  return (
    <AppCtx.Provider value={{ user, setUser, token, setSession, clearSession, theme, setTheme, showToast, logout }}>
      <div className="app-root">
        {!user || !token ? <AuthPage /> : <Dashboard />}
        {toast && (
          <div className={`toast toast-${toast.type}`} key={toast.id}>
            <span className="toast-icon">
              {toast.type==="success"?"✓":toast.type==="error"?"✕":toast.type==="warn"?"⚠":"ℹ"}
            </span>
            {toast.msg}
          </div>
        )}
      </div>
    </AppCtx.Provider>
  );
}

WBEOF
echo "  ✓ src/App.jsx"

cat > "$F/src/context/AppContext.jsx" << 'WBEOF'
import { createContext, useContext } from "react";
export const AppCtx = createContext(null);
export const useApp = () => useContext(AppCtx);

WBEOF
echo "  ✓ src/context/AppContext.jsx"

cat > "$F/src/pages/AuthPage.jsx" << 'WBEOF'
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

WBEOF
echo "  ✓ src/pages/AuthPage.jsx"

cat > "$F/src/pages/Dashboard.jsx" << 'WBEOF'
import { useState, useEffect, useCallback } from "react";
import { useApp }       from "../context/AppContext";
import { makeApi }      from "../api";
import Navbar           from "../components/Navbar";
import DisclaimerBanner from "../components/DisclaimerBanner";
import OverviewTab      from "../components/OverviewTab";
import SignalsTab       from "../components/SignalsTab";
import TradesTab        from "../components/TradesTab";
import SettingsModal    from "../components/SettingsModal";
import BuiltBy          from "../components/BuiltBy";

export default function Dashboard() {
  const { token, showToast } = useApp();
  const api = makeApi(token);

  const [tab,           setTab]          = useState("overview");
  const [botStatus,     setBotStatus]    = useState(null);
  const [signals,       setSignals]      = useState([]);
  const [trades,        setTrades]       = useState([]);
  const [summary,       setSummary]      = useState(null);
  const [portfolio,     setPortfolio]    = useState(null);
  const [loading,       setLoading]      = useState(false);
  const [actionLoad,    setActionLoad]   = useState(false);
  const [lastUpdate,    setLastUpdate]   = useState(null);
  const [showSettings,  setShowSettings] = useState(false);
  const [backendDown,   setBackendDown]  = useState(false);

  const load = useCallback(async (silent = false) => {
    if (!silent) setLoading(true);
    try {
      const [status, sigs, trds, sum, port] = await Promise.all([
        api.getBotStatus().catch(() => null),
        api.getAllSignals().catch(() => []),
        api.getTrades().catch(() => []),
        api.getSummary().catch(() => null),
        api.getPortfolio().catch(() => null),
      ]);
      setBackendDown(false);
      if (status)  setBotStatus(status);
      if (sigs)    setSignals(Array.isArray(sigs) ? sigs : []);
      if (trds)    setTrades(Array.isArray(trds) ? trds : []);
      if (sum)     setSummary(sum);
      if (port)    setPortfolio(port);
      setLastUpdate(new Date().toLocaleTimeString());
    } catch {
      setBackendDown(true);
      if (!silent) showToast("Cannot reach Railway backend", "error");
    } finally { setLoading(false); }
  }, [token]);

  useEffect(() => {
    load();
    const t = setInterval(() => load(true), 30000);
    return () => clearInterval(t);
  }, [load]);

  const handleStart = async () => {
    setActionLoad(true);
    try { const r = await api.startBot(); showToast(r.message || "Bot started", "success"); setTimeout(() => load(true), 2000); }
    catch { showToast("Failed to start", "error"); }
    finally { setActionLoad(false); }
  };
  const handleStop = async () => {
    setActionLoad(true);
    try { await api.stopBot(); showToast("Bot stopped"); load(true); }
    catch { showToast("Failed to stop", "error"); }
    finally { setActionLoad(false); }
  };
  const handleScan = async () => {
    setActionLoad(true);
    showToast("Scanning markets…", "info");
    try { await api.scanNow(); setTimeout(() => load(true), 6000); }
    catch { showToast("Scan failed", "error"); }
    finally { setActionLoad(false); }
  };
  const handleCloseTrade = async (id) => {
    try {
      const r = await api.closeTrade(id);
      if (r.success) { showToast(`Closed · P&L: $${(r.pnl||0).toFixed(4)}`, "success"); load(true); }
      else showToast(r.error || "Close failed", "error");
    } catch { showToast("Close failed", "error"); }
  };
  const handleClearTrades = async () => {
    try {
      const r = await api.clearTrades();
      if (r.success) { showToast(`Cleared ${r.deleted} trades`, "success"); load(true); }
    } catch { showToast("Clear failed", "error"); }
  };

  const ctx = {
    botStatus, signals, trades, summary, portfolio,
    loading, actionLoad, lastUpdate, backendDown,
    handleStart, handleStop, handleScan,
    handleCloseTrade, handleClearTrades,
    refresh: load,
  };

  return (
    <div className="app-root">
      <DisclaimerBanner />
      <Navbar tab={tab} setTab={setTab} botStatus={botStatus}
        onSettings={() => setShowSettings(true)} ctx={ctx} />

      {backendDown && (
        <div style={{
          background:"rgba(255,77,109,0.08)", border:"1px solid rgba(255,77,109,0.2)",
          padding:"10px 24px", fontSize:11, color:"var(--sell)",
          fontFamily:"var(--font-mono)", display:"flex", alignItems:"center", gap:8,
        }}>
          <span>⚠</span>
          Backend unreachable — check Railway dashboard · Bot may still be running on server
          <button onClick={() => load()} style={{ marginLeft:"auto", fontSize:10, padding:"3px 10px",
            background:"rgba(255,77,109,0.1)", border:"1px solid rgba(255,77,109,0.3)",
            color:"var(--sell)", borderRadius:4, cursor:"pointer" }}>Retry</button>
        </div>
      )}

      <div className="page-body animate-in">
        {tab === "overview" && <OverviewTab {...ctx} />}
        {tab === "signals"  && <SignalsTab  {...ctx} />}
        {tab === "trades"   && <TradesTab   {...ctx} />}
      </div>
      <BuiltBy />
      {showSettings && <SettingsModal onClose={() => setShowSettings(false)} onRefresh={() => load(true)} />}
    </div>
  );
}

WBEOF
echo "  ✓ src/pages/Dashboard.jsx"

cat > "$F/src/components/Navbar.jsx" << 'WBEOF'
import { useApp } from "../context/AppContext";

export default function Navbar({ tab, setTab, botStatus, onSettings, ctx }) {
  const { user, logout } = useApp();
  const { handleStart, handleStop, handleScan, actionLoad, lastUpdate } = ctx;

  const isLive   = botStatus?.running && !botStatus?.paused;
  const isPaused = botStatus?.paused;
  const balance  = botStatus?.balance_usdt ?? 0;
  const statusLabel = isLive ? "LIVE" : isPaused ? "PAUSED" : "STOPPED";
  const statusClass = isLive ? "live"  : isPaused ? "paused" : "stopped";
  const initials = user?.name ? user.name.split(" ").map(n=>n[0]).join("").toUpperCase().slice(0,2) : "U";

  return (
    <nav className="navbar">
      <div className="navbar-brand">
        <div className="brand-logo"><span className="w">WELT</span><span className="b">BOT</span></div>
        <span className="brand-tag">v5.0</span>
        <div className={`status-pill ${statusClass}`}>
          <div className={`pulse-dot ${isLive?"live":""}`}/>
          {statusLabel}
        </div>
        {botStatus?.testnet && (
          <span style={{ fontSize:9, color:"var(--purple)", padding:"2px 8px", borderRadius:4,
            background:"rgba(167,139,250,0.1)", border:"1px solid rgba(167,139,250,0.25)",
            fontFamily:"var(--font-mono)", letterSpacing:"0.1em" }}>TESTNET</span>
        )}
      </div>

      <div className="navbar-center">
        {[["overview","📊 Overview"],["signals","📡 Signals"],["trades","📋 Trades"]].map(([t,l]) => (
          <button key={t} className={`nav-tab ${tab===t?"active":""}`} onClick={() => setTab(t)}>{l}</button>
        ))}
      </div>

      <div className="navbar-right">
        {lastUpdate && <span style={{ fontSize:10, color:"var(--text3)", fontFamily:"var(--font-mono)" }}>{lastUpdate}</span>}
        <div className="balance-chip">
          <span className="bal">${balance.toLocaleString(undefined,{minimumFractionDigits:2,maximumFractionDigits:2})}</span>
          <span className="bal-label">USDT</span>
        </div>
        {!isLive
          ? <button className="btn btn-success btn-sm" onClick={handleStart} disabled={actionLoad}>{actionLoad?"…":"▶ Start"}</button>
          : <button className="btn btn-danger  btn-sm" onClick={handleStop}  disabled={actionLoad}>{actionLoad?"…":"■ Stop"}</button>
        }
        <button className="btn btn-scan btn-sm" onClick={handleScan} disabled={actionLoad}>⟳ Scan</button>
        <button className="icon-btn" onClick={onSettings} title="Settings">⚙</button>
        <div className="user-chip">
          <div className="user-avatar">{initials}</div>
          <span className="user-name">{user?.name?.split(" ")[0] || "Trader"}</span>
        </div>
        <button className="icon-btn" onClick={logout} title="Sign out" style={{ fontSize:13 }}>⎋</button>
      </div>
    </nav>
  );
}

WBEOF
echo "  ✓ src/components/Navbar.jsx"

cat > "$F/src/components/DisclaimerBanner.jsx" << 'WBEOF'
const ITEMS = [
  "⚠ RISK WARNING: Crypto futures trading involves substantial risk — you may lose your entire capital",
  "💡 WeltBot is an algorithmic tool, not financial advice — always do your own research",
  "🔐 Your API keys are stored locally in your browser and never shared with any server",
  "📉 High leverage amplifies losses as well as gains — use risk management",
  "⚠ This platform is for educational purposes — trade on testnet before using real funds",
  "🤖 Past strategy performance does not guarantee future results",
  "💡 Never invest money you cannot afford to lose — set daily loss limits",
  "⚠ Cryptocurrency markets operate 24/7 and can be highly volatile",
];

export default function DisclaimerBanner() {
  const doubled = [...ITEMS, ...ITEMS];
  return (
    <div className="disclaimer-wrap">
      <div className="disclaimer-inner">
        {doubled.map((item, i) => (
          <span key={i} className="disclaimer-item">
            <span className="disclaimer-icon">{item.split(" ")[0]}</span>
            {item.slice(item.indexOf(" ") + 1)}
            <span style={{ color:"var(--text3)", margin:"0 10px" }}>|</span>
          </span>
        ))}
      </div>
    </div>
  );
}

WBEOF
echo "  ✓ src/components/DisclaimerBanner.jsx"

cat > "$F/src/components/OverviewTab.jsx" << 'WBEOF'
import { useState } from "react";
import SignalCard   from "./SignalCard";
import PositionCard from "./PositionCard";
import RiskPanel    from "./RiskPanel";

const getLev      = c => c>=98?100:c>=95?50:c>=90?20:10;
const getLevClass = c => c>=98?"lev-100":c>=95?"lev-50":c>=90?"lev-20":"lev-10";

export default function OverviewTab(props) {
  const { summary, portfolio, signals, botStatus, handleCloseTrade, loading } = props;
  const [selected, setSelected] = useState(null);

  const pnl       = summary?.total_pnl ?? 0;
  const wr        = summary?.win_rate  ?? 0;
  const positions = portfolio?.positions || [];
  const activeS   = signals.filter(s=>s.signal_data?.signal!=="HOLD").sort((a,b)=>(b.signal_data?.confidence||0)-(a.signal_data?.confidence||0));
  const holdS     = signals.filter(s=>s.signal_data?.signal==="HOLD");

  const stats = [
    {label:"Balance",    value:`$${(botStatus?.balance_usdt||0).toLocaleString(undefined,{minimumFractionDigits:2,maximumFractionDigits:2})}`, color:"var(--buy)"},
    {label:"Trades",     value:summary?.total??0,  color:"var(--text)"},
    {label:"Open",       value:summary?.open??0,   color:"var(--info)"},
    {label:"Wins",       value:summary?.wins??0,   color:"var(--buy)"},
    {label:"Losses",     value:summary?.losses??0, color:"var(--sell)"},
    {label:"Win Rate",   value:`${wr}%`,           color:wr>=50?"var(--buy)":"var(--sell)"},
    {label:"P&L",        value:`${pnl>=0?"+":""}$${Math.abs(pnl).toFixed(4)}`, color:pnl>=0?"var(--buy)":"var(--sell)"},
    {label:"Unrealized", value:`${(portfolio?.unrealized_pnl??0)>=0?"+":""}$${Math.abs(portfolio?.unrealized_pnl??0).toFixed(4)}`, color:(portfolio?.unrealized_pnl??0)>=0?"var(--buy)":"var(--sell)"},
  ];

  return (
    <div>
      {/* Stats */}
      <div className="stat-grid" style={{ marginBottom:16 }}>
        {stats.map(s=>(
          <div key={s.label} className="stat-card">
            <div className="stat-label">{s.label}</div>
            <div className="stat-value" style={{color:s.color,fontSize:15}}>{s.value}</div>
          </div>
        ))}
      </div>

      {/* Active setups badge */}
      {botStatus?.active_setups?.length>0 && (
        <div style={{display:"flex",gap:6,alignItems:"center",marginBottom:12,flexWrap:"wrap"}}>
          <span style={{fontSize:10,color:"var(--text3)",fontFamily:"var(--font-mono)"}}>L2 WATCHING:</span>
          {botStatus.active_setups.map(s=>(
            <span key={s} style={{fontSize:10,padding:"2px 9px",borderRadius:4,
              background:"rgba(167,139,250,0.1)",color:"var(--purple)",
              border:"1px solid rgba(167,139,250,0.2)",fontFamily:"var(--font-mono)"}}>
              {s.replace("/USDT","")}
            </span>
          ))}
          <span style={{fontSize:10,color:"var(--text3)"}}>· checking every 60s</span>
        </div>
      )}

      {/* Open positions */}
      {positions.length>0 && (
        <div style={{marginBottom:16}}>
          <div className="section-header">
            <div className="section-title">Open Positions — {positions.length}</div>
          </div>
          <div style={{display:"grid",gridTemplateColumns:"repeat(auto-fill,minmax(260px,1fr))",gap:10}}>
            {positions.map((p,i)=>(
              <PositionCard key={i} position={p} onClose={()=>handleCloseTrade(p.trade_id)}/>
            ))}
          </div>
        </div>
      )}

      {/* Main grid */}
      <div className="page-grid">
        <div>
          {/* Leverage guide */}
          <div style={{display:"flex",gap:6,alignItems:"center",marginBottom:12,flexWrap:"wrap"}}>
            <span style={{fontSize:10,color:"var(--text3)",fontFamily:"var(--font-mono)"}}>LEVERAGE:</span>
            {[["98%+ → 100x","lev-100"],["95%+ → 50x","lev-50"],["90-94% → 20x","lev-20"],["85-89% → 10x","lev-10"]].map(([l,c])=>(
              <span key={l} className={`lev-badge ${c}`}>{l}</span>
            ))}
          </div>

          {/* Signals header */}
          <div className="section-header" style={{marginBottom:12}}>
            <div>
              <div className="section-title">Structure Signals — {signals.length} assets</div>
              <div className="section-sub">BOS → Fib → OB → MA → Entry · HTF bias filter active</div>
            </div>
            <div style={{display:"flex",gap:4}}>
              {["BOS","Fib","OB","MA","Entry"].map(s=>(
                <span key={s} style={{fontSize:9,padding:"2px 8px",borderRadius:3,
                  background:"var(--surface2)",color:"var(--text3)",
                  border:"1px solid var(--border)",fontFamily:"var(--font-mono)"}}>{s}</span>
              ))}
            </div>
          </div>

          {activeS.length>0 && (
            <div style={{marginBottom:10}}>
              <div style={{fontSize:10,color:"var(--info)",fontFamily:"var(--font-mono)",marginBottom:6,letterSpacing:"0.06em"}}>✦ ACTIVE — {activeS.length}</div>
              <div className="signal-grid">
                {activeS.map(data=>(
                  <SignalCard key={data.signal_data?.symbol} data={data}
                    selected={selected?.signal_data?.symbol===data.signal_data?.symbol}
                    onSelect={setSelected} getLev={getLev} getLevClass={getLevClass}/>
                ))}
              </div>
            </div>
          )}

          <div className="signal-grid">
            {holdS.map(data=>(
              <SignalCard key={data.signal_data?.symbol} data={data}
                selected={selected?.signal_data?.symbol===data.signal_data?.symbol}
                onSelect={setSelected} getLev={getLev} getLevClass={getLevClass}/>
            ))}
          </div>

          {signals.length===0&&!loading&&(
            <div className="card"><div className="empty-state"><div className="empty-icon">📡</div>Warming signal cache — 30–60s on first load</div></div>
          )}
        </div>

        <div className="risk-panel"><RiskPanel selected={selected}/></div>
      </div>
    </div>
  );
}

WBEOF
echo "  ✓ src/components/OverviewTab.jsx"

cat > "$F/src/components/SignalsTab.jsx" << 'WBEOF'
import { useState } from "react";
import SignalCard from "./SignalCard";
import RiskPanel  from "./RiskPanel";

const getLev      = c => c>=98?100:c>=95?50:c>=90?20:10;
const getLevClass = c => c>=98?"lev-100":c>=95?"lev-50":c>=90?"lev-20":"lev-10";

export default function SignalsTab({ signals, botStatus, loading }) {
  const [selected, setSelected] = useState(null);
  const [filter,   setFilter]   = useState("all");
  const [sortBy,   setSortBy]   = useState("confidence");

  const counts = {
    all:    signals.length,
    active: signals.filter(s=>s.signal_data?.signal!=="HOLD").length,
    buy:    signals.filter(s=>s.signal_data?.signal==="BUY").length,
    sell:   signals.filter(s=>s.signal_data?.signal==="SELL").length,
    hold:   signals.filter(s=>s.signal_data?.signal==="HOLD").length,
  };

  const filtered = signals
    .filter(s => {
      const sig = s.signal_data?.signal;
      if (filter==="active") return sig!=="HOLD";
      if (filter==="buy")    return sig==="BUY";
      if (filter==="sell")   return sig==="SELL";
      if (filter==="hold")   return sig==="HOLD";
      return true;
    })
    .sort((a,b) => {
      if (sortBy==="confidence") return (b.signal_data?.confidence||0)-(a.signal_data?.confidence||0);
      if (sortBy==="price") return (b.signal_data?.market?.price||0)-(a.signal_data?.market?.price||0);
      return (a.signal_data?.symbol||"").localeCompare(b.signal_data?.symbol||"");
    });

  return (
    <div>
      <div style={{display:"flex",alignItems:"center",justifyContent:"space-between",marginBottom:16,flexWrap:"wrap",gap:10}}>
        <div>
          <div style={{fontFamily:"var(--font-display)",fontSize:20,fontWeight:700}}>Structure Signals</div>
          <div style={{fontSize:12,color:"var(--text2)",marginTop:2}}>{signals.length} assets · SMC v5 with HTF Bias</div>
        </div>
        {botStatus?.active_setups?.length>0 && (
          <div style={{display:"flex",gap:5,alignItems:"center",flexWrap:"wrap"}}>
            <span style={{fontSize:10,color:"var(--text3)",fontFamily:"var(--font-mono)"}}>L2:</span>
            {botStatus.active_setups.map(s=>(
              <span key={s} style={{fontSize:10,padding:"2px 9px",borderRadius:4,
                background:"rgba(167,139,250,0.1)",color:"var(--purple)",
                border:"1px solid rgba(167,139,250,0.2)",fontFamily:"var(--font-mono)"}}>
                {s.replace("/USDT","")}
              </span>
            ))}
          </div>
        )}
      </div>

      <div className="page-grid">
        <div>
          <div style={{display:"flex",gap:6,marginBottom:12,alignItems:"center",flexWrap:"wrap"}}>
            <div style={{display:"flex",gap:3}}>
              {[["all","All"],["active","Active"],["buy","Buy"],["sell","Sell"],["hold","Hold"]].map(([k,l])=>(
                <button key={k} onClick={()=>setFilter(k)} style={{
                  padding:"5px 11px",borderRadius:5,fontSize:11,cursor:"pointer",border:"1px solid",
                  background:filter===k?"var(--info)":"var(--surface2)",
                  color:filter===k?"#fff":"var(--text2)",
                  borderColor:filter===k?"var(--info)":"var(--border)",fontFamily:"var(--font-mono)",
                }}>{l} <span style={{opacity:0.7,fontSize:10}}>{counts[k]}</span></button>
              ))}
            </div>
            <div style={{marginLeft:"auto",display:"flex",alignItems:"center",gap:4}}>
              <span style={{fontSize:10,color:"var(--text3)"}}>Sort:</span>
              {[["confidence","Conf"],["price","Price"],["symbol","Name"]].map(([k,l])=>(
                <button key={k} onClick={()=>setSortBy(k)} style={{
                  padding:"4px 10px",borderRadius:4,fontSize:10,cursor:"pointer",border:"1px solid",
                  fontFamily:"var(--font-mono)",
                  background:sortBy===k?"var(--surface3)":"transparent",
                  color:sortBy===k?"var(--text)":"var(--text3)",
                  borderColor:sortBy===k?"var(--border2)":"transparent",
                }}>{l}</button>
              ))}
            </div>
          </div>

          {filtered.length===0&&!loading ? (
            <div className="card"><div className="empty-state"><div className="empty-icon">📡</div>No signals match filter</div></div>
          ) : (
            <div className="signal-grid">
              {filtered.map(data=>(
                <SignalCard key={data.signal_data?.symbol} data={data}
                  selected={selected?.signal_data?.symbol===data.signal_data?.symbol}
                  onSelect={setSelected} getLev={getLev} getLevClass={getLevClass}/>
              ))}
            </div>
          )}
        </div>
        <div className="risk-panel"><RiskPanel selected={selected}/></div>
      </div>
    </div>
  );
}

WBEOF
echo "  ✓ src/components/SignalsTab.jsx"

cat > "$F/src/components/TradesTab.jsx" << 'WBEOF'
import { useState } from "react";

const fmt = (v) => {
  if (!v && v!==0) return "—";
  if (Math.abs(v)>=10000) return `$${Number(v).toLocaleString(undefined,{maximumFractionDigits:0})}`;
  if (Math.abs(v)>=1) return `$${Number(v).toFixed(4)}`;
  if (Math.abs(v)>=0.01) return `$${Number(v).toFixed(5)}`;
  return `$${Number(v).toFixed(6)}`;
};

export default function TradesTab({ trades, handleCloseTrade, handleClearTrades }) {
  const [confirmClear,setConfirmClear] = useState(false);
  const [clearing,    setClearing]    = useState(false);
  const [filter,      setFilter]      = useState("all");
  const [search,      setSearch]      = useState("");

  const onClear = async () => {
    if (!confirmClear) { setConfirmClear(true); setTimeout(()=>setConfirmClear(false),4000); return; }
    setClearing(true);
    await handleClearTrades();
    setClearing(false); setConfirmClear(false);
  };

  const filtered = trades.filter(t => {
    const mf = filter==="all"?true:filter==="open"?t.outcome==="OPEN":filter==="win"?t.outcome==="WIN":t.outcome==="LOSS";
    const ms = search ? t.asset?.toLowerCase().includes(search.toLowerCase()) : true;
    return mf && ms;
  });

  const closed   = trades.filter(t=>t.outcome!=="OPEN");
  const wins     = closed.filter(t=>t.outcome==="WIN").length;
  const losses   = closed.filter(t=>t.outcome==="LOSS").length;
  const wr       = closed.length>0?((wins/closed.length)*100).toFixed(1):"0.0";
  const totalPnl = closed.reduce((s,t)=>s+(t.pnl||0),0);
  const openCnt  = trades.filter(t=>t.outcome==="OPEN").length;
  const avgWin   = wins>0   ? closed.filter(t=>t.outcome==="WIN").reduce((s,t)=>s+(t.pnl||0),0)/wins   : 0;
  const avgLoss  = losses>0 ? Math.abs(closed.filter(t=>t.outcome==="LOSS").reduce((s,t)=>s+(t.pnl||0),0)/losses) : 0;

  return (
    <div>
      <div style={{ display:"flex", alignItems:"center", justifyContent:"space-between", marginBottom:16, flexWrap:"wrap", gap:10 }}>
        <div>
          <div style={{ fontFamily:"var(--font-display)", fontSize:20, fontWeight:700 }}>Trade History</div>
          <div style={{ fontSize:12, color:"var(--text2)", marginTop:2 }}>
            {trades.length} total · {openCnt} open · {wins}W {losses}L
          </div>
        </div>
        {trades.length>0 && (
          <button onClick={onClear} disabled={clearing} style={{
            padding:"7px 14px", borderRadius:6, fontSize:11, border:"1px solid",
            cursor:"pointer", fontFamily:"var(--font-mono)",
            background:confirmClear?"rgba(255,77,109,0.15)":"var(--surface2)",
            color:confirmClear?"var(--sell)":"var(--text3)",
            borderColor:confirmClear?"rgba(255,77,109,0.35)":"var(--border)", transition:"all 0.2s",
          }}>
            {clearing?"Clearing…":confirmClear?"⚠ Confirm Clear":"Clear History"}
          </button>
        )}
      </div>

      {/* Stats */}
      <div style={{ display:"grid", gridTemplateColumns:"repeat(auto-fit,minmax(100px,1fr))", gap:8, marginBottom:16 }}>
        {[
          {label:"Total",    value:trades.length,                         color:"var(--text)"},
          {label:"Open",     value:openCnt,                               color:"var(--info)"},
          {label:"Wins",     value:wins,                                  color:"var(--buy)"},
          {label:"Losses",   value:losses,                                color:"var(--sell)"},
          {label:"Win Rate", value:`${wr}%`,                              color:parseFloat(wr)>=50?"var(--buy)":"var(--sell)"},
          {label:"Total P&L",value:`${totalPnl>=0?"+":""}$${Math.abs(totalPnl).toFixed(4)}`, color:totalPnl>=0?"var(--buy)":"var(--sell)"},
          {label:"Avg Win",  value:avgWin>0?`+$${avgWin.toFixed(4)}`:"—",color:"var(--buy)"},
          {label:"Avg Loss", value:avgLoss>0?`-$${avgLoss.toFixed(4)}`:"—",color:"var(--sell)"},
        ].map(s=>(
          <div key={s.label} className="stat-card">
            <div className="stat-label">{s.label}</div>
            <div className="stat-value" style={{color:s.color,fontSize:14}}>{s.value}</div>
          </div>
        ))}
      </div>

      {/* Filters */}
      <div style={{ display:"flex", gap:6, marginBottom:12, alignItems:"center", flexWrap:"wrap" }}>
        <div style={{ display:"flex", gap:3 }}>
          {[["all","All"],["open","Open"],["win","Wins"],["loss","Losses"]].map(([k,l])=>(
            <button key={k} onClick={()=>setFilter(k)} style={{
              padding:"5px 12px", borderRadius:5, fontSize:11, cursor:"pointer",
              border:"1px solid", fontFamily:"var(--font-mono)",
              background:filter===k?"var(--surface3)":"var(--surface2)",
              color:filter===k?"var(--text)":"var(--text3)",
              borderColor:filter===k?"var(--border2)":"var(--border)",
            }}>{l}</button>
          ))}
        </div>
        <input placeholder="Search asset…" value={search} onChange={e=>setSearch(e.target.value)}
          style={{ padding:"5px 12px", borderRadius:5, fontSize:11, background:"var(--surface2)",
            border:"1px solid var(--border)", color:"var(--text)", fontFamily:"var(--font-mono)",
            outline:"none", width:140 }} />
      </div>

      {/* Table */}
      <div className="card" style={{ padding:0 }}>
        {filtered.length===0 ? (
          <div className="empty-state">
            <div className="empty-icon">{trades.length===0?"📋":"🔍"}</div>
            {trades.length===0?"No trades yet — start the bot to begin":"No trades match the filter"}
          </div>
        ) : (
          <div className="table-wrap">
            <table className="data-table">
              <thead><tr>
                <th>#</th><th>Asset</th><th>Signal</th><th>Entry</th>
                <th>Stop</th><th>TP</th><th>Size</th><th>Conf</th>
                <th>Status</th><th>P&L</th><th>Date</th><th>Time</th><th>Closed</th><th></th>
              </tr></thead>
              <tbody>
                {filtered.map((t,i)=>{
                  const pnlColor=(t.pnl||0)>=0?"var(--buy)":"var(--sell)";
                  const lev=(t.confidence||0)>=98?100:(t.confidence||0)>=95?50:(t.confidence||0)>=90?20:10;
                  const levCls=(t.confidence||0)>=98?"lev-100":(t.confidence||0)>=95?"lev-50":(t.confidence||0)>=90?"lev-20":"lev-10";
                  return (
                    <tr key={i}>
                      <td style={{color:"var(--text3)",fontSize:10}}>{t.id||i+1}</td>
                      <td>
                        <span style={{fontFamily:"var(--font-display)",fontWeight:700,fontSize:13}}>{t.asset?.replace("/USDT","")}</span>
                        <span style={{fontSize:9,color:"var(--text3)"}}>/USDT</span>
                      </td>
                      <td>
                        <div style={{display:"flex",flexDirection:"column",gap:2}}>
                          <span className={`tag tag-${t.signal}`}>{t.signal}</span>
                          <span className={`lev-badge ${levCls}`}>{lev}x</span>
                        </div>
                      </td>
                      <td className="mono">{fmt(t.entry_price)}</td>
                      <td className="mono" style={{color:"var(--sell)"}}>{fmt(t.stop_loss)}</td>
                      <td className="mono" style={{color:"var(--buy)"}}>{fmt(t.take_profit)}</td>
                      <td className="mono" style={{color:"var(--text3)",fontSize:11}}>{t.position_sz?.toFixed(4)||"—"}</td>
                      <td style={{color:"var(--text2)",fontSize:11,fontFamily:"var(--font-mono)"}}>{t.confidence?.toFixed(1)||"—"}%</td>
                      <td><span className={`tag tag-${t.outcome}`}>{t.outcome}</span></td>
                      <td style={{fontFamily:"var(--font-mono)",fontSize:12,fontWeight:600,color:pnlColor}}>
                        {t.pnl!=null?`${t.pnl>=0?"+":""}$${t.pnl.toFixed(4)}`:"—"}
                      </td>
                      <td style={{fontSize:11,color:"var(--text2)",whiteSpace:"nowrap"}}>{t.date||"—"}</td>
                      <td style={{fontSize:11,color:"var(--text3)",whiteSpace:"nowrap",fontFamily:"var(--font-mono)"}}>{t.time||"—"}</td>
                      <td style={{fontSize:10,color:"var(--text3)",whiteSpace:"nowrap"}}>{t.closed_date?`${t.closed_date} ${t.closed_time||""}`:"—"}</td>
                      <td>{t.outcome==="OPEN"&&<button className="btn btn-danger btn-xs" onClick={()=>handleCloseTrade(t.id)}>Close</button>}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}

WBEOF
echo "  ✓ src/components/TradesTab.jsx"

cat > "$F/src/components/SignalCard.jsx" << 'WBEOF'
const fmtPrice = (v) => {
  if (!v || v === 0) return "$0.00";
  if (v >= 1000) return `$${v.toLocaleString(undefined,{maximumFractionDigits:2})}`;
  if (v >= 1)    return `$${v.toFixed(4)}`;
  return `$${v.toFixed(6)}`;
};

const STAGES = ["BOS","Fib","OB","MA","Entry"];

export default function SignalCard({ data, selected, onSelect, getLev, getLevClass }) {
  const sig   = data?.signal_data || {};
  const mkt   = sig.market || {};
  const sub   = sig.sub_scores || {};
  const bias  = sig.bias || {};
  const dir   = sig.signal;
  const price = mkt.price || 0;
  const conf  = sig.confidence || 0;
  const lev   = getLev(conf);
  const levCls= getLevClass(conf);

  const stageKeys  = ["bos","fib","ob","ma","entry"];
  const donePct    = stageKeys.filter(k => sub[k]).length;
  const biasColor  = bias.bias === "bullish" ? "var(--buy)" : bias.bias === "bearish" ? "var(--sell)" : "var(--text3)";

  return (
    <div
      className={`signal-card ${dir !== "HOLD" ? `signal-${dir}` : ""} ${selected ? "selected" : ""}`}
      onClick={() => onSelect(data)}
    >
      {/* Header */}
      <div style={{ display:"flex", justifyContent:"space-between", alignItems:"flex-start", marginBottom:6 }}>
        <div>
          <div className="signal-asset">
            {sig.symbol?.replace("/USDT","")}
            <span className="pair">/USDT</span>
          </div>
          <div className="signal-price">{fmtPrice(price)}</div>
        </div>
        <div style={{ display:"flex", flexDirection:"column", alignItems:"flex-end", gap:3 }}>
          <span className={`tag tag-${dir}`}>{dir}</span>
          {dir !== "HOLD" && (
            <span className={`lev-badge ${levCls}`}>{lev}x</span>
          )}
        </div>
      </div>

      {/* Stages */}
      <div className="signal-stages">
        {STAGES.map((s, i) => {
          const k    = stageKeys[i];
          const done = sub[k];
          return (
            <div key={s} className={`stage-pill ${done ? `done-${dir !== "HOLD" ? dir : "BUY"}` : ""}`}>
              {done ? "✓" : s}
            </div>
          );
        })}
      </div>

      {/* Bias */}
      {bias.bias && (
        <div style={{ display:"flex", gap:4, marginBottom:6 }}>
          <span style={{ fontSize:9, color:"var(--text3)", fontFamily:"var(--font-mono)" }}>BIAS:</span>
          <span style={{ fontSize:9, color: biasColor, fontFamily:"var(--font-mono)", fontWeight:600 }}>
            {(bias["4h"] || "").toUpperCase()} 4H · {(bias["1h"] || "").toUpperCase()} 1H
          </span>
        </div>
      )}

      {/* Reason */}
      <div className="signal-reason">{sig.reason || "Monitoring…"}</div>

      {/* Confidence bar */}
      {conf > 0 && (
        <div style={{ marginTop:8 }}>
          <div style={{ height:2, background:"var(--surface2)", borderRadius:1, overflow:"hidden" }}>
            <div style={{
              height:"100%", borderRadius:1,
              width:`${Math.min(100, ((conf-85)/15)*100)}%`,
              background: dir === "BUY" ? "var(--buy)" : "var(--sell)",
              transition:"width 0.4s ease",
            }}/>
          </div>
          <div style={{ display:"flex", justifyContent:"space-between", marginTop:3 }}>
            <span style={{ fontSize:9, color:"var(--text3)", fontFamily:"var(--font-mono)" }}>
              {conf.toFixed(1)}% conf
            </span>
            <span style={{ fontSize:9, color:"var(--text3)" }}>
              {donePct}/5 stages
            </span>
          </div>
        </div>
      )}
    </div>
  );
}

WBEOF
echo "  ✓ src/components/SignalCard.jsx"

cat > "$F/src/components/PositionCard.jsx" << 'WBEOF'
const fmt = (v) => {
  if (!v && v !== 0) return "—";
  if (Math.abs(v) >= 10000) return `$${Number(v).toLocaleString(undefined,{maximumFractionDigits:0})}`;
  if (Math.abs(v) >= 1)     return `$${Number(v).toFixed(4)}`;
  if (Math.abs(v) >= 0.01)  return `$${Number(v).toFixed(5)}`;
  return `$${Number(v).toFixed(6)}`;
};

export default function PositionCard({ position: p, onClose }) {
  const isProfit = (p.unrealized ?? 0) >= 0;
  const pnlColor = isProfit ? "var(--buy)" : "var(--sell)";
  const lev      = (p.confidence||0) >= 98 ? 100 : (p.confidence||0) >= 95 ? 50 : (p.confidence||0) >= 90 ? 20 : 10;
  const levCls   = (p.confidence||0) >= 98 ? "lev-100" : (p.confidence||0) >= 95 ? "lev-50" : (p.confidence||0) >= 90 ? "lev-20" : "lev-10";

  const range    = (p.tp || 0) - (p.sl || 0);
  const progress = range !== 0
    ? Math.min(100, Math.max(0, ((p.current || 0) - (p.sl || 0)) / range * 100))
    : 0;

  return (
    <div className="position-card" style={{
      border: `1px solid ${isProfit ? "rgba(0,229,160,0.2)" : "rgba(255,77,109,0.2)"}`,
      borderRadius: "var(--radius-md)",
      padding: 14,
      background: "var(--surface)",
    }}>
      {/* Header */}
      <div style={{ display:"flex", justifyContent:"space-between", alignItems:"flex-start", marginBottom:10 }}>
        <div>
          <div style={{ display:"flex", alignItems:"center", gap:7, marginBottom:3 }}>
            <span style={{ fontFamily:"var(--font-display)", fontSize:15, fontWeight:700 }}>
              {p.asset?.replace("/USDT","")}
            </span>
            <span className={`tag tag-${p.signal}`}>{p.signal}</span>
            <span className={`lev-badge ${levCls}`}>{lev}x</span>
          </div>
          <div style={{ fontSize:10, color:"var(--text3)", fontFamily:"var(--font-mono)" }}>
            {(p.confidence||0).toFixed(1)}% confidence
          </div>
        </div>
        <div style={{ textAlign:"right" }}>
          <div style={{ fontFamily:"var(--font-display)", fontSize:20, fontWeight:700, color:pnlColor }}>
            {isProfit ? "+" : ""}{(p.pnl_pct||0).toFixed(3)}%
          </div>
          <div style={{ fontSize:11, color:pnlColor, fontFamily:"var(--font-mono)" }}>
            {(p.unrealized||0) >= 0 ? "+" : ""}${(p.unrealized||0).toFixed(4)}
          </div>
        </div>
      </div>

      {/* Price grid */}
      <div style={{ display:"grid", gridTemplateColumns:"1fr 1fr", gap:6, marginBottom:10 }}>
        {[["Entry",fmt(p.entry),""],["Current",fmt(p.current),""],
          ["Stop",fmt(p.sl),"var(--sell)"],["Target",fmt(p.tp),"var(--buy)"]].map(([l,v,c])=>(
          <div key={l} style={{ background:"var(--surface2)", borderRadius:6, padding:"7px 10px", border:"1px solid var(--border)" }}>
            <div style={{ fontSize:9, color:"var(--text3)", fontFamily:"var(--font-mono)", marginBottom:2 }}>{l}</div>
            <div style={{ fontSize:11, fontFamily:"var(--font-mono)", color:c||"var(--text)" }}>{v}</div>
          </div>
        ))}
      </div>

      {/* Progress bar */}
      <div style={{ height:4, background:"var(--surface2)", borderRadius:2, marginBottom:4, overflow:"hidden" }}>
        <div style={{
          height:"100%", borderRadius:2, width:`${progress}%`,
          background: isProfit ? "var(--buy)" : "var(--sell)",
          boxShadow: isProfit ? "0 0 6px rgba(0,229,160,0.5)" : "0 0 6px rgba(255,77,109,0.5)",
          transition: "width 0.6s ease",
        }}/>
      </div>
      <div style={{ display:"flex", justifyContent:"space-between", marginBottom:10, fontSize:9, color:"var(--text3)" }}>
        <span>SL</span>
        <span>{progress.toFixed(0)}% to TP</span>
        <span>TP</span>
      </div>

      {/* Close button */}
      <button
        onClick={onClose}
        style={{
          width:"100%", padding:"7px", borderRadius:6, fontSize:11,
          background:"rgba(255,77,109,0.1)", color:"var(--sell)",
          border:"1px solid rgba(255,77,109,0.25)", cursor:"pointer",
          fontFamily:"var(--font-mono)", transition:"all 0.15s",
        }}
        onMouseOver={e => e.target.style.background="rgba(255,77,109,0.2)"}
        onMouseOut={e => e.target.style.background="rgba(255,77,109,0.1)"}
      >
        ✕ Close Position Manually
      </button>
    </div>
  );
}

WBEOF
echo "  ✓ src/components/PositionCard.jsx"

cat > "$F/src/components/RiskPanel.jsx" << 'WBEOF'
const fmtPrice = (v) => {
  if (!v) return "—";
  if (v >= 1000) return `$${v.toLocaleString(undefined,{maximumFractionDigits:2})}`;
  if (v >= 1)    return `$${Number(v).toFixed(4)}`;
  return `$${Number(v).toFixed(6)}`;
};

export default function RiskPanel({ selected }) {
  if (!selected) {
    return (
      <div className="card risk-panel" style={{ textAlign:"center" }}>
        <div style={{ fontSize:24, marginBottom:10, opacity:0.3 }}>📐</div>
        <div style={{ fontSize:12, color:"var(--text3)", lineHeight:1.6 }}>
          Click any signal card to see its full setup analysis
        </div>
      </div>
    );
  }

  const sig   = selected.signal_data || {};
  const risk  = selected.risk_plan   || {};
  const mkt   = sig.market  || {};
  const bias  = sig.bias    || {};
  const sl_tp = sig.sl_tp   || {};
  const bos   = sig.bos     || {};
  const fib   = sig.fib     || {};
  const ob    = sig.ob      || {};
  const dir   = sig.signal;

  const reasoning = Array.isArray(sig.reasoning) ? sig.reasoning : [];
  const lev = sig.confidence >= 98 ? 100 : sig.confidence >= 95 ? 50 : sig.confidence >= 90 ? 20 : 10;
  const levCls = sig.confidence >= 98 ? "lev-100" : sig.confidence >= 95 ? "lev-50" : sig.confidence >= 90 ? "lev-20" : "lev-10";

  return (
    <div className="card risk-panel">
      {/* Header */}
      <div style={{ display:"flex", justifyContent:"space-between", alignItems:"center", marginBottom:14 }}>
        <div>
          <div style={{ fontFamily:"var(--font-display)", fontSize:16, fontWeight:700 }}>
            {sig.symbol?.replace("/USDT","")} <span style={{ fontWeight:400, fontSize:12, color:"var(--text3)" }}>/USDT</span>
          </div>
          <div style={{ fontSize:12, fontFamily:"var(--font-mono)", marginTop:2 }}>
            {fmtPrice(mkt.price)}
          </div>
        </div>
        <div style={{ display:"flex", flexDirection:"column", alignItems:"flex-end", gap:4 }}>
          <span className={`tag tag-${dir}`}>{dir}</span>
          {sig.confidence > 0 && <span className={`lev-badge ${levCls}`}>{lev}x</span>}
        </div>
      </div>

      {/* HTF Bias */}
      {bias.bias && (
        <div className="card-sm" style={{ marginBottom:12 }}>
          <div style={{ fontSize:9, color:"var(--text3)", fontFamily:"var(--font-mono)", marginBottom:6 }}>HTF DIRECTIONAL BIAS</div>
          <div style={{ display:"flex", gap:6 }}>
            {[["4H",bias["4h"]],["1H",bias["1h"]]].map(([tf,b]) => (
              <div key={tf} style={{ flex:1, textAlign:"center", padding:"6px 0",
                borderRadius:4, background:"var(--surface3)",
                border:`1px solid ${b==="bullish"?"rgba(0,229,160,0.2)":b==="bearish"?"rgba(255,77,109,0.2)":"var(--border)"}`,
              }}>
                <div style={{ fontSize:9, color:"var(--text3)", fontFamily:"var(--font-mono)" }}>{tf}</div>
                <div style={{ fontSize:11, fontWeight:700, fontFamily:"var(--font-mono)",
                  color:b==="bullish"?"var(--buy)":b==="bearish"?"var(--sell)":"var(--text3)",
                }}>
                  {(b||"neutral").toUpperCase()}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Key levels */}
      {(sl_tp.stop_loss || risk.stop_loss) && (
        <div className="card-sm" style={{ marginBottom:12 }}>
          <div style={{ fontSize:9, color:"var(--text3)", fontFamily:"var(--font-mono)", marginBottom:6 }}>KEY LEVELS</div>
          <div style={{ display:"flex", flexDirection:"column", gap:5 }}>
            {[
              ["Entry",   fmtPrice(mkt.price),           "var(--text)"],
              ["Stop Loss",fmtPrice(sl_tp.stop_loss||risk.stop_loss), "var(--sell)"],
              ["Take Profit",fmtPrice(sl_tp.take_profit||risk.take_profit), "var(--buy)"],
              ["Risk",    sl_tp.risk_pct ? `${sl_tp.risk_pct}%` : "—", "var(--warn)"],
              ["R:R",     sl_tp.rr ? `1:${sl_tp.rr}` : "1:2", "var(--info)"],
            ].map(([l,v,c]) => (
              <div key={l} style={{ display:"flex", justifyContent:"space-between" }}>
                <span style={{ fontSize:11, color:"var(--text3)" }}>{l}</span>
                <span style={{ fontSize:11, fontFamily:"var(--font-mono)", color:c, fontWeight:500 }}>{v}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Confluence zones */}
      {fib.zone_low && (
        <div className="card-sm" style={{ marginBottom:12 }}>
          <div style={{ fontSize:9, color:"var(--text3)", fontFamily:"var(--font-mono)", marginBottom:6 }}>CONFLUENCE ZONES</div>
          <div style={{ display:"flex", flexDirection:"column", gap:4 }}>
            <div style={{ display:"flex", justifyContent:"space-between" }}>
              <span style={{ fontSize:10, color:"var(--text3)" }}>Fib 0.5–0.618</span>
              <span style={{ fontSize:10, fontFamily:"var(--font-mono)", color:"var(--purple)" }}>
                {fmtPrice(fib.zone_low)}–{fmtPrice(fib.zone_high)}
              </span>
            </div>
            {ob.ob_low && (
              <div style={{ display:"flex", justifyContent:"space-between" }}>
                <span style={{ fontSize:10, color:"var(--text3)" }}>Order Block</span>
                <span style={{ fontSize:10, fontFamily:"var(--font-mono)", color:"var(--info)" }}>
                  {fmtPrice(ob.ob_low)}–{fmtPrice(ob.ob_high)}
                </span>
              </div>
            )}
          </div>
        </div>
      )}

      {/* Reasoning */}
      {reasoning.length > 0 && (
        <div>
          <div style={{ fontSize:9, color:"var(--text3)", fontFamily:"var(--font-mono)", marginBottom:6 }}>ANALYSIS</div>
          <ul className="reasoning-list">
            {reasoning.map((r, i) => <li key={i}>{r}</li>)}
          </ul>
        </div>
      )}

      {/* Confidence meter */}
      {sig.confidence > 0 && (
        <div style={{ marginTop:14 }}>
          <div style={{ display:"flex", justifyContent:"space-between", marginBottom:4 }}>
            <span style={{ fontSize:9, color:"var(--text3)", fontFamily:"var(--font-mono)" }}>CONFIDENCE</span>
            <span style={{ fontSize:11, fontFamily:"var(--font-mono)", color:"var(--text)", fontWeight:600 }}>
              {sig.confidence?.toFixed(1)}%
            </span>
          </div>
          <div style={{ height:6, background:"var(--surface2)", borderRadius:3, overflow:"hidden" }}>
            <div style={{
              height:"100%", borderRadius:3,
              width:`${((sig.confidence-85)/15)*100}%`,
              background:`linear-gradient(90deg, var(--info), ${dir==="BUY"?"var(--buy)":"var(--sell)"})`,
            }}/>
          </div>
          <div style={{ display:"flex", justifyContent:"space-between", marginTop:3, fontSize:9, color:"var(--text3)" }}>
            <span>85%</span><span>92.5%</span><span>100%</span>
          </div>
        </div>
      )}
    </div>
  );
}

WBEOF
echo "  ✓ src/components/RiskPanel.jsx"

cat > "$F/src/components/SettingsModal.jsx" << 'WBEOF'
import { useState, useEffect } from "react";
import { useApp }  from "../context/AppContext";
import { authApi, makeApi } from "../api";

export default function SettingsModal({ onClose, onRefresh }) {
  const { user, setUser, token, theme, setTheme, showToast, logout } = useApp();
  const api = makeApi(token);

  const [section,    setSection]    = useState("apikeys");
  const [apiKey,     setApiKey]     = useState("");
  const [apiSecret,  setApiSecret]  = useState("");
  const [showKey,    setShowKey]    = useState(false);
  const [showSec,    setShowSec]    = useState(false);
  const [saving,     setSaving]     = useState(false);
  const [keyStatus,  setKeyStatus]  = useState(null);
  const [testnet,    setTestnet]    = useState(user?.testnet ?? true);
  const [togglingNet,setTogglingNet]= useState(false);
  const [riskPct,    setRiskPct]    = useState("1.0");
  const [maxTrades,  setMaxTrades]  = useState("3");
  const [minConf,    setMinConf]    = useState("85");
  const [dailyLimit, setDailyLimit] = useState("5");
  const [savingBot,  setSavingBot]  = useState(false);
  const [editName,   setEditName]   = useState(user?.name || "");

  useEffect(() => {
    authApi.getKeyStat(token).then(s => { setKeyStatus(s); setTestnet(s.testnet ?? true); }).catch(() => {});
    api.getBotSettings?.().then(s => {
      if (s) {
        setRiskPct(String(s.risk_pct || 1));
        setMaxTrades(String(s.max_trades || 3));
        setMinConf(String(s.min_conf || 85));
        setDailyLimit(String(s.daily_limit || 5));
      }
    }).catch(() => {});
  }, [token]);

  const saveApiKeys = async () => {
    if (!apiKey.trim() || !apiSecret.trim()) { showToast("Both keys are required", "error"); return; }
    setSaving(true);
    try {
      const r = await authApi.saveKeys(token, apiKey.trim(), apiSecret.trim());
      if (r.success) {
        showToast(r.message, "success");
        setApiKey(""); setApiSecret("");
        const s = await authApi.getKeyStat(token);
        setKeyStatus(s);
        const me = await authApi.getMe(token);
        setUser(me);
        localStorage.setItem("wb_user", JSON.stringify(me));
        onRefresh();
      } else {
        showToast(r.error || "Failed", "error");
      }
    } catch (e) { showToast(e.message || "Error", "error"); }
    finally { setSaving(false); }
  };

  const toggleNetwork = async (isTestnet) => {
    setTogglingNet(true);
    try {
      const r = await authApi.toggleNet(token, isTestnet);
      if (r.success) {
        setTestnet(isTestnet);
        const me = { ...user, testnet: isTestnet };
        setUser(me);
        localStorage.setItem("wb_user", JSON.stringify(me));
        showToast(r.message, "success");
        onRefresh();
      }
    } catch (e) { showToast(e.message || "Error", "error"); }
    finally { setTogglingNet(false); }
  };

  const saveBotSettings = async () => {
    setSavingBot(true);
    try {
      const r = await api.updateBotSettings({
        risk_pct: parseFloat(riskPct), max_trades: parseInt(maxTrades),
        min_conf: parseFloat(minConf), daily_limit: parseFloat(dailyLimit),
      });
      if (r.success) showToast("Settings applied to bot!", "success");
      else showToast(r.error || "Failed", "error");
    } catch (e) { showToast(e.message, "error"); }
    finally { setSavingBot(false); }
  };

  const saveName = async () => {
    if (!editName.trim()) return;
    try {
      await authApi.updateName(token, editName.trim());
      const me = { ...user, name: editName.trim() };
      setUser(me);
      localStorage.setItem("wb_user", JSON.stringify(me));
      showToast("Name updated", "success");
    } catch (e) { showToast(e.message, "error"); }
  };

  const sections = [
    { key:"apikeys",    icon:"🔑", label:"API Keys" },
    { key:"network",    icon:"🌐", label:"Testnet / Mainnet" },
    { key:"bot",        icon:"🤖", label:"Bot Settings" },
    { key:"appearance", icon:"🎨", label:"Appearance" },
    { key:"account",    icon:"👤", label:"Account" },
    { key:"risk",       icon:"🛡", label:"Risk Guide" },
    { key:"about",      icon:"ℹ",  label:"About" },
  ];

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal modal-lg" onClick={e => e.stopPropagation()}
        style={{ padding:0, display:"flex", flexDirection:"column", width:580, maxHeight:"90vh" }}>

        <div style={{ padding:"20px 24px 16px", borderBottom:"1px solid var(--border)", display:"flex", justifyContent:"space-between", alignItems:"center" }}>
          <div>
            <div className="modal-title">Settings</div>
            <div className="modal-subtitle">Logged in as {user?.email}</div>
          </div>
          <button className="icon-btn" onClick={onClose}>✕</button>
        </div>

        <div style={{ display:"flex", flex:1, overflow:"hidden" }}>
          <div style={{ width:160, borderRight:"1px solid var(--border)", padding:"10px 8px", display:"flex", flexDirection:"column", gap:2, flexShrink:0 }}>
            {sections.map(s => (
              <button key={s.key} onClick={() => setSection(s.key)} style={{
                display:"flex", alignItems:"center", gap:8, padding:"8px 10px",
                borderRadius:6, border:"none", cursor:"pointer", textAlign:"left",
                fontSize:12, fontWeight:500, fontFamily:"var(--font-body)",
                background:section===s.key?"var(--surface2)":"transparent",
                color:section===s.key?"var(--text)":"var(--text2)",
              }}>
                <span style={{ fontSize:14 }}>{s.icon}</span>{s.label}
              </button>
            ))}
            <div style={{ flex:1 }} />
            <button onClick={logout} style={{
              display:"flex", alignItems:"center", gap:8, padding:"8px 10px",
              borderRadius:6, border:"none", cursor:"pointer", textAlign:"left",
              fontSize:12, fontFamily:"var(--font-body)", background:"transparent",
              color:"var(--sell)", marginTop:8,
            }}>
              <span>⎋</span> Sign Out
            </button>
          </div>

          <div style={{ flex:1, padding:"20px 24px", overflowY:"auto" }}>

            {section === "apikeys" && (
              <div>
                <div className="settings-title">Binance API Keys</div>
                {keyStatus && (
                  <div className={`info-box ${keyStatus.has_keys?"info-box-green":"info-box-red"}`} style={{ marginBottom:14 }}>
                    {keyStatus.has_keys ? `✓ Connected — Key: ${keyStatus.key_preview}` : "✗ No keys — bot cannot trade without them"}
                  </div>
                )}
                <div className="info-box info-box-blue" style={{ marginBottom:14, fontSize:11 }}>
                  <strong>Demo Trading:</strong> Get keys from <span style={{ color:"var(--info)" }}>demo-fapi.binance.com</span><br/>
                  Account → API Management → Create key → Copy API Key + Secret Key.<br/><br/>
                  <strong>Live Trading:</strong> Binance.com → Profile → API Management → Enable Futures only.
                </div>
                <div className="form-group">
                  <label className="form-label">API Key</label>
                  <div className="form-input-wrap">
                    <input className="form-input" type={showKey?"text":"password"} value={apiKey}
                      onChange={e => setApiKey(e.target.value)} placeholder="Paste Binance API key" />
                    <button className="form-input-eye" onClick={() => setShowKey(!showKey)}>{showKey?"○":"●"}</button>
                  </div>
                </div>
                <div className="form-group">
                  <label className="form-label">Secret Key</label>
                  <div className="form-input-wrap">
                    <input className="form-input" type={showSec?"text":"password"} value={apiSecret}
                      onChange={e => setApiSecret(e.target.value)} placeholder="Paste Binance secret key" />
                    <button className="form-input-eye" onClick={() => setShowSec(!showSec)}>{showSec?"○":"●"}</button>
                  </div>
                </div>
                <button className="btn btn-primary" style={{ width:"100%", justifyContent:"center" }}
                  onClick={saveApiKeys} disabled={saving}>
                  {saving ? "Saving & Testing Connection…" : "Save & Connect API Keys"}
                </button>
                <div className="info-box info-box-warn" style={{ marginTop:12 }}>
                  🔒 Keys are encrypted with AES and stored in the server database. They are never exposed in plain text.
                </div>
              </div>
            )}

            {section === "network" && (
              <div>
                <div className="settings-title">Trading Network</div>
                <div className="info-box info-box-blue" style={{ marginBottom:16 }}>
                  Switch between demo trading (testnet) and real money (mainnet). Your API keys must match the selected mode.
                </div>
                <div style={{ display:"grid", gridTemplateColumns:"1fr 1fr", gap:12, marginBottom:16 }}>
                  {[
                    { label:"🧪 Testnet (Demo)", desc:"Virtual funds · Zero real risk · Perfect for testing and learning", val:true },
                    { label:"🔴 Mainnet (Live)", desc:"Real money · Real profits and losses · Only when confident", val:false },
                  ].map(({ label, desc, val }) => (
                    <div key={String(val)} onClick={() => !togglingNet && toggleNetwork(val)} style={{
                      padding:16, borderRadius:10, cursor:togglingNet?"not-allowed":"pointer",
                      border:`2px solid ${testnet===val?"var(--info)":"var(--border)"}`,
                      background:testnet===val?"rgba(77,159,255,0.06)":"var(--surface2)",
                      transition:"all 0.15s",
                    }}>
                      <div style={{ fontSize:14, fontWeight:700, marginBottom:6 }}>{label}</div>
                      <div style={{ fontSize:11, color:"var(--text2)", lineHeight:1.5 }}>{desc}</div>
                      {testnet===val && <div style={{ marginTop:8, fontSize:10, color:"var(--info)", fontFamily:"var(--font-mono)" }}>● CURRENTLY ACTIVE</div>}
                    </div>
                  ))}
                </div>
                {!testnet && (
                  <div className="info-box info-box-red">
                    ⚠ MAINNET is ACTIVE. Real USDT is at risk. Make sure your API keys are from Binance.com (not demo-fapi). The bot will trade your real futures balance.
                  </div>
                )}
                {testnet && (
                  <div className="info-box info-box-green">
                    ✓ Testnet is active. All trades use virtual funds. Safe to experiment.
                  </div>
                )}
              </div>
            )}

            {section === "bot" && (
              <div>
                <div className="settings-title">Trading Parameters</div>
                <div className="form-row" style={{ marginBottom:12 }}>
                  <div className="form-group" style={{ marginBottom:0 }}>
                    <label className="form-label">Risk per Trade (%)</label>
                    <input className="form-input" type="number" min="0.1" max="5" step="0.1"
                      value={riskPct} onChange={e => setRiskPct(e.target.value)} />
                    <div style={{ fontSize:10, color:"var(--text3)", marginTop:4 }}>Recommended: 1% · Never exceed 2%</div>
                  </div>
                  <div className="form-group" style={{ marginBottom:0 }}>
                    <label className="form-label">Max Open Positions</label>
                    <input className="form-input" type="number" min="1" max="10"
                      value={maxTrades} onChange={e => setMaxTrades(e.target.value)} />
                    <div style={{ fontSize:10, color:"var(--text3)", marginTop:4 }}>Recommended: 3</div>
                  </div>
                </div>
                <div className="form-row" style={{ marginBottom:16 }}>
                  <div className="form-group" style={{ marginBottom:0 }}>
                    <label className="form-label">Min Confidence (%)</label>
                    <input className="form-input" type="number" min="70" max="99"
                      value={minConf} onChange={e => setMinConf(e.target.value)} />
                    <div style={{ fontSize:10, color:"var(--text3)", marginTop:4 }}>Higher = fewer, better trades</div>
                  </div>
                  <div className="form-group" style={{ marginBottom:0 }}>
                    <label className="form-label">Daily Loss Limit (%)</label>
                    <input className="form-input" type="number" min="1" max="20"
                      value={dailyLimit} onChange={e => setDailyLimit(e.target.value)} />
                    <div style={{ fontSize:10, color:"var(--text3)", marginTop:4 }}>Bot pauses when hit</div>
                  </div>
                </div>
                <div className="settings-title">Leverage Tiers (automatic)</div>
                <div style={{ display:"grid", gridTemplateColumns:"1fr 1fr", gap:8, marginBottom:16 }}>
                  {[["lev-100","100x","≥ 98% conf","BTC/ETH only"],["lev-50","50x","≥ 95% conf","Major pairs"],
                    ["lev-20","20x","90-94% conf","All assets"],["lev-10","10x","85-89% conf","All assets"]].map(([cls,lev,conf,note]) => (
                    <div key={lev} className="card-sm" style={{ display:"flex", justifyContent:"space-between", alignItems:"center" }}>
                      <div><span className={`lev-badge ${cls}`}>{lev}</span><div style={{ fontSize:10, color:"var(--text3)", marginTop:3 }}>{note}</div></div>
                      <div style={{ fontSize:12, fontFamily:"var(--font-mono)", color:"var(--text2)" }}>{conf}</div>
                    </div>
                  ))}
                </div>
                <button className="btn btn-primary" onClick={saveBotSettings} disabled={savingBot} style={{ width:"100%", justifyContent:"center" }}>
                  {savingBot ? "Applying…" : "Apply Settings to Bot"}
                </button>
              </div>
            )}

            {section === "appearance" && (
              <div>
                <div className="settings-title">Theme</div>
                <div className="settings-row">
                  <div><div className="settings-row-label">Color Mode</div><div className="settings-row-desc">Dark recommended for trading</div></div>
                  <div className="theme-selector">
                    {[["dark","🌙 Dark"],["light","☀ Light"]].map(([t,l]) => (
                      <button key={t} className={`theme-btn ${theme===t?"active":""}`} onClick={() => setTheme(t)}>{l}</button>
                    ))}
                  </div>
                </div>
                <div className="settings-row">
                  <div><div className="settings-row-label">Accent Color</div><div className="settings-row-desc">Primary interface color</div></div>
                  <div className="color-picker">
                    {[["#4d9fff","Blue"],["#00e5a0","Green"],["#a78bfa","Purple"],["#f59e0b","Amber"],["#f43f5e","Rose"]].map(([c,n]) => (
                      <div key={c} className="color-swatch" style={{ background:c }} title={n}
                        onClick={() => { document.documentElement.style.setProperty("--info", c); showToast(`Accent: ${n}`); }} />
                    ))}
                  </div>
                </div>
              </div>
            )}

            {section === "account" && (
              <div>
                <div className="settings-title">Profile</div>
                <div style={{ display:"flex", alignItems:"center", gap:14, padding:"14px 0", borderBottom:"1px solid var(--border)", marginBottom:16 }}>
                  <div style={{ width:52, height:52, borderRadius:"50%", background:"linear-gradient(135deg,var(--info),var(--purple))", display:"flex", alignItems:"center", justifyContent:"center", fontSize:22, fontWeight:700, color:"#fff" }}>
                    {user?.name?.charAt(0)?.toUpperCase() || "U"}
                  </div>
                  <div>
                    <div style={{ fontSize:16, fontWeight:600 }}>{user?.name}</div>
                    <div style={{ fontSize:12, color:"var(--text3)" }}>{user?.email}</div>
                    <div style={{ fontSize:10, color:"var(--text3)", marginTop:2, fontFamily:"var(--font-mono)" }}>
                      {user?.role?.toUpperCase()} · Joined {user?.created_at ? new Date(user.created_at).toLocaleDateString() : "—"}
                    </div>
                  </div>
                </div>
                <div className="form-group">
                  <label className="form-label">Display Name</label>
                  <div style={{ display:"flex", gap:8 }}>
                    <input className="form-input" value={editName} onChange={e => setEditName(e.target.value)} />
                    <button className="btn btn-ghost" onClick={saveName}>Save</button>
                  </div>
                </div>
                <div className="form-group">
                  <label className="form-label">Email</label>
                  <input className="form-input" value={user?.email || ""} disabled style={{ opacity:0.6 }} />
                </div>
                <div className="info-box info-box-blue" style={{ marginTop:12 }}>
                  Your account is stored securely in the server database. You can log in from any device with your email and password.
                </div>
              </div>
            )}

            {section === "risk" && (
              <div>
                <div className="settings-title">Risk Management Guide</div>
                <div className="info-box info-box-warn" style={{ marginBottom:14 }}>⚠ Read all safeguards before trading with real money.</div>
                {[
                  ["🛡","1% Risk Per Trade","Each trade risks exactly 1% of balance. 10 losses = only 10% down."],
                  ["📉","5% Daily Stop","Bot auto-pauses if you lose 5% in a single day."],
                  ["⏱","SL Cooldown","After a stop-loss, that asset is blocked for 4 hours minimum."],
                  ["📊","Max 3 Positions","Never over-exposed. Max 3 open trades at once."],
                  ["🎯","Liquidation Guard","Leverage auto-reduces if liquidation price is dangerously close."],
                  ["🔒","100x Whitelist","Extreme leverage restricted to BTC and ETH only."],
                  ["📡","HTF Bias Filter","Blocks trades that go against the 4H + 1H structure."],
                  ["📰","News Blackout","Trading pauses 15 min before high-impact events."],
                ].map(([icon,title,desc]) => (
                  <div key={title} style={{ display:"flex", gap:12, padding:"11px 0", borderBottom:"1px solid var(--border)" }}>
                    <span style={{ fontSize:18, flexShrink:0 }}>{icon}</span>
                    <div>
                      <div style={{ fontSize:13, fontWeight:600, marginBottom:3 }}>{title}</div>
                      <div style={{ fontSize:11, color:"var(--text2)", lineHeight:1.6 }}>{desc}</div>
                    </div>
                  </div>
                ))}
              </div>
            )}

            {section === "about" && (
              <div>
                <div style={{ textAlign:"center", padding:"14px 0 20px" }}>
                  <div style={{ fontFamily:"var(--font-display)", fontSize:34, fontWeight:800, marginBottom:4 }}>
                    <span style={{ color:"var(--info)" }}>WELT</span>BOT
                  </div>
                  <div style={{ fontSize:11, color:"var(--text3)", fontFamily:"var(--font-mono)" }}>v5.0 · Autonomous Crypto Trading · Built by Zilla</div>
                </div>
                {[
                  ["Strategy","Smart Money Concepts v5 — BOS + Fib + OB + MA + Entry"],
                  ["Bias Filter","4H + 1H directional analysis — blocks countertrend trades"],
                  ["Leverage","Auto 10x / 20x / 50x / 100x based on confidence score"],
                  ["Auth","JWT tokens · Passwords hashed · Keys encrypted"],
                  ["Backend","Python FastAPI + SQLite + APScheduler · Railway"],
                  ["Frontend","React + Vite · Vercel"],
                  ["Built by","Zilla · Syntrion Lab"],
                ].map(([k,v]) => (
                  <div key={k} style={{ display:"flex", justifyContent:"space-between", padding:"9px 0", borderBottom:"1px solid var(--border)", fontSize:12 }}>
                    <span style={{ color:"var(--text3)" }}>{k}</span>
                    <span style={{ color:"var(--text)", textAlign:"right", maxWidth:260 }}>{v}</span>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

WBEOF
echo "  ✓ src/components/SettingsModal.jsx"

cat > "$F/src/components/BuiltBy.jsx" << 'WBEOF'
export default function BuiltBy() {
  return (
    <div className="built-by">
      Built with ⚡ by <span>Zilla</span> · Syntrion Lab · WeltBot v5.0 · Autonomous Crypto Trading ·{" "}
      <span style={{ opacity:0.5 }}>Not financial advice</span>
    </div>
  );
}

WBEOF
echo "  ✓ src/components/BuiltBy.jsx"

echo ""
echo "╔══════════════════════════════════════════╗"
echo "║  ✅ All 20 files written!                 ║"
echo "║                                          ║"
echo "║  Next:                                   ║"
echo "║  cd /c/Users/Lotim/weltbot/frontend      ║"
echo "║  npm install                             ║"
echo "║  npm run dev                             ║"
echo "║                                          ║"
echo "║  Then open: http://localhost:5173        ║"
echo "╚══════════════════════════════════════════╝"
