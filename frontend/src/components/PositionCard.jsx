// ── PositionCard ──────────────────────────────────────────────────
export function PositionCard({ position: p, onClose }) {
  const isProfit = (p.unrealized ?? 0) >= 0;
  const pnlColor = isProfit ? "var(--buy)" : "var(--sell)";
  const lev      = p.confidence >= 98 ? 100 : p.confidence >= 95 ? 50 : p.confidence >= 90 ? 20 : 10;
  const levCls   = p.confidence >= 98 ? "lev-100" : p.confidence >= 95 ? "lev-50" : p.confidence >= 90 ? "lev-20" : "lev-10";

  const fmt = (v) => !v ? "—" : v < 1 ? `$${Number(v).toFixed(5)}` : `$${Number(v).toLocaleString(undefined,{maximumFractionDigits:3})}`;

  const progress = p.entry > 0 && p.sl && p.tp
    ? Math.min(100, Math.max(0, (p.current - p.sl) / (p.tp - p.sl) * 100))
    : 0;

  return (
    <div className={`position-card ${isProfit ? "profit" : "loss"}`}>
      <div style={{ display:"flex", justifyContent:"space-between", alignItems:"flex-start", marginBottom:10 }}>
        <div>
          <div style={{ display:"flex", gap:7, alignItems:"center", marginBottom:3 }}>
            <span style={{ fontFamily:"var(--font-display)", fontSize:15, fontWeight:700 }}>
              {p.asset?.replace("/USDT","")}
            </span>
            <span className={`tag tag-${p.signal}`}>{p.signal}</span>
            <span className={`lev-badge ${levCls}`}>{lev}x</span>
          </div>
          <div style={{ fontSize:10, color:"var(--text3)", fontFamily:"var(--font-mono)" }}>
            {p.confidence?.toFixed(1)}% confidence
          </div>
        </div>
        <div style={{ textAlign:"right" }}>
          <div style={{ fontFamily:"var(--font-display)", fontSize:20, fontWeight:700, color:pnlColor }}>
            {isProfit?"+":""}{(p.pnl_pct||0).toFixed(3)}%
          </div>
          <div style={{ fontSize:11, color:pnlColor, fontFamily:"var(--font-mono)" }}>
            {(p.unrealized||0)>=0?"+":""}${(p.unrealized||0).toFixed(4)}
          </div>
        </div>
      </div>

      <div style={{ display:"grid", gridTemplateColumns:"1fr 1fr", gap:6, marginBottom:10 }}>
        {[["Entry",fmt(p.entry),""],["Current",fmt(p.current),""],
          ["Stop",fmt(p.sl),"var(--sell)"],["Target",fmt(p.tp),"var(--buy)"]].map(([l,v,c]) => (
          <div key={l} className="card-sm">
            <div style={{ fontSize:9, color:"var(--text3)", fontFamily:"var(--font-mono)", marginBottom:2 }}>{l}</div>
            <div style={{ fontSize:11, fontFamily:"var(--font-mono)", color:c||"var(--text)" }}>{v}</div>
          </div>
        ))}
      </div>

      <div className="pos-progress">
        <div className="pos-progress-fill" style={{
          width:`${progress}%`,
          background:isProfit?"var(--buy)":"var(--sell)",
          boxShadow:`0 0 6px ${isProfit?"rgba(0,229,160,0.5)":"rgba(255,77,109,0.5)"}`,
        }}/>
      </div>
      <div style={{ display:"flex", justifyContent:"space-between", marginBottom:10, fontSize:9, color:"var(--text3)" }}>
        <span>SL</span><span>{progress.toFixed(0)}% to TP</span><span>TP</span>
      </div>

      <button className="btn btn-danger btn-sm" onClick={onClose} style={{ width:"100%", justifyContent:"center" }}>
        ✕ Close Manually
      </button>
    </div>
  );
}

export default PositionCard;

