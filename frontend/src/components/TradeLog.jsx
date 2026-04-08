export default function TradeLog({ trades }) {
  return (
    <div className="card" style={{ marginTop: 16 }}>
      <div className="label" style={{ marginBottom: 12 }}>Trade log</div>
      <div style={{ overflowX: "auto" }}>
        <table style={{ width: "100%", borderCollapse: "collapse" }}>
          <thead>
            <tr>
              {["Asset","Signal","Entry","Stop","TP","Size","Risk","Status","P&L","Time"].map(h => (
                <th key={h} style={{
                  padding: "4px 8px", textAlign: "left",
                  color: "var(--muted)", fontFamily: "var(--mono)",
                  fontSize: 9, fontWeight: 400, letterSpacing: "0.08em",
                  textTransform: "uppercase", whiteSpace: "nowrap",
                }}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {trades.map(t => {
              const ep  = t.entry_price ?? 0;
              const sl  = t.stop_loss   ?? 0;
              const tp  = t.take_profit ?? 0;
              const fmt = (v) => v < 1 ? v.toFixed(6) : v.toLocaleString(undefined, { maximumFractionDigits: 4 });
              const pnl = t.pnl ?? null;
              return (
                <tr key={t.id} style={{ borderTop: "1px solid var(--border)" }}>
                  <td style={{ padding: "7px 8px" }} className="mono" >
                    {t.asset?.replace("/USDT", "")}
                  </td>
                  <td style={{ padding: "7px 8px" }}>
                    <span className={`tag ${t.signal}`}>{t.signal}</span>
                  </td>
                  <td style={{ padding: "7px 8px" }} className="mono">${fmt(ep)}</td>
                  <td style={{ padding: "7px 8px", color: "var(--sell)" }} className="mono">${fmt(sl)}</td>
                  <td style={{ padding: "7px 8px", color: "var(--buy)" }}  className="mono">${fmt(tp)}</td>
                  <td style={{ padding: "7px 8px" }} className="mono">{t.position_sz?.toFixed(6)}</td>
                  <td style={{ padding: "7px 8px", color: "var(--sell)" }} className="mono">${t.risk_usd?.toFixed(4)}</td>
                  <td style={{ padding: "7px 8px" }}>
                    <span className={`tag ${t.outcome}`}>{t.outcome}</span>
                  </td>
                  <td style={{
                    padding: "7px 8px",
                    color: pnl === null ? "var(--muted)" : pnl >= 0 ? "var(--buy)" : "var(--sell)"
                  }} className="mono">
                    {pnl !== null ? `${pnl >= 0 ? "+" : ""}$${Math.abs(pnl).toFixed(4)}` : "—"}
                  </td>
                  <td style={{ padding: "7px 8px", color: "var(--muted)" }} className="mono">
                    {t.created_at ? new Date(t.created_at).toLocaleTimeString() : "—"}
                  </td>
                </tr>
              );
            })}
            {trades.length === 0 && (
              <tr>
                <td colSpan={10} style={{ padding: 24, color: "var(--muted)", textAlign: "center" }}>
                  No trades yet — start the bot to begin
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}