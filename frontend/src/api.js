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

