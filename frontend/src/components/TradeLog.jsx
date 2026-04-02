export default function TradeLog({ trades }) {
  return (
    <div className="card" style={{ marginTop: 20 }}>
      <div className="label" style={{ marginBottom: 14 }}>Trade log</div>
      <div style={{ overflowX: "auto" }}>
        <table style={{ width: "100%", borderCollapse: "collapse" }}>
          <thead>
            <tr>
              {["Asset","Signal","Entry","Stop","Take Profit","Size","Risk $","Status","P&L"].map(h => (
                <th key={h} style={{
                  padding: "4px 10px", textAlign: "left",
                  color: "var(--muted)", fontFamily: "var(--mono)",
                  fontSize: 9, fontWeight: 400,
                  letterSpacing: "0.08em", textTransform: "uppercase",
                }}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {trades.map(t => (
              <tr key={t.id} style={{ borderTop: "1px solid var(--border)" }}>
                <td style={{ padding: "8px 10px" }} className="mono">{t.asset}</td>
                <td style={{ padding: "8px 10px" }}><span className={`tag ${t.signal}`}>{t.signal}</span></td>
                <td style={{ padding: "8px 10px" }} className="mono">${t.entry_price?.toLocaleString(undefined,{maximumFractionDigits:2})}</td>
                <td style={{ padding: "8px 10px", color: "var(--sell)" }} className="mono">${t.stop_loss?.toLocaleString(undefined,{maximumFractionDigits:2})}</td>
                <td style={{ padding: "8px 10px", color: "var(--buy)" }} className="mono">${t.take_profit?.toLocaleString(undefined,{maximumFractionDigits:2})}</td>
                <td style={{ padding: "8px 10px" }} className="mono">${t.position_sz?.toLocaleString(undefined,{maximumFractionDigits:0})}</td>
                <td style={{ padding: "8px 10px", color: "var(--sell)" }} className="mono">${t.risk_usd?.toFixed(2)}</td>
                <td style={{ padding: "8px 10px" }}><span className={`tag ${t.outcome}`}>{t.outcome}</span></td>
                <td style={{ padding: "8px 10px", color: (t.pnl ?? 0) >= 0 ? "var(--buy)" : "var(--sell)" }} className="mono">
                  {t.pnl != null ? `${t.pnl >= 0 ? "+" : ""}$${Math.abs(t.pnl).toFixed(2)}` : "—"}
                </td>
              </tr>
            ))}
            {trades.length === 0 && (
              <tr>
                <td colSpan={9} style={{ padding: 24, color: "var(--muted)", textAlign: "center" }}>
                  No simulated trades yet — click Simulate on a signal card
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}