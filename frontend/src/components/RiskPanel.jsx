export default function RiskPanel({ selected }) {
  if (!selected) {
    return (
      <div className="card" style={{ color: "var(--muted)", textAlign: "center", padding: 40, fontSize: 12 }}>
        Click any signal card to see its risk plan
      </div>
    );
  }

  const s = selected?.signal_data;
  const r = selected?.risk_plan;

  if (!r || r.signal === "HOLD") {
    return (
      <div className="card">
        <div className="label" style={{ marginBottom: 12 }}>Risk Plan — {s?.symbol}</div>
        <div style={{ color: "var(--muted)", fontSize: 12 }}>
          HOLD — no trade parameters generated
        </div>
      </div>
    );
  }

  const rows = [
    ["Entry",          `$${r.entry_price?.toLocaleString()}`,                   ""],
    ["Stop-loss",      `$${r.stop_loss?.toLocaleString()}`,                     "var(--sell)"],
    ["Take-profit",    `$${r.take_profit?.toLocaleString()}`,                   "var(--buy)"],
    ["Stop dist.",     `${r.stop_pct?.toFixed(2)}%`,                            ""],
    ["Position size",  `$${r.position_size?.toLocaleString()}`,                 ""],
    ["Risk $",         `$${r.risk_usd}`,                                        ""],
    ["Risk %",         `${r.risk_pct}%`,                                        ""],
    ["R:R ratio",      `1 : ${r.risk_reward}`,                                  ""],
    ["Portfolio used", `${r.portfolio_used_pct}%`,                              ""],
  ];

  return (
    <div className="card" style={{ display: "flex", flexDirection: "column", gap: 14 }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <span className="label">Risk Plan</span>
        <span className={`tag ${s?.signal}`}>{s?.symbol}</span>
      </div>

      <div>
        {rows.map(([label, value, color]) => (
          <div key={label} style={{
            display: "flex",
            justifyContent: "space-between",
            padding: "7px 0",
            borderBottom: "1px solid var(--border)",
          }}>
            <span style={{ color: "var(--muted)", fontSize: 12 }}>{label}</span>
            <span className="mono" style={{ fontSize: 12, color: color || "var(--text)" }}>{value}</span>
          </div>
        ))}
      </div>

      <div style={{ background: "var(--sur2)", borderRadius: 8, padding: "12px 14px" }}>
        <div className="label" style={{ marginBottom: 6 }}>Break-even win rate</div>
        <div className="mono" style={{ fontSize: 22, fontWeight: 500, color: "var(--info)" }}>
          {Math.round(1 / (1 + r.risk_reward) * 100)}%
        </div>
        <div style={{ color: "var(--muted)", fontSize: 11, marginTop: 4 }}>
          At 2.5:1 R:R — win 1 in 4 trades to break even
        </div>
      </div>
    </div>
  );
}