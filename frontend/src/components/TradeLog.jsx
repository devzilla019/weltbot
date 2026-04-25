export default function TradeLog({ trades, onClose }) {
  const fmt = (v) => !v ? "—" : v < 1 ? `$${Number(v).toFixed(5)}` : `$${Number(v).toFixed(2)}`;
  const openTrades   = trades.filter(t => t.outcome === "OPEN");
  const closedTrades = trades.filter(t => t.outcome !== "OPEN");

  return (
    <div className="card" style={{ marginTop: 12 }}>
      <div className="label" style={{ marginBottom: 12 }}>Trade Log — {trades.length} total</div>
      {trades.length === 0 ? (
        <div style={{ textAlign: "center", color: "var(--muted)", padding: "24px 0", fontSize: 12 }}>
          No trades yet — start the bot to begin
        </div>
      ) : (
        <div style={{ overflowX: "auto" }}>
          <table>
            <thead>
              <tr>
                <th>Asset</th><th>Signal</th><th>Entry</th>
                <th>Stop</th><th>TP</th><th>Size</th>
                <th>Status</th><th>P&L</th><th>Time</th><th></th>
              </tr>
            </thead>
            <tbody>
              {trades.map((t, i) => (
                <tr key={i}>
                  <td style={{ fontFamily: "var(--display)", fontWeight: 600 }}>
                    {t.asset?.replace("/USDT", "")}
                  </td>
                  <td><span className={`tag ${t.signal}`}>{t.signal}</span></td>
                  <td className="mono">{fmt(t.entry_price)}</td>
                  <td className="mono" style={{ color: "var(--sell)" }}>{fmt(t.stop_loss)}</td>
                  <td className="mono" style={{ color: "var(--buy)" }}>{fmt(t.take_profit)}</td>
                  <td className="mono" style={{ color: "var(--muted)" }}>{t.position_sz?.toFixed(4)}</td>
                  <td><span className={`tag ${t.outcome}`}>{t.outcome}</span></td>
                  <td style={{ color: (t.pnl ?? 0) >= 0 ? "var(--buy)" : "var(--sell)" }}>
                    {t.pnl != null ? `${t.pnl >= 0 ? "+" : ""}$${t.pnl.toFixed(4)}` : "—"}
                  </td>
                  <td style={{ color: "var(--dim)", fontSize: 11 }}>
                    {t.created_at ? new Date(t.created_at).toLocaleTimeString() : "—"}
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