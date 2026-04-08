export default function RiskPanel({ selected }) {
  if (!selected) {
    return (
      <div className="card" style={{ color: "var(--muted)", textAlign: "center", padding: 40, fontSize: 12 }}>
        Click any signal card to see its setup
      </div>
    );
  }

  const s   = selected?.signal_data;
  const r   = selected?.risk_plan;
  const bos = s?.bos;
  const fib = s?.fib;
  const ob  = s?.ob;
  const slt = s?.sl_tp;

  const fmt = (v) => {
    if (!v && v !== 0) return "—";
    return v < 1
      ? `$${Number(v).toFixed(6)}`
      : `$${Number(v).toLocaleString(undefined, { maximumFractionDigits: 4 })}`;
  };

  if (!r || s?.signal === "HOLD") {
    return (
      <div className="card" style={{ display: "flex", flexDirection: "column", gap: 12 }}>
        <div style={{ display: "flex", justifyContent: "space-between" }}>
          <span className="label">Structure analysis</span>
          <span className="mono" style={{ fontSize: 11 }}>{s?.symbol?.replace("/USDT", "")}</span>
        </div>

        {bos && (
          <div className="card2">
            <div className="label" style={{ marginBottom: 6 }}>Break of structure</div>
            <div style={{ fontSize: 11, color: bos.direction === "bullish" ? "var(--buy)" : "var(--sell)", fontFamily: "var(--mono)", fontWeight: 600, marginBottom: 4 }}>
              {bos.direction?.toUpperCase()} BOS
            </div>
            <div style={{ fontSize: 10, color: "var(--muted)" }}>
              Broke {fmt(bos.bos_level)}
            </div>
          </div>
        )}

        {fib && (
          <div className="card2">
            <div className="label" style={{ marginBottom: 6 }}>Fibonacci zone (0.5–0.618)</div>
            <div style={{ display: "flex", justifyContent: "space-between" }}>
              <span style={{ fontSize: 10, color: "var(--muted)" }}>Zone high</span>
              <span className="mono" style={{ fontSize: 10 }}>{fmt(fib.zone_high)}</span>
            </div>
            <div style={{ display: "flex", justifyContent: "space-between", marginTop: 4 }}>
              <span style={{ fontSize: 10, color: "var(--muted)" }}>Zone low</span>
              <span className="mono" style={{ fontSize: 10 }}>{fmt(fib.zone_low)}</span>
            </div>
          </div>
        )}

        {ob && (
          <div className="card2">
            <div className="label" style={{ marginBottom: 6 }}>Order block</div>
            <div style={{ display: "flex", justifyContent: "space-between" }}>
              <span style={{ fontSize: 10, color: "var(--muted)" }}>OB high</span>
              <span className="mono" style={{ fontSize: 10, color: "var(--buy)" }}>{fmt(ob.ob_high)}</span>
            </div>
            <div style={{ display: "flex", justifyContent: "space-between", marginTop: 4 }}>
              <span style={{ fontSize: 10, color: "var(--muted)" }}>OB low</span>
              <span className="mono" style={{ fontSize: 10, color: "var(--sell)" }}>{fmt(ob.ob_low)}</span>
            </div>
          </div>
        )}

        <div style={{ color: "var(--muted)", fontSize: 11, textAlign: "center", padding: "8px 0" }}>
          {s?.reason || "Waiting for all conditions"}
        </div>
      </div>
    );
  }

  const stopLoss   = slt?.stop_loss   ?? r?.stop_loss;
  const takeProfit = slt?.take_profit ?? r?.take_profit;
  const price      = s?.market?.price ?? 0;

  const rows = [
    ["Entry",          fmt(price),                     ""],
    ["Stop-loss",      fmt(stopLoss),                  "var(--sell)"],
    ["Take-profit",    fmt(takeProfit),                "var(--buy)"],
    ["Position (USDT)",`$${r.position_size_usdt?.toFixed(2)}`, ""],
    ["Position (units)",`${r.position_size_units}`,   ""],
    ["Risk $",         `$${r.risk_usd?.toFixed(4)}`,  "var(--sell)"],
    ["Risk %",         `${r.risk_pct?.toFixed(3)}%`,  ""],
    ["R:R",            "1 : 2",                        "var(--info)"],
  ];

  return (
    <div className="card" style={{ display: "flex", flexDirection: "column", gap: 12 }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <span className="label">Trade setup</span>
        <div style={{ display: "flex", gap: 6 }}>
          <span className="mono" style={{ fontSize: 11 }}>{s?.symbol?.replace("/USDT", "")}</span>
          <span className={`tag ${s?.signal}`}>{s?.signal}</span>
        </div>
      </div>

      {bos && (
        <div style={{
          background: bos.direction === "bullish" ? "rgba(0,208,132,0.06)" : "rgba(255,77,106,0.06)",
          border: `1px solid ${bos.direction === "bullish" ? "rgba(0,208,132,0.2)" : "rgba(255,77,106,0.2)"}`,
          borderRadius: 6, padding: "8px 10px", fontSize: 10,
        }}>
          <span style={{ color: bos.direction === "bullish" ? "var(--buy)" : "var(--sell)", fontWeight: 600 }}>
            {bos.direction?.toUpperCase()} BOS
          </span>
          <span style={{ color: "var(--muted)", marginLeft: 8 }}>
            broke {fmt(bos.bos_level)} · entry: {s.entry_type} on {s.entry_tf}
          </span>
        </div>
      )}

      <div>
        {rows.map(([label, value, color]) => (
          <div key={label} style={{
            display: "flex", justifyContent: "space-between",
            padding: "6px 0", borderBottom: "1px solid var(--border)",
          }}>
            <span style={{ color: "var(--muted)", fontSize: 12 }}>{label}</span>
            <span className="mono" style={{ fontSize: 12, color: color || "var(--text)" }}>{value}</span>
          </div>
        ))}
      </div>

      {fib && (
        <div className="card2">
          <div className="label" style={{ marginBottom: 6 }}>Fib + OB confluence zone</div>
          <div style={{ height: 6, background: "var(--surface3)", borderRadius: 3, position: "relative", marginBottom: 4 }}>
            <div style={{
              position: "absolute",
              left: "38.2%", width: "23.6%",
              height: "100%", background: "rgba(0,208,132,0.4)",
              borderRadius: 3,
            }}/>
            <div style={{
              position: "absolute",
              left: `${Math.min(95, Math.max(0, (price - fib.zone_low) / (fib.zone_high - fib.zone_low) * 23.6 + 38.2))}%`,
              width: 2, height: "100%",
              background: "var(--info)",
            }}/>
          </div>
          <div style={{ display: "flex", justifyContent: "space-between", fontSize: 9, color: "var(--muted)", fontFamily: "var(--mono)" }}>
            <span>0.0</span>
            <span style={{ color: "var(--buy)" }}>0.5–0.618</span>
            <span>1.0</span>
          </div>
        </div>
      )}

      <div className="card2" style={{ textAlign: "center" }}>
        <div className="label" style={{ marginBottom: 6 }}>Break-even win rate</div>
        <div className="mono" style={{ fontSize: 22, fontWeight: 600, color: "var(--info)" }}>33%</div>
        <div style={{ fontSize: 11, color: "var(--muted)", marginTop: 4 }}>
          Win 1 in 3 trades to break even at 1:2 R:R
        </div>
      </div>
    </div>
  );
}