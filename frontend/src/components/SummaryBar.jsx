export default function SummaryBar({ summary, portfolio }) {
  if (!summary) return null;
  const pnlColor = (summary.total_pnl ?? 0) >= 0 ? "var(--buy)" : "var(--sell)";
  const unrColor = (portfolio?.unrealized_pnl ?? 0) >= 0 ? "var(--buy)" : "var(--sell)";
  const stats = [
    { label: "Total trades", value: summary.total ?? 0 },
    { label: "Open",         value: summary.open ?? 0,       color: "var(--info)" },
    { label: "Wins",         value: summary.wins ?? 0,       color: "var(--buy)" },
    { label: "Losses",       value: summary.losses ?? 0,     color: "var(--sell)" },
    { label: "Win rate",     value: `${summary.win_rate ?? 0}%` },
    { label: "Realized P&L", value: `${(summary.total_pnl ?? 0) >= 0 ? "+" : ""}$${(summary.total_pnl ?? 0).toFixed(4)}`, color: pnlColor },
    { label: "Unrealized",   value: `${(portfolio?.unrealized_pnl ?? 0) >= 0 ? "+" : ""}$${(portfolio?.unrealized_pnl ?? 0).toFixed(4)}`, color: unrColor },
  ];
  return (
    <div style={{ display: "grid", gridTemplateColumns: "repeat(7,1fr)", gap: 8, marginBottom: 16 }}>
      {stats.map(({ label, value, color }) => (
        <div key={label} className="card2" style={{ textAlign: "center", padding: "10px 6px" }}>
          <div className="label" style={{ marginBottom: 4 }}>{label}</div>
          <div className="mono" style={{ fontSize: 15, fontWeight: 600, color: color || "var(--text)" }}>
            {value}
          </div>
        </div>
      ))}
    </div>
  );
}