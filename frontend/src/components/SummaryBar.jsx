export default function SummaryBar({ summary }) {
  if (!summary) return null;
  const pnlColor = (summary.total_pnl ?? 0) >= 0 ? "var(--buy)" : "var(--sell)";
  const stats = [
    { label: "Total trades", value: summary.total },
    { label: "Wins",         value: summary.wins,                        color: "var(--buy)" },
    { label: "Losses",       value: summary.losses,                      color: "var(--sell)" },
    { label: "Win rate",     value: `${summary.win_rate}%` },
    { label: "Total P&L",   value: `$${summary.total_pnl?.toFixed(2)}`, color: pnlColor },
  ];
  return (
    <div style={{ display: "grid", gridTemplateColumns: "repeat(5, 1fr)", gap: 12, marginBottom: 24 }}>
      {stats.map(({ label, value, color }) => (
        <div key={label} className="card" style={{ textAlign: "center", padding: "14px 10px" }}>
          <div className="label" style={{ marginBottom: 6 }}>{label}</div>
          <div className="mono" style={{ fontSize: 20, color: color || "var(--text)" }}>{value}</div>
        </div>
      ))}
    </div>
  );
}