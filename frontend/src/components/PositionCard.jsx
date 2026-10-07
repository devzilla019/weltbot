const fmt=v=>{if(!v&&v!==0)return"—";if(Math.abs(v)>=10000)return`$${Number(v).toLocaleString(undefined,{maximumFractionDigits:0})}`;if(Math.abs(v)>=1)return`$${Number(v).toFixed(4)}`;return`$${Number(v).toFixed(6)}`;};
const fmtP=v=>v==null?"—":Number(v).toFixed(5);

export default function PositionCard({position:p,onClose}){
  const isP=(p.unrealized??0)>=0;
  const pnlC=isP?"var(--buy)":"var(--sell)";
  const lev=(p.confidence||0)>=98?100:(p.confidence||0)>=95?50:(p.confidence||0)>=90?20:10;
  const levC=(p.confidence||0)>=98?"lev-100":(p.confidence||0)>=95?"lev-50":(p.confidence||0)>=90?"lev-20":"lev-10";
  const progress=p.progress??0;

  const riskUsd=p.risk_usd??0;
  const rewardUsd=p.reward_usd??0;
  const riskPct=p.risk_pct??0;
  const rewardPct=p.reward_pct??0;
  const rr=p.risk_reward??0;

  return(
    <div style={{background:"var(--surface)",border:`1px solid ${isP?"rgba(52,229,176,0.25)":"rgba(255,92,138,0.25)"}`,borderRadius:"var(--radius-md)",padding:14}}>
      {/* Header */}
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

      {/* Risk / Reward dashboard */}
      <div style={{display:"grid",gridTemplateColumns:"1fr 1fr 1fr",gap:6,marginBottom:10}}>
        <div style={{background:"rgba(255,92,138,0.08)",border:"1px solid rgba(255,92,138,0.2)",borderRadius:6,padding:"7px 9px"}}>
          <div style={{fontSize:8,color:"var(--text3)",fontFamily:"var(--font-mono)",letterSpacing:"0.08em"}}>RISK</div>
          <div style={{fontSize:13,fontFamily:"var(--font-mono)",color:"var(--sell)",fontWeight:600}}>-${riskUsd.toFixed(2)}</div>
          <div style={{fontSize:9,color:"var(--text3)",fontFamily:"var(--font-mono)"}}>{riskPct.toFixed(2)}% of bal</div>
        </div>
        <div style={{background:"rgba(52,229,176,0.08)",border:"1px solid rgba(52,229,176,0.2)",borderRadius:6,padding:"7px 9px"}}>
          <div style={{fontSize:8,color:"var(--text3)",fontFamily:"var(--font-mono)",letterSpacing:"0.08em"}}>TARGET</div>
          <div style={{fontSize:13,fontFamily:"var(--font-mono)",color:"var(--buy)",fontWeight:600}}>+${rewardUsd.toFixed(2)}</div>
          <div style={{fontSize:9,color:"var(--text3)",fontFamily:"var(--font-mono)"}}>{rewardPct.toFixed(2)}% of bal</div>
        </div>
        <div style={{background:"rgba(167,139,250,0.08)",border:"1px solid var(--border2)",borderRadius:6,padding:"7px 9px"}}>
          <div style={{fontSize:8,color:"var(--text3)",fontFamily:"var(--font-mono)",letterSpacing:"0.08em"}}>R:R</div>
          <div style={{fontSize:13,fontFamily:"var(--font-mono)",color:"var(--lav-2)",fontWeight:600}}>1:{rr.toFixed(2)}</div>
          <div style={{fontSize:9,color:"var(--text3)",fontFamily:"var(--font-mono)"}}>reward/risk</div>
        </div>
      </div>

      {/* Prices */}
      <div style={{display:"grid",gridTemplateColumns:"1fr 1fr",gap:6,marginBottom:10}}>
        {[["Entry",fmtP(p.entry),""],["Current",fmtP(p.current),""],["Stop",fmtP(p.sl),"var(--sell)"],["Target",fmtP(p.tp),"var(--buy)"]].map(([l,v,c])=>(
          <div key={l} style={{background:"var(--surface2)",borderRadius:6,padding:"7px 10px",border:"1px solid var(--border)"}}>
            <div style={{fontSize:9,color:"var(--text3)",fontFamily:"var(--font-mono)",marginBottom:2}}>{l}</div>
            <div style={{fontSize:11,fontFamily:"var(--font-mono)",color:c||"var(--text)"}}>{v}</div>
          </div>
        ))}
      </div>

      {/* Progress to TP */}
      <div style={{height:4,background:"var(--surface2)",borderRadius:2,marginBottom:4,overflow:"hidden"}}>
        <div style={{height:"100%",borderRadius:2,width:`${progress}%`,background:isP?"var(--buy)":"var(--sell)",transition:"width 0.6s ease"}}/>
      </div>
      <div style={{display:"flex",justifyContent:"space-between",marginBottom:10,fontSize:9,color:"var(--text3)",fontFamily:"var(--font-mono)"}}>
        <span>SL</span><span>{progress.toFixed(0)}% to TP</span><span>TP</span>
      </div>

      <button onClick={onClose} style={{width:"100%",padding:"7px",borderRadius:6,fontSize:11,background:"rgba(255,92,138,0.1)",color:"var(--sell)",border:"1px solid rgba(255,92,138,0.25)",cursor:"pointer",fontFamily:"var(--font-mono)"}}>✕ Close Manually</button>
    </div>
  );
}
