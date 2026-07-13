const fmt=v=>{if(!v&&v!==0)return"—";if(Math.abs(v)>=10000)return`$${Number(v).toLocaleString(undefined,{maximumFractionDigits:0})}`;if(Math.abs(v)>=1)return`$${Number(v).toFixed(4)}`;return`$${Number(v).toFixed(6)}`;};
export default function PositionCard({position:p,onClose}){
  const isP=(p.unrealized??0)>=0;
  const pnlC=isP?"var(--buy)":"var(--sell)";
  const lev=(p.confidence||0)>=98?100:(p.confidence||0)>=95?50:(p.confidence||0)>=90?20:10;
  const levC=(p.confidence||0)>=98?"lev-100":(p.confidence||0)>=95?"lev-50":(p.confidence||0)>=90?"lev-20":"lev-10";
  const range=(p.tp||0)-(p.sl||0);
  const progress=range!==0?Math.min(100,Math.max(0,((p.current||0)-(p.sl||0))/range*100)):0;
  return(
    <div style={{background:"var(--surface)",border:`1px solid ${isP?"rgba(0,229,160,0.2)":"rgba(255,77,109,0.2)"}`,borderRadius:"var(--radius-md)",padding:14}}>
      <div style={{display:"flex",justifyContent:"space-between",alignItems:"flex-start",marginBottom:10}}>
        <div>
          <div style={{display:"flex",alignItems:"center",gap:7,marginBottom:3}}>
            <span style={{fontFamily:"var(--font-display)",fontSize:15,fontWeight:700}}>{p.asset?.replace("/USDT","")}</span>
            <span className={`tag tag-${p.signal}`}>{p.signal}</span>
            <span className={`lev-badge ${levC}`}>{lev}x</span>
          </div>
          <div style={{fontSize:10,color:"var(--text3)",fontFamily:"var(--font-mono)"}}>{(p.confidence||0).toFixed(1)}% confidence</div>
        </div>
        <div style={{textAlign:"right"}}>
          <div style={{fontFamily:"var(--font-display)",fontSize:20,fontWeight:700,color:pnlC}}>{isP?"+":""}{(p.pnl_pct||0).toFixed(3)}%</div>
          <div style={{fontSize:11,color:pnlC,fontFamily:"var(--font-mono)"}}>{(p.unrealized||0)>=0?"+":""}${(p.unrealized||0).toFixed(4)}</div>
        </div>
      </div>
      <div style={{display:"grid",gridTemplateColumns:"1fr 1fr",gap:6,marginBottom:10}}>
        {[["Entry",fmt(p.entry),""],["Current",fmt(p.current),""],["Stop",fmt(p.sl),"var(--sell)"],["Target",fmt(p.tp),"var(--buy)"]].map(([l,v,c])=>(
          <div key={l} style={{background:"var(--surface2)",borderRadius:6,padding:"7px 10px",border:"1px solid var(--border)"}}>
            <div style={{fontSize:9,color:"var(--text3)",fontFamily:"var(--font-mono)",marginBottom:2}}>{l}</div>
            <div style={{fontSize:11,fontFamily:"var(--font-mono)",color:c||"var(--text)"}}>{v}</div>
          </div>
        ))}
      </div>
      <div style={{height:4,background:"var(--surface2)",borderRadius:2,marginBottom:4,overflow:"hidden"}}>
        <div style={{height:"100%",borderRadius:2,width:`${progress}%`,background:isP?"var(--buy)":"var(--sell)",transition:"width 0.6s ease"}}/>
      </div>
      <div style={{display:"flex",justifyContent:"space-between",marginBottom:10,fontSize:9,color:"var(--text3)"}}>
        <span>SL</span><span>{progress.toFixed(0)}% to TP</span><span>TP</span>
      </div>
      <button onClick={onClose} style={{width:"100%",padding:"7px",borderRadius:6,fontSize:11,background:"rgba(255,77,109,0.1)",color:"var(--sell)",border:"1px solid rgba(255,77,109,0.25)",cursor:"pointer",fontFamily:"var(--font-mono)"}}>✕ Close Manually</button>
    </div>
  );
}
