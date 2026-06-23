import { useState } from "react";
import { api } from "../api";

export default function TradeLog({ trades, onClose, onRefresh }) {
  const [clearing, setClearing] = useState(false);
  const [confirmClear, setConfirmClear] = useState(false);

  const fmt = (v) => !v ? "—" : v < 1 ? `$${Number(v).toFixed(5)}` : `$${Number(v).toFixed(2)}`;

  const handleClear = async () => {
    if (!confirmClear) {
      setConfirmClear(true);
      setTimeout(() => setConfirmClear(false), 4000);
      return;
    }
    setClearing(true);
    try {
      const resp = await fetch(
        `${import.meta.env.VITE_API_URL || "http://localhost:8000"}/api/trades/clear`,
        { method: "DELETE" }
      );
      const data = await resp.json();
      if (data.success) {
        setConfirmClear(false);
        if (onRefresh) onRefresh();
      }
    } catch (e) {
      console.error("Clear failed", e);
    } finally {
      setClearing(false);
    }
  };

  const openTrades   = trades.filter(t => t.outcome === "OPEN");
  const closedTrades = trades.filter(t => t.outcome !== "OPEN");
  const wins         = closedTrades.filter(t => t.outcome === "WIN").length;
  const losses       = closedTrades.filter(t => t.outcome === "LOSS").length;
  const winRate      = closedTrades.length > 0 ? ((wins / closedTrades.length) * 100).toFixed(1) : "0.0";
  const totalPnl     = closedTrades.reduce((sum, t) => sum + (t.pnl || 0), 0);

  return (
    <div className="card" style={{ marginTop: 12 }}>
      <div style={{
        display: "flex", justifyContent: "space-between",
        alignItems: "center", marginBottom: 14,
      }}>
        <div style={{ display: "flex", alignItems: "center", gap: 16 }}>
          <div className="label">Trade History — {trades.length} total</div>
          {closedTrades.length > 0 && (
            <div style={{ display: "flex", gap: 10, fontSize: 11 }}>
              <span style={{ color: "var(--buy)" }}>{wins}W</span>
              <span style={{ color: "var(--sell)" }}>{losses}L</span>
              <span style={{ color: winRate >= 50 ? "var(--buy)" : "var(--sell)" }}>
                {winRate}% WR
              </span>
              <span style={{ color: totalPnl >= 0 ? "var(--buy)" : "var(--sell)" }}>
                {totalPnl >= 0 ? "+" : ""}${totalPnl.toFixed(4)} P&L
              </span>
            </div>
          )}
        </div>
        {trades.length > 0 && (
          <button
            onClick={handleClear}
            disabled={clearing}
            style={{
              background: confirmClear ? "rgba(255,77,109,0.2)" : "rgba(255,255,255,0.04)",
              color: confirmClear ? "var(--sell)" : "var(--dim)",
              border: confirmClear ? "1px solid rgba(255,77,109,0.4)" : "1px solid var(--border)",
              padding: "5px 12px", borderRadius: 6, fontSize: 11,
              transition: "all 0.2s",
            }}
          >
            {clearing ? "Clearing…" : confirmClear ? "⚠ Confirm Clear" : "Clear History"}
          </button>
        )}
      </div>

      {trades.length === 0 ? (
        <div style={{
          textAlign: "center", color: "var(--muted)",
          padding: "32px 0", fontSize: 12,
        }}>
          No trades yet — history cleared, starting fresh
        </div>
      ) : (
        <div style={{ overflowX: "auto" }}>
          <table>
            <thead>
              <tr>
                <th>Asset</th>
                <th>Signal</th>
                <th>Entry</th>
                <th>Stop</th>
                <th>TP</th>
                <th>Size</th>
                <th>Status</th>
                <th>P&L</th>
                <th>Date</th>
                <th>Time</th>
                <th>Closed</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {trades.map((t, i) => (
                <tr key={i} style={{ opacity: t.outcome === "OPEN" ? 1 : 0.75 }}>
                  <td style={{ fontFamily: "var(--display)", fontWeight: 700 }}>
                    {t.asset?.replace("/USDT", "")}
                    <span style={{ fontSize: 9, color: "var(--dim)", marginLeft: 2 }}>/USDT</span>
                  </td>
                  <td><span className={`tag ${t.signal}`}>{t.signal}</span></td>
                  <td className="mono" style={{ fontSize: 11 }}>{fmt(t.entry_price)}</td>
                  <td className="mono" style={{ fontSize: 11, color: "var(--sell)" }}>{fmt(t.stop_loss)}</td>
                  <td className="mono" style={{ fontSize: 11, color: "var(--buy)" }}>{fmt(t.take_profit)}</td>
                  <td className="mono" style={{ fontSize: 11, color: "var(--muted)" }}>
                    {t.position_sz?.toFixed(4)}
                  </td>
                  <td><span className={`tag ${t.outcome}`}>{t.outcome}</span></td>
                  <td style={{
                    fontFamily: "var(--mono)", fontSize: 12, fontWeight: 600,
                    color: (t.pnl ?? 0) >= 0 ? "var(--buy)" : "var(--sell)",
                  }}>
                    {t.pnl != null
                      ? `${t.pnl >= 0 ? "+" : ""}$${t.pnl.toFixed(4)}`
                      : "—"}
                  </td>
                  <td style={{ fontSize: 11, color: "var(--muted)", whiteSpace: "nowrap" }}>
                    {t.date || "—"}
                  </td>
                  <td style={{ fontSize: 11, color: "var(--dim)", whiteSpace: "nowrap" }}>
                    {t.time || "—"}
                  </td>
                  <td style={{ fontSize: 10, color: "var(--dim)", whiteSpace: "nowrap" }}>
                    {t.closed_date ? `${t.closed_date} ${t.closed_time}` : "—"}
                  </td>
                  <td>
                    {t.outcome === "OPEN" && (
                      <button className="btn-close" onClick={() => onClose(t.id)}>
                        Close
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}