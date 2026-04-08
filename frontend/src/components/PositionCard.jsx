export default function PositionCard({ position: p }) {
  const isProfit  = p.pnl_pct >= 0;
  const pnlColor  = isProfit ? "var(--buy)" : "var(--sell)";
  const slPct     = p.entry > 0 ? Math.abs((p.sl - p.entry) / p.entry * 100).toFixed(2) : 0;
  const tpPct     = p.entry > 0 ? Math.abs((p.tp - p.entry) / p.entry * 100).toFixed(2) : 0;
  const fmt       = (v) => v < 1 ? Number(v).toFixed(6) : Number(v).toLocaleString(undefined, { maximumFractionDigits: 4 });

  return (
    <div className="card" style={{
      border: `1px solid ${isProfit ? "rgba(0,208,132,0.25)" : "rgba(255,77,106,0.25)"}`,
      display: "flex", flexDirection: "column", gap: 10,
    }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <div>
          <div className="mono" style={{ fontSize: 13, fontWeight: 600 }}>
            {p.asset?.replace("/USDT", "")}
            <span style={{ fontSize: 9, color: "var(--muted)", marginLeft: 4 }}>/USDT</span>
          </div>
          <span className={`tag ${p.signal}`} style={{ marginTop: 4 }}>{p.signal}</span>
        </div>
        <div style={{ textAlign: "right" }}>
          <div className="mono" style={{ fontSize: 18, fontWeight: 600, color: pnlColor }}>
            {isProfit ? "+" : ""}{p.pnl_pct?.toFixed(2)}%
          </div>
          <div className="mono" style={{ fontSize: 11, color: pnlColor }}>
            {p.unrealized >= 0 ? "+" : ""}${p.unrealized?.toFixed(4)}
          </div>
        </div>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8 }}>
        {[
          { label: "Entry",   value: `$${fmt(p.entry)}` },
          { label: "Current", value: `$${fmt(p.current)}` },
          { label: "Stop",    value: `$${fmt(p.sl)} (-${slPct}%)`, color: "var(--sell)" },
          { label: "Target",  value: `$${fmt(p.tp)} (+${tpPct}%)`, color: "var(--buy)" },
        ].map(({ label, value, color }) => (
          <div key={label} style={{
            background: "var(--surface2)", borderRadius: 6, padding: "6px 8px",
          }}>
            <div className="label" style={{ marginBottom: 2 }}>{label}</div>
            <div className="mono" style={{ fontSize: 10, color: color || "var(--text)" }}>{value}</div>
          </div>
        ))}
      </div>

      <div style={{ display: "flex", justifyContent: "space-between" }}>
        <span style={{ color: "var(--muted)", fontSize: 10 }}>
          Size: {p.size?.toFixed(6)} units
        </span>
        <span style={{ color: "var(--muted)", fontSize: 10 }}>
          Conf: {p.confidence?.toFixed(1)}%
        </span>
      </div>

      {/* Progress bar between SL and TP */}
      <div>
        <div style={{ height: 4, background: "var(--surface3)", borderRadius: 2, position: "relative" }}>
          {p.entry > 0 && p.sl && p.tp && (
            <div style={{
              position: "absolute",
              left: 0,
              width: `${Math.min(100, Math.max(0,
                (p.current - p.sl) / (p.tp - p.sl) * 100
              ))}%`,
              height: "100%",
              background: isProfit ? "var(--buy)" : "var(--sell)",
              borderRadius: 2,
              transition: "width 0.6s ease",
            }}/>
          )}
        </div>
        <div style={{ display: "flex", justifyContent: "space-between", marginTop: 3 }}>
          <span style={{ fontSize: 9, color: "var(--sell)", fontFamily: "var(--mono)" }}>SL</span>
          <span style={{ fontSize: 9, color: "var(--muted)", fontFamily: "var(--mono)" }}>
            Price tracking
          </span>
          <span style={{ fontSize: 9, color: "var(--buy)", fontFamily: "var(--mono)" }}>TP</span>
        </div>
      </div>
    </div>
  );
}