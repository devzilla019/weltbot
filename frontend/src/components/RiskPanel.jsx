const fmtPrice = (v) => {
  if (!v) return "—";
  if (v >= 1000) return `$${v.toLocaleString(undefined,{maximumFractionDigits:2})}`;
  if (v >= 1)    return `$${Number(v).toFixed(4)}`;
  return `$${Number(v).toFixed(6)}`;
};

export default function RiskPanel({ selected }) {
  if (!selected) {
    return (
      <div className="card risk-panel" style={{ textAlign:"center" }}>
        <div style={{ fontSize:24, marginBottom:10, opacity:0.3 }}>📐</div>
        <div style={{ fontSize:12, color:"var(--text3)", lineHeight:1.6 }}>
          Click any signal card to see its full setup analysis
        </div>
      </div>
    );
  }

  const sig   = selected.signal_data || {};
  const risk  = selected.risk_plan   || {};
  const mkt   = sig.market  || {};
  const bias  = sig.bias    || {};
  const sl_tp = sig.sl_tp   || {};
  const bos   = sig.bos     || {};
  const fib   = sig.fib     || {};
  const ob    = sig.ob      || {};
  const dir   = sig.signal;

  const reasoning = Array.isArray(sig.reasoning) ? sig.reasoning : [];
  const lev = sig.confidence >= 98 ? 100 : sig.confidence >= 95 ? 50 : sig.confidence >= 90 ? 20 : 10;
  const levCls = sig.confidence >= 98 ? "lev-100" : sig.confidence >= 95 ? "lev-50" : sig.confidence >= 90 ? "lev-20" : "lev-10";

  return (
    <div className="card risk-panel">
      {/* Header */}
      <div style={{ display:"flex", justifyContent:"space-between", alignItems:"center", marginBottom:14 }}>
        <div>
          <div style={{ fontFamily:"var(--font-display)", fontSize:16, fontWeight:700 }}>
            {sig.symbol?.replace("/USDT","")} <span style={{ fontWeight:400, fontSize:12, color:"var(--text3)" }}>/USDT</span>
          </div>
          <div style={{ fontSize:12, fontFamily:"var(--font-mono)", marginTop:2 }}>
            {fmtPrice(mkt.price)}
          </div>
        </div>
        <div style={{ display:"flex", flexDirection:"column", alignItems:"flex-end", gap:4 }}>
          <span className={`tag tag-${dir}`}>{dir}</span>
          {sig.confidence > 0 && <span className={`lev-badge ${levCls}`}>{lev}x</span>}
        </div>
      </div>

      {/* HTF Bias */}
      {bias.bias && (
        <div className="card-sm" style={{ marginBottom:12 }}>
          <div style={{ fontSize:9, color:"var(--text3)", fontFamily:"var(--font-mono)", marginBottom:6 }}>HTF DIRECTIONAL BIAS</div>
          <div style={{ display:"flex", gap:6 }}>
            {[["4H",bias["4h"]],["1H",bias["1h"]]].map(([tf,b]) => (
              <div key={tf} style={{ flex:1, textAlign:"center", padding:"6px 0",
                borderRadius:4, background:"var(--surface3)",
                border:`1px solid ${b==="bullish"?"rgba(0,229,160,0.2)":b==="bearish"?"rgba(255,77,109,0.2)":"var(--border)"}`,
              }}>
                <div style={{ fontSize:9, color:"var(--text3)", fontFamily:"var(--font-mono)" }}>{tf}</div>
                <div style={{ fontSize:11, fontWeight:700, fontFamily:"var(--font-mono)",
                  color:b==="bullish"?"var(--buy)":b==="bearish"?"var(--sell)":"var(--text3)",
                }}>
                  {(b||"neutral").toUpperCase()}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Key levels */}
      {(sl_tp.stop_loss || risk.stop_loss) && (
        <div className="card-sm" style={{ marginBottom:12 }}>
          <div style={{ fontSize:9, color:"var(--text3)", fontFamily:"var(--font-mono)", marginBottom:6 }}>KEY LEVELS</div>
          <div style={{ display:"flex", flexDirection:"column", gap:5 }}>
            {[
              ["Entry",   fmtPrice(mkt.price),           "var(--text)"],
              ["Stop Loss",fmtPrice(sl_tp.stop_loss||risk.stop_loss), "var(--sell)"],
              ["Take Profit",fmtPrice(sl_tp.take_profit||risk.take_profit), "var(--buy)"],
              ["Risk",    sl_tp.risk_pct ? `${sl_tp.risk_pct}%` : "—", "var(--warn)"],
              ["R:R",     sl_tp.rr ? `1:${sl_tp.rr}` : "1:2", "var(--info)"],
            ].map(([l,v,c]) => (
              <div key={l} style={{ display:"flex", justifyContent:"space-between" }}>
                <span style={{ fontSize:11, color:"var(--text3)" }}>{l}</span>
                <span style={{ fontSize:11, fontFamily:"var(--font-mono)", color:c, fontWeight:500 }}>{v}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Confluence zones */}
      {fib.zone_low && (
        <div className="card-sm" style={{ marginBottom:12 }}>
          <div style={{ fontSize:9, color:"var(--text3)", fontFamily:"var(--font-mono)", marginBottom:6 }}>CONFLUENCE ZONES</div>
          <div style={{ display:"flex", flexDirection:"column", gap:4 }}>
            <div style={{ display:"flex", justifyContent:"space-between" }}>
              <span style={{ fontSize:10, color:"var(--text3)" }}>Fib 0.5–0.618</span>
              <span style={{ fontSize:10, fontFamily:"var(--font-mono)", color:"var(--purple)" }}>
                {fmtPrice(fib.zone_low)}–{fmtPrice(fib.zone_high)}
              </span>
            </div>
            {ob.ob_low && (
              <div style={{ display:"flex", justifyContent:"space-between" }}>
                <span style={{ fontSize:10, color:"var(--text3)" }}>Order Block</span>
                <span style={{ fontSize:10, fontFamily:"var(--font-mono)", color:"var(--info)" }}>
                  {fmtPrice(ob.ob_low)}–{fmtPrice(ob.ob_high)}
                </span>
              </div>
            )}
          </div>
        </div>
      )}

      {/* Reasoning */}
      {reasoning.length > 0 && (
        <div>
          <div style={{ fontSize:9, color:"var(--text3)", fontFamily:"var(--font-mono)", marginBottom:6 }}>ANALYSIS</div>
          <ul className="reasoning-list">
            {reasoning.map((r, i) => <li key={i}>{r}</li>)}
          </ul>
        </div>
      )}

      {/* Confidence meter */}
      {sig.confidence > 0 && (
        <div style={{ marginTop:14 }}>
          <div style={{ display:"flex", justifyContent:"space-between", marginBottom:4 }}>
            <span style={{ fontSize:9, color:"var(--text3)", fontFamily:"var(--font-mono)" }}>CONFIDENCE</span>
            <span style={{ fontSize:11, fontFamily:"var(--font-mono)", color:"var(--text)", fontWeight:600 }}>
              {sig.confidence?.toFixed(1)}%
            </span>
          </div>
          <div style={{ height:6, background:"var(--surface2)", borderRadius:3, overflow:"hidden" }}>
            <div style={{
              height:"100%", borderRadius:3,
              width:`${((sig.confidence-85)/15)*100}%`,
              background:`linear-gradient(90deg, var(--info), ${dir==="BUY"?"var(--buy)":"var(--sell)"})`,
            }}/>
          </div>
          <div style={{ display:"flex", justifyContent:"space-between", marginTop:3, fontSize:9, color:"var(--text3)" }}>
            <span>85%</span><span>92.5%</span><span>100%</span>
          </div>
        </div>
      )}
    </div>
  );
}

