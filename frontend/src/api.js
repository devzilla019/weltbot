const BASE = import.meta.env.VITE_API_URL || "http://localhost:8000";

const get  = (url) => fetch(`${BASE}${url}`).then(r => { if (!r.ok) throw new Error(r.status); return r.json(); });
const post = (url) => fetch(`${BASE}${url}`, { method: "POST" }).then(r => r.json());

export const api = {
  getBotStatus:   ()    => get("/api/bot/status"),
  startBot:       ()    => post("/api/bot/start"),
  stopBot:        ()    => post("/api/bot/stop"),
  scanNow:        ()    => post("/api/bot/scan-now"),
  getAllSignals:   ()    => get("/api/signals/"),
  getTrades:      ()    => get("/api/trades/"),
  evaluateTrades: ()    => post("/api/trades/evaluate"),
  getSummary:     ()    => get("/api/analytics/summary"),
  getPortfolio:   ()    => get("/api/analytics/portfolio"),
};