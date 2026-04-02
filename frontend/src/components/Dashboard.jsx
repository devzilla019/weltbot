import { useState, useEffect, useCallback } from "react";
import { api } from "../api";
import SignalCard  from "./SignalCard";
import RiskPanel   from "./RiskPanel";
import TradeLog    from "./TradeLog";
import SummaryBar  from "./SummaryBar";

export default function Dashboard() {
  const [signals,    setSignals]    = useState([]);
  const [trades,     setTrades]     = useState([]);
  const [summary,    setSummary]    = useState(null);
  const [selected,   setSelected]   = useState(null);
  const [loading,    setLoading]    = useState(false);
  const [lastUpdate, setLastUpdate] = useState(null);
  const [toast,      setToast]      = useState(null);
  const [error,      setError]      = useState(null);

  const showToast = (msg) => {
    setToast(msg);
    setTimeout(() => setToast(null), 3500);
  };

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [sigs, trds, sum] = await Promise.all([
        api.getAllSignals(),
        api.getTrades(),
        api.getSummary(),
      ]);
      const sorted = (Array.isArray(sigs) ? sigs : []).sort((a, b) => {
        const ah = a.signal_data?.signal === "HOLD" ? 1 : 0;
        const bh = b.signal_data?.signal === "HOLD" ? 1 : 0;
        if (ah !== bh) return ah - bh;
        return (b.signal_data?.confidence ?? 0) - (a.signal_data?.confidence ?? 0);
      });
      setSignals(sorted);
      setTrades(Array.isArray(trds) ? trds : []);
      setSummary(sum);
      setLastUpdate(new Date().toLocaleTimeString());
    } catch (e) {
      setError("Cannot reach backend — make sure uvicorn is running on port 8000");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
    const t = setInterval(load, 60000);
    return () => clearInterval(t);
  }, [load]);

  const handleExecute = async (symbol) => {
    try {
      const res = await api.executeSignal(symbol);
      showToast(res.message || "Trade simulated");
      load();
    } catch {
      showToast("Execution failed");
    }
  };

  const handleEvaluate = async () => {
    const res = await api.evaluateTrades();
    showToast(`Closed ${res.evaluated} trades`);
    load();
  };

  return (
    <div style={{ minHeight: "100vh", padding: "20px 28px 60px" }}>

      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 24 }}>
        <div>
          <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
            <div style={{
              width: 8, height: 8,
              background: "var(--buy)",
              borderRadius: "50%",
              animation: "pulse 2s infinite",
            }}/>
            <h1 style={{ fontFamily: "var(--mono)", fontSize: 16, fontWeight: 500, letterSpacing: "0.04em" }}>
              AI TRADING COPILOT
            </h1>
          </div>
          {lastUpdate && (
            <div style={{ color: "var(--muted)", fontSize: 11, marginTop: 3, fontFamily: "var(--mono)" }}>
              last updated {lastUpdate} · auto-refresh 60s
            </div>
          )}
        </div>
        <div style={{ display: "flex", gap: 8 }}>
          <button onClick={handleEvaluate}>Evaluate open trades</button>
          <button onClick={load} disabled={loading}>
            {loading ? "Loading…" : "Refresh"}
          </button>
        </div>
      </div>

      {error && (
        <div style={{
          background: "rgba(240,107,122,0.08)",
          border: "1px solid rgba(240,107,122,0.25)",
          color: "var(--sell)",
          padding: "12px 18px",
          borderRadius: 8,
          marginBottom: 20,
          fontSize: 12,
        }}>
          {error}
        </div>
      )}

      <SummaryBar summary={summary} />

      <div style={{ display: "grid", gridTemplateColumns: "1fr 300px", gap: 20 }}>
        <div>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(260px, 1fr))", gap: 16 }}>
            {signals.map(data => (
              <SignalCard
                key={data.signal_data?.symbol}
                data={data}
                selected={selected?.signal_data?.symbol === data.signal_data?.symbol}
                onSelect={setSelected}
                onExecute={handleExecute}
              />
            ))}
            {signals.length === 0 && !loading && !error && (
              <div className="card" style={{ gridColumn: "1/-1", textAlign: "center", color: "var(--muted)", padding: 40 }}>
                Loading signals — this takes 20–30 seconds on first load
              </div>
            )}
          </div>
          <TradeLog trades={trades} />
        </div>

        <RiskPanel selected={selected} />
      </div>

      {toast && (
        <div style={{
          position: "fixed", bottom: 28, right: 28,
          background: "var(--surface)",
          border: "1px solid var(--bord2)",
          padding: "10px 20px",
          borderRadius: 8,
          fontSize: 12,
          fontFamily: "var(--mono)",
          color: "var(--info)",
          zIndex: 9999,
        }}>
          {toast}
        </div>
      )}

      <style>{`
        @keyframes pulse {
          0%, 100% { opacity: 1; }
          50% { opacity: 0.3; }
        }
      `}</style>
    </div>
  );
}