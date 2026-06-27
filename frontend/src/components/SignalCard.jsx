const fmtPrice = (v) => {
  if (!v || v === 0) return "$0.00";
  if (v >= 1000) return `$${v.toLocaleString(undefined,{maximumFractionDigits:2})}`;
  if (v >= 1)    return `$${v.toFixed(4)}`;
  return `$${v.toFixed(6)}`;
};

const STAGES = ["BOS","Fib","OB","MA","Entry"];

export default function SignalCard({ data, selected, onSelect, getLev, getLevClass }) {
  const sig   = data?.signal_data || {};
  const mkt   = sig.market || {};
  const sub   = sig.sub_scores || {};
  const bias  = sig.bias || {};
  const dir   = sig.signal;
  const price = mkt.price || 0;
  const conf  = sig.confidence || 0;
  const lev   = getLev(conf);
  const levCls= getLevClass(conf);

  const stageKeys  = ["bos","fib","ob","ma","entry"];
  const donePct    = stageKeys.filter(k => sub[k]).length;
  const biasColor  = bias.bias === "bullish" ? "var(--buy)" : bias.bias === "bearish" ? "var(--sell)" : "var(--text3)";

  return (
    <div
      className={`signal-card ${dir !== "HOLD" ? `signal-${dir}` : ""} ${selected ? "selected" : ""}`}
      onClick={() => onSelect(data)}
    >
      {/* Header */}
      <div style={{ display:"flex", justifyContent:"space-between", alignItems:"flex-start", marginBottom:6 }}>
        <div>
          <div className="signal-asset">
            {sig.symbol?.replace("/USDT","")}
            <span className="pair">/USDT</span>
          </div>
          <div className="signal-price">{fmtPrice(price)}</div>
        </div>
        <div style={{ display:"flex", flexDirection:"column", alignItems:"flex-end", gap:3 }}>
          <span className={`tag tag-${dir}`}>{dir}</span>
          {dir !== "HOLD" && (
            <span className={`lev-badge ${levCls}`}>{lev}x</span>
          )}
        </div>
      </div>

      {/* Stages */}
      <div className="signal-stages">
        {STAGES.map((s, i) => {
          const k    = stageKeys[i];
          const done = sub[k];
          return (
            <div key={s} className={`stage-pill ${done ? `done-${dir !== "HOLD" ? dir : "BUY"}` : ""}`}>
              {done ? "✓" : s}
            </div>
          );
        })}
      </div>

      {/* Bias */}
      {bias.bias && (
        <div style={{ display:"flex", gap:4, marginBottom:6 }}>
          <span style={{ fontSize:9, color:"var(--text3)", fontFamily:"var(--font-mono)" }}>BIAS:</span>
          <span style={{ fontSize:9, color: biasColor, fontFamily:"var(--font-mono)", fontWeight:600 }}>
            {(bias["4h"] || "").toUpperCase()} 4H · {(bias["1h"] || "").toUpperCase()} 1H
          </span>
        </div>
      )}

      {/* Reason */}
      <div className="signal-reason">{sig.reason || "Monitoring…"}</div>

      {/* Confidence bar */}
      {conf > 0 && (
        <div style={{ marginTop:8 }}>
          <div style={{ height:2, background:"var(--surface2)", borderRadius:1, overflow:"hidden" }}>
            <div style={{
              height:"100%", borderRadius:1,
              width:`${Math.min(100, ((conf-85)/15)*100)}%`,
              background: dir === "BUY" ? "var(--buy)" : "var(--sell)",
              transition:"width 0.4s ease",
            }}/>
          </div>
          <div style={{ display:"flex", justifyContent:"space-between", marginTop:3 }}>
            <span style={{ fontSize:9, color:"var(--text3)", fontFamily:"var(--font-mono)" }}>
              {conf.toFixed(1)}% conf
            </span>
            <span style={{ fontSize:9, color:"var(--text3)" }}>
              {donePct}/5 stages
            </span>
          </div>
        </div>
      )}
    </div>
  );
}

