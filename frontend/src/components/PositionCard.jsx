export default function PositionCard({ position: p, onClose }) {
  const isProfit  = p.pnl_pct >= 0;
  const pnlColor  = isProfit ? "var(--buy)" : "var(--sell)";
  const fmt = (v) => v < 1 ? `$${Number(v).toFixed(5)}` : `$${Number(v).toLocaleString(undefined, { maximumFractionDigits: 4 })}`;

  const leverage = p.confidence >= 95 ? 25 : p.confidence >= 90 ? 20 : 10;
  const levClass = p.confidence >= 95 ? "lev-25" : p.confidence >= 90 ? "lev-20" : "lev-10";

  return (
    <div className="card" style={{
      border: `1px solid ${isProfit ? "rgba(0,229,160,0.2)" : "rgba(255,77,109,0.2)"}`,
    }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 12 }}>
        <div>
          <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 4 }}>
            <span style={{ fontFamily: "var(--display)", fontSize: 15, fontWeight: 700 }}>
              {p.asset?.replace("/USDT", "")}
            </span>
            <span className={`tag ${p.signal}`}>{p.signal}</span>
            <span className={`conf-badge ${p.confidence >= 95 ? "conf-25x" : p.confidence >= 90 ? "conf-20x" : "conf-10x"}`}>
              <span className={levClass}>{leverage}x</span>
            </span>
          </div>
          <div style={{ fontSize: 10, color: "var(--muted)" }}>
            conf {p.confidence?.toFixed(1)}%
          </div>
        </div>
        <div style={{ textAlign: "right" }}>
          <div style={{ fontFamily: "var(--display)", fontSize: 20, fontWeight: 700, color: pnlColor }}>
            {isProfit ? "+" : ""}{p.pnl_pct?.toFixed(3)}%
          </div>
          <div style={{ fontSize: 11, color: pnlColor }}>
            {p.unrealized >= 0 ? "+" : ""}${p.unrealized?.toFixed(4)}
          </div>
        </div>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 6, marginBottom: 12 }}>
        {[
          { label: "Entry",   value: fmt(p.entry) },
          { label: "Current", value: fmt(p.current) },
          { label: "Stop",    value: fmt(p.sl), color: "var(--sell)" },
          { label: "Target",  value: fmt(p.tp), color: "var(--buy)" },
        ].map(({ label, value, color }) => (
          <div key={label} className="card2">
            <div className="label" style={{ marginBottom: 2 }}>{label}</div>
            <div style={{ fontFamily: "var(--mono)", fontSize: 11, color: color || "var(--text)" }}>{value}</div>
          </div>
        ))}
      </div>

      {/* Progress bar */}
      <div style={{ marginBottom: 12 }}>
        <div style={{ height: 4, background: "var(--surface2)", borderRadius: 2, position: "relative" }}>
          {p.entry > 0 && p.sl && p.tp && (
            <div style={{
              position: "absolute", left: 0,
              width: `${Math.min(100, Math.max(0, (p.current - p.sl) / (p.tp - p.sl) * 100))}%`,
              height: "100%", background: isProfit ? "var(--buy)" : "var(--sell)",
              borderRadius: 2, transition: "width 0.6s ease",
              boxShadow: isProfit ? "0 0 8px rgba(0,229,160,0.5)" : "0 0 8px rgba(255,77,109,0.5)",
            }}/>
          )}
        </div>
        <div style={{ display: "flex", justifyContent: "space-between", marginTop: 3, fontSize: 9, color: "var(--dim)" }}>
          <span>SL</span><span>TP</span>
        </div>
      </div>

      <button className="btn-close" onClick={onClose} style={{ width: "100%" }}>
        ✕ Close Position Manually
      </button>
    </div>
  );
}