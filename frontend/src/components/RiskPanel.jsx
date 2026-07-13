const fmtP=v=>{if(!v)return"—";if(v>=1000)return`$${v.toLocaleString(undefined,{maximumFractionDigits:2})}`;if(v>=1)return`$${Number(v).toFixed(4)}`;return`$${Number(v).toFixed(6)}`;};
export default function RiskPanel({selected}){
  if(!selected)return(
    <div className="card risk-panel" style={{textAlign:"center"}}>
      <div style={{fontSize:24,marginBottom:10,opacity:0.3}}>📐</div>
      <div style={{fontSize:12,color:"var(--text3)",lineHeight:1.6}}>Click any signal card to see its full setup analysis</div>
    </div>
  );
  const sig=selected.signal_data||{};
  const mkt=sig.market||{};
  const bias=sig.bias||{};
  const sl_tp=sig.sl_tp||{};
  const fib=sig.fib||{};
  const ob=sig.ob||{};
  const dir=sig.signal;
  const conf=sig.confidence||0;
  const lev=conf>=98?100:conf>=95?50:conf>=90?20:10;
  const levCls=conf>=98?"lev-100":conf>=95?"lev-50":conf>=90?"lev-20":"lev-10";
  const biasColor=bias.bias==="bullish"?"var(--buy)":bias.bias==="bearish"?"var(--sell)":"var(--text3)";
  return(
    <div className="card risk-panel">
      <div style={{display:"flex",justifyContent:"space-between",alignItems:"center",marginBottom:14}}>
        <div>
          <div style={{fontFamily:"var(--font-display)",fontSize:16,fontWeight:700}}>{sig.symbol?.replace("/USDT","")}<span style={{fontWeight:400,fontSize:12,color:"var(--text3)"}}>/USDT</span></div>
          <div style={{fontSize:12,fontFamily:"var(--font-mono)",marginTop:2}}>{fmtP(mkt.price)}</div>
        </div>
        <div style={{display:"flex",flexDirection:"column",alignItems:"flex-end",gap:4}}>
          <span className={`tag tag-${dir}`}>{dir}</span>
          {conf>0&&<span className={`lev-badge ${levCls}`}>{lev}x</span>}
        </div>
      </div>
      {bias.bias&&(
        <div className="card-sm" style={{marginBottom:12}}>
          <div style={{fontSize:9,color:"var(--text3)",fontFamily:"var(--font-mono)",marginBottom:6}}>HTF DIRECTIONAL BIAS</div>
          <div style={{display:"flex",gap:6}}>
            {[["4H",bias["4h"]],["1H",bias["1h"]]].map(([tf,b])=>(
              <div key={tf} style={{flex:1,textAlign:"center",padding:"6px 0",borderRadius:4,background:"var(--surface3)",border:`1px solid ${b==="bullish"?"rgba(0,229,160,0.2)":b==="bearish"?"rgba(255,77,109,0.2)":"var(--border)"}`}}>
                <div style={{fontSize:9,color:"var(--text3)",fontFamily:"var(--font-mono)"}}>{tf}</div>
                <div style={{fontSize:11,fontWeight:700,fontFamily:"var(--font-mono)",color:b==="bullish"?"var(--buy)":b==="bearish"?"var(--sell)":"var(--text3)"}}>{(b||"neutral").toUpperCase()}</div>
              </div>
            ))}
          </div>
        </div>
      )}
      {(sl_tp.stop_loss)&&(
        <div className="card-sm" style={{marginBottom:12}}>
          <div style={{fontSize:9,color:"var(--text3)",fontFamily:"var(--font-mono)",marginBottom:6}}>KEY LEVELS</div>
          <div style={{display:"flex",flexDirection:"column",gap:5}}>
            {[["Entry",fmtP(mkt.price),"var(--text)"],["Stop Loss",fmtP(sl_tp.stop_loss),"var(--sell)"],["Take Profit",fmtP(sl_tp.take_profit),"var(--buy)"],["Risk %",sl_tp.risk_pct?`${sl_tp.risk_pct}%`:"—","var(--warn)"],["R:R",sl_tp.rr?`1:${sl_tp.rr}`:"1:2","var(--info)"]].map(([l,v,c])=>(
              <div key={l} style={{display:"flex",justifyContent:"space-between"}}>
                <span style={{fontSize:11,color:"var(--text3)"}}>{l}</span>
                <span style={{fontSize:11,fontFamily:"var(--font-mono)",color:c,fontWeight:500}}>{v}</span>
              </div>
            ))}
          </div>
        </div>
      )}
      {fib.zone_low&&(
        <div className="card-sm" style={{marginBottom:12}}>
          <div style={{fontSize:9,color:"var(--text3)",fontFamily:"var(--font-mono)",marginBottom:6}}>CONFLUENCE ZONES</div>
          <div style={{display:"flex",flexDirection:"column",gap:4}}>
            <div style={{display:"flex",justifyContent:"space-between"}}><span style={{fontSize:10,color:"var(--text3)"}}>Fib 0.5–0.618</span><span style={{fontSize:10,fontFamily:"var(--font-mono)",color:"var(--purple)"}}>{fmtP(fib.zone_low)}–{fmtP(fib.zone_high)}</span></div>
            {ob.ob_low&&<div style={{display:"flex",justifyContent:"space-between"}}><span style={{fontSize:10,color:"var(--text3)"}}>Order Block</span><span style={{fontSize:10,fontFamily:"var(--font-mono)",color:"var(--info)"}}>{fmtP(ob.ob_low)}–{fmtP(ob.ob_high)}</span></div>}
          </div>
        </div>
      )}
      {Array.isArray(sig.reasoning)&&sig.reasoning.length>0&&(
        <div>
          <div style={{fontSize:9,color:"var(--text3)",fontFamily:"var(--font-mono)",marginBottom:6}}>ANALYSIS</div>
          <ul className="reasoning-list">{sig.reasoning.map((r,i)=><li key={i}>{r}</li>)}</ul>
        </div>
      )}
      {conf>0&&(
        <div style={{marginTop:14}}>
          <div style={{display:"flex",justifyContent:"space-between",marginBottom:4}}>
            <span style={{fontSize:9,color:"var(--text3)",fontFamily:"var(--font-mono)"}}>CONFIDENCE</span>
            <span style={{fontSize:11,fontFamily:"var(--font-mono)",fontWeight:600}}>{conf.toFixed(1)}%</span>
          </div>
          <div style={{height:6,background:"var(--surface2)",borderRadius:3,overflow:"hidden"}}>
            <div style={{height:"100%",borderRadius:3,width:`${((conf-85)/15)*100}%`,background:`linear-gradient(90deg,var(--info),${dir==="BUY"?"var(--buy)":"var(--sell)"})`}}/>
          </div>
          <div style={{display:"flex",justifyContent:"space-between",marginTop:3,fontSize:9,color:"var(--text3)"}}>
            <span>85%</span><span>92.5%</span><span>100%</span>
          </div>
        </div>
      )}
    </div>
  );
}
