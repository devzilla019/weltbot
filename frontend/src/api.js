const BASE = import.meta.env.VITE_API_URL || "http://localhost:8000";

const req = async (method, path, body) => {
  const opts = { method, headers: { "Content-Type": "application/json" } };
  if (body) opts.body = JSON.stringify(body);
  const r = await fetch(`${BASE}${path}`, opts);
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
};

export const makeApi = (_user) => ({
  // Bot control
  getBotStatus:      ()        => req("GET",    "/api/bot/status"),
  startBot:          ()        => req("POST",   "/api/bot/start"),
  stopBot:           ()        => req("POST",   "/api/bot/stop"),
  scanNow:           ()        => req("POST",   "/api/bot/scan-now"),
  // Signals
  getAllSignals:      ()        => req("GET",    "/api/signals/"),
  // Trades
  getTrades:         ()        => req("GET",    "/api/trades/"),
  clearTrades:       ()        => req("DELETE", "/api/trades/clear"),
  closeTrade:        (id)      => req("POST",   `/api/trades/${id}/close`),
  // Analytics
  getSummary:        ()        => req("GET",    "/api/analytics/summary"),
  getPortfolio:      ()        => req("GET",    "/api/analytics/portfolio"),
  // Settings
  getApiKeyStatus:   ()        => req("GET",    "/api/analytics/settings/apikeys"),
  updateApiKeys:     (k, s)    => req("POST",   "/api/analytics/settings/apikeys", { api_key: k, api_secret: s }),
  getBotSettings:    ()        => req("GET",    "/api/analytics/settings/bot"),
  updateBotSettings: (d)       => req("POST",   "/api/analytics/settings/bot", d),
  toggleNetwork:     (testnet) => req("POST",   "/api/analytics/settings/network", { testnet }),
});

