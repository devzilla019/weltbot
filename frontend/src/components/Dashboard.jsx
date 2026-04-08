import { useState, useEffect, useCallback } from "react";
import { api } from "../api";
import BotStatus from "./BotStatus";
import SummaryBar from "./SummaryBar";
import SignalCard from "./SignalCard";
import RiskPanel from "./RiskPanel";
import TradeLog from "./TradeLog";
import PositionCard from "./PositionCard";

export default function Dashboard() {
  const [botStatus, setBotStatus] = useState(null);
  const [signals, setSignals] = useState([]);
  const [trades, setTrades] = useState([]);
  const [summary, setSummary] = useState(null);
  const [portfolio, setPortfolio] = useState(null);
  const [selected, setSelected] = useState(null);
  const [loading, setLoading] = useState(false);
  const [actionLoad, setActionLoad] = useState(false);
  const [lastUpdate, setLastUpdate] = useState(null);
  const [toast, setToast] = useState(null);
  const [error, setError] = useState(null);

  const showToast = (msg, isError = false) => {
    setToast({ msg, isError });
    setTimeout(() => setToast(null), 4000);
  };

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [status, sigs, trds, sum, port] = await Promise.all([
        api.getBotStatus(),
        api.getAllSignals(),
        api.getTrades(),
        api.getSummary(),
        api.getPortfolio(),
      ]);
      setBotStatus(status);
      const sorted = (Array.isArray(sigs) ? sigs : []).sort((a, b) => {
        const ah = a.signal_data?.signal === "HOLD" ? 1 : 0;
        const bh = b.signal_data?.signal === "HOLD" ? 1 : 0;
        if (ah !== bh) return ah - bh;
        return (
          (b.signal_data?.confidence ?? 0) - (a.signal_data?.confidence ?? 0)
        );
      });
      setSignals(sorted);
      setTrades(Array.isArray(trds) ? trds : []);
      setSummary(sum);
      setPortfolio(port);
      setLastUpdate(new Date().toLocaleTimeString());
    } catch (e) {
      setError(
        "Cannot reach backend — run: python -m uvicorn main:app --reload --port 8000",
      );
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
    const t = setInterval(load, 30000);
    return () => clearInterval(t);
  }, [load]);

  const handleStart = async () => {
    setActionLoad(true);
    try {
      const res = await api.startBot();
      showToast(res.message || "Bot started");
      setTimeout(load, 2000);
    } catch {
      showToast("Failed to start bot", true);
    } finally {
      setActionLoad(false);
    }
  };

  const handleStop = async () => {
    setActionLoad(true);
    try {
      const res = await api.stopBot();
      showToast(res.message || "Bot stopped");
      load();
    } catch {
      showToast("Failed to stop", true);
    } finally {
      setActionLoad(false);
    }
  };

  const handleScan = async () => {
    setActionLoad(true);
    try {
      await api.scanNow();
      showToast("Scanning all 50 assets now — check terminal");
      setTimeout(load, 8000);
    } catch {
      showToast("Scan failed", true);
    } finally {
      setActionLoad(false);
    }
  };

  const handleEvaluate = async () => {
    try {
      const res = await api.evaluateTrades();
      showToast(`Evaluated — closed ${res.evaluated || 0} trades`);
      load();
    } catch {
      showToast("Evaluate failed", true);
    }
  };

  return (
    <div style={{ minHeight: "100vh", padding: "14px 18px 60px" }}>
      {/* Header */}
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          marginBottom: 14,
        }}
      >
        <div>
          <div
            style={{
              fontFamily: "var(--mono)",
              fontSize: 10,
              color: "var(--muted)",
              letterSpacing: "0.12em",
            }}
          >
            AUTONOMOUS CRYPTO TRADING · WELTBOT v1.0
          </div>
          {lastUpdate && (
            <div
              style={{
                fontFamily: "var(--mono)",
                fontSize: 9,
                color: "var(--dim)",
                marginTop: 2,
              }}
            >
              updated {lastUpdate} · auto-refresh 30s
            </div>
          )}
        </div>
        <div style={{ display: "flex", gap: 8 }}>
          <button onClick={handleEvaluate} style={{ fontSize: 10 }}>
            Check exits
          </button>
          <button onClick={load} disabled={loading} style={{ fontSize: 10 }}>
            {loading ? "Loading…" : "Refresh"}
          </button>
        </div>
      </div>

      {error && (
        <div
          style={{
            background: "rgba(255,77,106,0.08)",
            border: "1px solid rgba(255,77,106,0.25)",
            color: "var(--sell)",
            padding: "10px 14px",
            borderRadius: 8,
            marginBottom: 14,
            fontSize: 11,
            fontFamily: "var(--mono)",
          }}
        >
          {error}
        </div>
      )}

      {/* Bot status */}
      <div style={{ marginBottom: 14 }}>
        <BotStatus
          status={botStatus}
          portfolio={portfolio}
          onStart={handleStart}
          onStop={handleStop}
          onScan={handleScan}
          loading={actionLoad}
        />
      </div>

      {/* Summary bar */}
      <SummaryBar summary={summary} portfolio={portfolio} />

      {/* Open positions */}
      {portfolio?.positions?.length > 0 && (
        <div style={{ marginBottom: 16 }}>
          <div className="label" style={{ marginBottom: 10 }}>
            Open positions — {portfolio.positions.length} active
          </div>
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "repeat(auto-fill, minmax(260px, 1fr))",
              gap: 10,
            }}
          >
            {portfolio.positions.map((p, i) => (
              <PositionCard key={i} position={p} />
            ))}
          </div>
        </div>
      )}

      {/* Main grid */}
      <div
        style={{ display: "grid", gridTemplateColumns: "1fr 280px", gap: 14 }}
      >
        <div>
          <div
            style={{
              display: "flex",
              justifyContent: "space-between",
              alignItems: "center",
              marginBottom: 10,
            }}
          >
            <div>
              <span className="label">
                Structure signals — {signals.length} assets monitored
              </span>
              <div
                style={{
                  fontSize: 10,
                  color: "var(--muted)",
                  marginTop: 2,
                  fontFamily: "var(--mono)",
                }}
              >
                BOS → Fib → OB → MA → Entry · all 5 conditions required
              </div>
            </div>
            <div style={{ display: "flex", gap: 6 }}>
              {["BOS", "Fib", "OB", "MA", "Entry"].map((s) => (
                <div
                  key={s}
                  style={{
                    background: "var(--surface2)",
                    border: "1px solid var(--border)",
                    borderRadius: 4,
                    padding: "3px 8px",
                    fontSize: 9,
                    color: "var(--muted)",
                    fontFamily: "var(--mono)",
                  }}
                >
                  {s}
                </div>
              ))}
            </div>
          </div>
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "repeat(auto-fill, minmax(210px, 1fr))",
              gap: 10,
              marginBottom: 4,
            }}
          >
            {signals.map((data) => (
              <SignalCard
                key={data.signal_data?.symbol}
                data={data}
                selected={
                  selected?.signal_data?.symbol === data.signal_data?.symbol
                }
                onSelect={setSelected}
              />
            ))}
            {signals.length === 0 && !loading && !error && (
              <div
                className="card"
                style={{
                  gridColumn: "1/-1",
                  textAlign: "center",
                  color: "var(--muted)",
                  padding: 40,
                  fontSize: 12,
                }}
              >
                Warming signal cache — 30–60 seconds on first load
              </div>
            )}
          </div>
          <TradeLog trades={trades} />
        </div>
        <div>
          <RiskPanel selected={selected} />
        </div>
      </div>

      {toast && (
        <div
          style={{
            position: "fixed",
            bottom: 24,
            right: 24,
            background: toast.isError
              ? "rgba(255,77,106,0.15)"
              : "var(--surface2)",
            border: `1px solid ${toast.isError ? "rgba(255,77,106,0.3)" : "var(--border2)"}`,
            padding: "10px 18px",
            borderRadius: 8,
            fontFamily: "var(--mono)",
            fontSize: 11,
            color: toast.isError ? "var(--sell)" : "var(--info)",
            zIndex: 9999,
          }}
        >
          {toast.msg}
        </div>
      )}
    </div>
  );
}
