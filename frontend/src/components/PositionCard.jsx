const fmt = (v) => {
  if (!v && v !== 0) return "—";
  if (Math.abs(v) >= 10000) return `$${Number(v).toLocaleString(undefined,{maximumFractionDigits:0})}`;
  if (Math.abs(v) >= 1)     return `$${Number(v).toFixed(4)}`;
  if (Math.abs(v) >= 0.01)  return `$${Number(v).toFixed(5)}`;
  return `$${Number(v).toFixed(6)}`;
};

export default function PositionCard({ position: p, onClose }) {
  const isProfit = (p.unrealized ?? 0) >= 0;
  const pnlColor = isProfit ? "var(--buy)" : "var(--sell)";
  const lev      = (p.confidence||0) >= 98 ? 100 : (p.confidence||0) >= 95 ? 50 : (p.confidence||0) >= 90 ? 20 : 10;
  const levCls   = (p.confidence||0) >= 98 ? "lev-100" : (p.confidence||0) >= 95 ? "lev-50" : (p.confidence||0) >= 90 ? "lev-20" : "lev-10";

  const range    = (p.tp || 0) - (p.sl || 0);
  const progress = range !== 0
    ? Math.min(100, Math.max(0, ((p.current || 0) - (p.sl || 0)) / range * 100))
    : 0;

  return (
    <div className="position-card" style={{
      border: `1px solid ${isProfit ? "rgba(0,229,160,0.2)" : "rgba(255,77,109,0.2)"}`,
      borderRadius: "var(--radius-md)",
      padding: 14,
      background: "var(--surface)",
    }}>
      {/* Header */}
      <div style={{ display:"flex", justifyContent:"space-between", alignItems:"flex-start", marginBottom:10 }}>
        <div>
          <div style={{ display:"flex", alignItems:"center", gap:7, marginBottom:3 }}>
            <span style={{ fontFamily:"var(--font-display)", fontSize:15, fontWeight:700 }}>
              {p.asset?.replace("/USDT","")}
            </span>
            <span className={`tag tag-${p.signal}`}>{p.signal}</span>
            <span className={`lev-badge ${levCls}`}>{lev}x</span>
          </div>
          <div style={{ fontSize:10, color:"var(--text3)", fontFamily:"var(--font-mono)" }}>
            {(p.confidence||0).toFixed(1)}% confidence
          </div>
        </div>
        <div style={{ textAlign:"right" }}>
          <div style={{ fontFamily:"var(--font-display)", fontSize:20, fontWeight:700, color:pnlColor }}>
            {isProfit ? "+" : ""}{(p.pnl_pct||0).toFixed(3)}%
          </div>
          <div style={{ fontSize:11, color:pnlColor, fontFamily:"var(--font-mono)" }}>
            {(p.unrealized||0) >= 0 ? "+" : ""}${(p.unrealized||0).toFixed(4)}
          </div>
        </div>
      </div>

      {/* Price grid */}
      <div style={{ display:"grid", gridTemplateColumns:"1fr 1fr", gap:6, marginBottom:10 }}>
        {[["Entry",fmt(p.entry),""],["Current",fmt(p.current),""],
          ["Stop",fmt(p.sl),"var(--sell)"],["Target",fmt(p.tp),"var(--buy)"]].map(([l,v,c])=>(
          <div key={l} style={{ background:"var(--surface2)", borderRadius:6, padding:"7px 10px", border:"1px solid var(--border)" }}>
            <div style={{ fontSize:9, color:"var(--text3)", fontFamily:"var(--font-mono)", marginBottom:2 }}>{l}</div>
            <div style={{ fontSize:11, fontFamily:"var(--font-mono)", color:c||"var(--text)" }}>{v}</div>
          </div>
        ))}
      </div>

      {/* Progress bar */}
      <div style={{ height:4, background:"var(--surface2)", borderRadius:2, marginBottom:4, overflow:"hidden" }}>
        <div style={{
          height:"100%", borderRadius:2, width:`${progress}%`,
          background: isProfit ? "var(--buy)" : "var(--sell)",
          boxShadow: isProfit ? "0 0 6px rgba(0,229,160,0.5)" : "0 0 6px rgba(255,77,109,0.5)",
          transition: "width 0.6s ease",
        }}/>
      </div>
      <div style={{ display:"flex", justifyContent:"space-between", marginBottom:10, fontSize:9, color:"var(--text3)" }}>
        <span>SL</span>
        <span>{progress.toFixed(0)}% to TP</span>
        <span>TP</span>
      </div>

      {/* Close button */}
      <button
        onClick={onClose}
        style={{
          width:"100%", padding:"7px", borderRadius:6, fontSize:11,
          background:"rgba(255,77,109,0.1)", color:"var(--sell)",
          border:"1px solid rgba(255,77,109,0.25)", cursor:"pointer",
          fontFamily:"var(--font-mono)", transition:"all 0.15s",
        }}
        onMouseOver={e => e.target.style.background="rgba(255,77,109,0.2)"}
        onMouseOut={e => e.target.style.background="rgba(255,77,109,0.1)"}
      >
        ✕ Close Position Manually
      </button>
    </div>
  );
}

