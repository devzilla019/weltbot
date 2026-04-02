const BASE = import.meta.env.VITE_API_URL || "http://localhost:8000";

const get  = (url) => fetch(`${BASE}${url}`).then(r => { if (!r.ok) throw new Error(r.status); return r.json(); });
const post = (url) => fetch(`${BASE}${url}`, { method: "POST" }).then(r => r.json());

export const api = {
  getAllSignals:   ()    => get("/api/signals/"),
  getSignal:      (sym) => get(`/api/signals/${sym}`),
  executeSignal:  (sym) => post(`/api/signals/${sym}/execute`),
  getTrades:      ()    => get("/api/trades/"),
  evaluateTrades: ()    => post("/api/trades/evaluate"),
  getAccuracy:    ()    => get("/api/trades/accuracy"),
  getSummary:     ()    => get("/api/analytics/summary"),
};