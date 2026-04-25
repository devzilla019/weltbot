const BASE = import.meta.env.VITE_API_URL || "http://localhost:8080";

const get  = (url) => fetch(`${BASE}${url}`).then(r => { if (!r.ok) throw new Error(r.status); return r.json(); });
const post = (url, body) => fetch(`${BASE}${url}`, {
  method: "POST",
  headers: body ? {"Content-Type": "application/json"} : {},
  body: body ? JSON.stringify(body) : undefined,
}).then(r => r.json());

export const api = {
  getBotStatus:    ()           => get("/api/bot/status"),
  startBot:        ()           => post("/api/bot/start"),
  stopBot:         ()           => post("/api/bot/stop"),
  scanNow:         ()           => post("/api/bot/scan-now"),
  getAllSignals:    ()           => get("/api/signals/"),
  getTrades:       ()           => get("/api/trades/"),
  evaluateTrades:  ()           => post("/api/trades/evaluate"),
  closeTrade:      (id)         => post(`/api/trades/${id}/close`),
  getSummary:      ()           => get("/api/analytics/summary"),
  getPortfolio:    ()           => get("/api/analytics/portfolio"),
  getApiKeyStatus: ()           => get("/api/analytics/settings/apikeys"),
  updateApiKeys:   (key, secret) => post("/api/analytics/settings/apikeys", {api_key: key, api_secret: secret}),
};