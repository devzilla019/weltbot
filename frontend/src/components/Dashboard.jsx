import { useState, useEffect, useCallback } from "react";
import { api } from "../api";
import SignalCard   from "./SignalCard";
import RiskPanel    from "./RiskPanel";
import TradeLog     from "./TradeLog";
import PositionCard from "./PositionCard";
import ApiKeyModal  from "./ApiKeyModal";

export default function Dashboard() {
  const [botStatus,  setBotStatus]  = useState(null);
  const [signals,    setSignals]    = useState([]);
  const [trades,     setTrades]     = useState([]);
  const [summary,    setSummary]    = useState(null);
  const [portfolio,  setPortfolio]  = useState(null);
  const [selected,   setSelected]   = useState(null);
  const [loading,    setLoading]    = useState(false);
  const [actionLoad, setActionLoad] = useState(false);
  const [lastUpdate, setLastUpdate] = useState(null);
  const [toast,      setToast]      = useState(null);
  const [showKeys,   setShowKeys]   = useState(false);

  const showToast = (msg, type = "info") => {
    setToast({ msg, type });
    setTimeout(() => setToast(null), 4000);
  };

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [status, sigs, trds, sum, port] = await Promise.all([
        api.getBotStatus(), api.getAllSignals(), api.getTrades(),
        api.getSummary(), api.getPortfolio(),
      ]);
      setBotStatus(status);
      const sorted = (Array.isArray(sigs) ? sigs : []).sort((a, b) => {
        const ah = a.signal_data?.signal === "HOLD" ? 1 : 0;
        const bh = b.signal_data?.signal === "HOLD" ? 1 : 0;
        if (ah !== bh) return ah - bh;
        return (b.signal_data?.confidence ?? 0) - (a.signal_data?.confidence ?? 0);
      });
      setSignals(sorted);
      setTrades(Array.isArray(trds) ? trds : []);
      setSummary(sum);
      setPortfolio(port);
      setLastUpdate(new Date().toLocaleTimeString());
    } catch (e) {
      showToast("Cannot reach backend", "error");
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
    try { const r = await api.startBot(); showToast(r.message || "Bot started", "success"); setTimeout(load, 2000); }
    catch { showToast("Failed to start", "error"); }
    finally { setActionLoad(false); }
  };

  const handleStop = async () => {
    setActionLoad(true);
    try { const r = await api.stopBot(); showToast(r.message || "Bot stopped"); load(); }
    catch { showToast("Failed to stop", "error"); }
    finally { setActionLoad(false); }
  };

  const handleScan = async () => {
    setActionLoad(true);
    try { await api.scanNow(); showToast("Scanning markets now…", "info"); setTimeout(load, 8000); }
    catch { showToast("Scan failed", "error"); }
    finally { setActionLoad(false); }
  };

  const handleCloseTrade = async (id) => {
    try {
      const r = await api.closeTrade(id);
      if (r.success) { showToast(`Trade closed — PnL: $${r.pnl?.toFixed(4)}`, "success"); load(); }
      else showToast(r.error || "Close failed", "error");
    } catch { showToast("Close failed", "error"); }
  };

  const isLive    = botStatus?.running && !botStatus?.paused;
  const isPaused  = botStatus?.paused;
  const balance   = botStatus?.balance_usdt ?? 0;
  const pnl       = summary?.total_pnl ?? 0;
  const pnlColor  = pnl >= 0 ? "var(--buy)" : "var(--sell)";

  const getLeverageClass = (conf) => {
    if (conf >= 95) return "conf-25x";
    if (conf >= 90) return "conf-20x";
    return "conf-10x";
  };
  const getLeverage = (conf) => {
    if (conf >= 95) return "25x";
    if (conf >= 90) return "20x";
    return "10x";
  };

  return (
    <div style={{ minHeight: "100vh", padding: "0" }}>

      {/* Top nav bar */}
      <div style={{
        display: "flex", justifyContent: "space-between", alignItems: "center",
        padding: "14px 24px", borderBottom: "1px solid var(--border)",
        background: "rgba(8,12,20,0.9)", backdropFilter: "blur(12px)",
        position: "sticky", top: 0, zIndex: 100,
      }}>
        <div style={{ display: "flex", alignItems: "center", gap: 16 }}>
          <div style={{ fontFamily: "var(--display)", fontSize: 18, fontWeight: 800, letterSpacing: "-0.02em" }}>
            <span style={{ color: "var(--info)" }}>WELT</span>
            <span style={{ color: "var(--text)" }}>BOT</span>
          </div>
          <div style={{
            display: "flex", alignItems: "center", gap: 6,
            padding: "3px 10px", borderRadius: 20,
            background: isLive ? "rgba(0,229,160,0.1)" : "rgba(255,77,109,0.1)",
            border: `1px solid ${isLive ? "rgba(0,229,160,0.25)" : "rgba(255,77,109,0.25)"}`,
          }}>
            <div style={{
              width: 6, height: 6, borderRadius: "50%",
              background: isLive ? "var(--buy)" : "var(--sell)",
              animation: isLive ? "pulse 2s infinite" : "none",
            }}/>
            <span style={{ fontSize: 10, color: isLive ? "var(--buy)" : "var(--sell)", letterSpacing: "0.08em" }}>
              {isLive ? "LIVE" : isPaused ? "PAUSED" : "STOPPED"}
            </span>
          </div>
          {botStatus?.testnet && (
            <span style={{
              fontSize: 9, color: "var(--purple)", letterSpacing: "0.1em",
              padding: "2px 8px", borderRadius: 4,
              background: "rgba(139,110,255,0.1)", border: "1px solid rgba(139,110,255,0.25)",
            }}>TESTNET</span>
          )}
        </div>

        <div style={{ display: "flex", alignItems: "center", gap: 20 }}>
          {lastUpdate && (
            <span style={{ fontSize: 10, color: "var(--dim)" }}>
              updated {lastUpdate}
            </span>
          )}
          <div style={{ textAlign: "right" }}>
            <div style={{ fontFamily: "var(--display)", fontSize: 20, fontWeight: 700, color: "var(--buy)", lineHeight: 1 }}>
              ${balance.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
            </div>
            <div style={{ fontSize: 9, color: "var(--muted)" }}>USDT BALANCE</div>
          </div>
          <button className="btn-settings" onClick={() => setShowKeys(true)} style={{ padding: "6px 12px" }}>
            ⚙ Settings
          </button>
        </div>
      </div>

      <div style={{ padding: "20px 24px" }}>

        {/* Control bar */}
        <div style={{
          display: "flex", alignItems: "center", justifyContent: "space-between",
          marginBottom: 20,
        }}>
          <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
            {!isLive
              ? <button className="btn-start" onClick={handleStart} disabled={actionLoad}>
                  {actionLoad ? "Starting…" : "▶ Start Bot"}
                </button>
              : <button className="btn-stop" onClick={handleStop} disabled={actionLoad}>
                  {actionLoad ? "Stopping…" : "■ Stop Bot"}
                </button>
            }
            <button className="btn-scan" onClick={handleScan} disabled={actionLoad}>
              ⟳ Scan Now
            </button>
            <button onClick={load} disabled={loading} style={{ background: "rgba(255,255,255,0.04)", color: "var(--muted)", border: "1px solid var(--border)" }}>
              {loading ? "…" : "↻"}
            </button>
          </div>

          {botStatus?.active_setups?.length > 0 && (
            <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
              <span style={{ fontSize: 10, color: "var(--muted)" }}>WATCHING</span>
              {botStatus.active_setups.map(s => (
                <span key={s} style={{
                  fontSize: 10, color: "var(--purple)", padding: "2px 8px",
                  borderRadius: 4, background: "rgba(139,110,255,0.1)",
                  border: "1px solid rgba(139,110,255,0.2)",
                }}>{s.replace("/USDT", "")}</span>
              ))}
            </div>
          )}
        </div>

        {/* Stats bar */}
        <div style={{
          display: "grid", gridTemplateColumns: "repeat(7, 1fr)",
          gap: 8, marginBottom: 20,
        }}>
          {[
            { label: "Total Trades", value: summary?.total ?? 0, color: "var(--text)" },
            { label: "Open",         value: summary?.open ?? 0,  color: "var(--info)" },
            { label: "Wins",         value: summary?.wins ?? 0,  color: "var(--buy)" },
            { label: "Losses",       value: summary?.losses ?? 0,color: "var(--sell)" },
            { label: "Win Rate",     value: `${summary?.win_rate ?? 0}%`, color: summary?.win_rate >= 50 ? "var(--buy)" : "var(--sell)" },
            { label: "Realized P&L", value: `${pnl >= 0 ? "+" : ""}$${pnl.toFixed(4)}`, color: pnlColor },
            { label: "Unrealized",   value: `${(portfolio?.unrealized_pnl ?? 0) >= 0 ? "+" : ""}$${(portfolio?.unrealized_pnl ?? 0).toFixed(4)}`, color: (portfolio?.unrealized_pnl ?? 0) >= 0 ? "var(--buy)" : "var(--sell)" },
          ].map(({ label, value, color }) => (
            <div key={label} style={{
              background: "var(--surface)", border: "1px solid var(--border)",
              borderRadius: 10, padding: "12px 14px", textAlign: "center",
            }}>
              <div className="label" style={{ marginBottom: 6 }}>{label}</div>
              <div style={{ fontFamily: "var(--display)", fontSize: 16, fontWeight: 700, color }}>{value}</div>
            </div>
          ))}
        </div>

        {/* Leverage guide */}
        <div style={{
          display: "flex", gap: 8, marginBottom: 16, alignItems: "center",
        }}>
          <span style={{ fontSize: 10, color: "var(--muted)" }}>LEVERAGE TIERS:</span>
          {[
            { label: "95%+ → 25x", cls: "conf-25x" },
            { label: "90-94% → 20x", cls: "conf-20x" },
            { label: "85-89% → 10x", cls: "conf-10x" },
          ].map(({ label, cls }) => (
            <span key={label} className={`conf-badge ${cls}`}>{label}</span>
          ))}
        </div>

        {/* Open positions */}
        {portfolio?.positions?.length > 0 && (
          <div style={{ marginBottom: 20 }}>
            <div className="label" style={{ marginBottom: 10 }}>
              Open Positions — {portfolio.positions.length} active
            </div>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(280px,1fr))", gap: 10 }}>
              {portfolio.positions.map((p, i) => (
                <PositionCard key={i} position={p} onClose={() => handleCloseTrade(p.trade_id)} />
              ))}
            </div>
          </div>
        )}

        {/* Main grid */}
        <div style={{ display: "grid", gridTemplateColumns: "1fr 300px", gap: 16 }}>
          <div>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 12 }}>
              <div>
                <span className="label">Structure Signals — {signals.length} assets monitored</span>
                <div style={{ fontSize: 10, color: "var(--dim)", marginTop: 2 }}>
                  BOS → Fib → OB → MA → Entry · all 5 conditions required · min 85% confidence
                </div>
              </div>
              <div style={{ display: "flex", gap: 6 }}>
                {["BOS","Fib","OB","MA","Entry"].map(s => (
                  <span key={s} style={{
                    fontSize: 9, color: "var(--dim)", padding: "2px 8px",
                    borderRadius: 4, background: "var(--surface)", border: "1px solid var(--border)",
                  }}>{s}</span>
                ))}
              </div>
            </div>

            <div style={{
              display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(200px,1fr))",
              gap: 8, marginBottom: 8,
            }}>
              {signals.map(data => (
                <SignalCard
                  key={data.signal_data?.symbol}
                  data={data}
                  selected={selected?.signal_data?.symbol === data.signal_data?.symbol}
                  onSelect={setSelected}
                  getLeverage={getLeverage}
                  getLeverageClass={getLeverageClass}
                />
              ))}
              {signals.length === 0 && !loading && (
                <div style={{
                  gridColumn: "1/-1", textAlign: "center",
                  color: "var(--muted)", padding: 40, fontSize: 12,
                  background: "var(--surface)", borderRadius: 12, border: "1px solid var(--border)",
                }}>
                  Warming signal cache — 30–60 seconds on first load
                </div>
              )}
            </div>

            <TradeLog trades={trades} onClose={handleCloseTrade} />
          </div>

          <div>
            <RiskPanel selected={selected} />
          </div>
        </div>
      </div>

      {/* API Key Modal */}
      {showKeys && <ApiKeyModal onClose={() => setShowKeys(false)} showToast={showToast} />}

      {/* Toast */}
      {toast && (
        <div style={{
          position: "fixed", bottom: 24, right: 24,
          background: toast.type === "error" ? "rgba(255,77,109,0.15)" :
                      toast.type === "success" ? "rgba(0,229,160,0.12)" : "var(--surface2)",
          border: `1px solid ${toast.type === "error" ? "rgba(255,77,109,0.35)" :
                               toast.type === "success" ? "rgba(0,229,160,0.3)" : "var(--border2)"}`,
          padding: "12px 20px", borderRadius: 10,
          fontFamily: "var(--mono)", fontSize: 12,
          color: toast.type === "error" ? "var(--sell)" : toast.type === "success" ? "var(--buy)" : "var(--info)",
          zIndex: 9999, animation: "fadeIn 0.2s ease",
          maxWidth: 320,
        }}>
          {toast.msg}
        </div>
      )}
    </div>
  );
}