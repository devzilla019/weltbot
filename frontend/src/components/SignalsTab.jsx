import{useState}from"react";
import SignalCard from"./SignalCard";
import RiskPanel from"./RiskPanel";
const getLev=c=>c>=98?100:c>=95?50:c>=90?20:10;
const getLevClass=c=>c>=98?"lev-100":c>=95?"lev-50":c>=90?"lev-20":"lev-10";
export default function SignalsTab({signals,botStatus,loading}){
  const[selected,setSelected]=useState(null);
  const[filter,setFilter]=useState("all");
  const[sortBy,setSortBy]=useState("confidence");
  const counts={all:signals.length,active:signals.filter(s=>s.signal_data?.signal!=="HOLD").length,buy:signals.filter(s=>s.signal_data?.signal==="BUY").length,sell:signals.filter(s=>s.signal_data?.signal==="SELL").length,hold:signals.filter(s=>s.signal_data?.signal==="HOLD").length};
  const filtered=signals.filter(s=>{const sig=s.signal_data?.signal;if(filter==="active")return sig!=="HOLD";if(filter==="buy")return sig==="BUY";if(filter==="sell")return sig==="SELL";if(filter==="hold")return sig==="HOLD";return true;}).sort((a,b)=>{if(sortBy==="confidence")return(b.signal_data?.confidence||0)-(a.signal_data?.confidence||0);if(sortBy==="price")return(b.signal_data?.market?.price||0)-(a.signal_data?.market?.price||0);return(a.signal_data?.symbol||"").localeCompare(b.signal_data?.symbol||"");});
  return(
    <div>
      <div style={{display:"flex",alignItems:"center",justifyContent:"space-between",marginBottom:16,flexWrap:"wrap",gap:10}}>
        <div><div style={{fontFamily:"var(--font-display)",fontSize:20,fontWeight:700}}>Structure Signals</div><div style={{fontSize:12,color:"var(--text2)",marginTop:2}}>{signals.length} assets · SMC v5.1 with HTF Bias</div></div>
        {botStatus?.active_setups?.length>0&&<div style={{display:"flex",gap:5,alignItems:"center",flexWrap:"wrap"}}><span style={{fontSize:10,color:"var(--text3)",fontFamily:"var(--font-mono)"}}>L2:</span>{botStatus.active_setups.map(s=><span key={s} style={{fontSize:10,padding:"2px 9px",borderRadius:4,background:"rgba(167,139,250,0.1)",color:"var(--purple)",border:"1px solid rgba(167,139,250,0.2)",fontFamily:"var(--font-mono)"}}>{s.replace("/USDT","")}</span>)}</div>}
      </div>
      <div className="page-grid">
        <div>
          <div style={{display:"flex",gap:6,marginBottom:12,alignItems:"center",flexWrap:"wrap"}}>
            <div style={{display:"flex",gap:3}}>{[["all","All"],["active","Active"],["buy","Buy"],["sell","Sell"],["hold","Hold"]].map(([k,l])=><button key={k} onClick={()=>setFilter(k)} style={{padding:"5px 11px",borderRadius:5,fontSize:11,cursor:"pointer",border:"1px solid",background:filter===k?"var(--info)":"var(--surface2)",color:filter===k?"#fff":"var(--text2)",borderColor:filter===k?"var(--info)":"var(--border)",fontFamily:"var(--font-mono)"}}>{l} <span style={{opacity:0.7,fontSize:10}}>{counts[k]}</span></button>)}</div>
            <div style={{marginLeft:"auto",display:"flex",alignItems:"center",gap:4}}><span style={{fontSize:10,color:"var(--text3)"}}>Sort:</span>{[["confidence","Conf"],["price","Price"],["symbol","Name"]].map(([k,l])=><button key={k} onClick={()=>setSortBy(k)} style={{padding:"4px 10px",borderRadius:4,fontSize:10,cursor:"pointer",border:"1px solid",fontFamily:"var(--font-mono)",background:sortBy===k?"var(--surface3)":"transparent",color:sortBy===k?"var(--text)":"var(--text3)",borderColor:sortBy===k?"var(--border2)":"transparent"}}>{l}</button>)}</div>
          </div>
          {filtered.length===0&&!loading?<div className="card"><div className="empty-state"><div className="empty-icon">📡</div>No signals match filter</div></div>:<div className="signal-grid">{filtered.map(d=><SignalCard key={d.signal_data?.symbol} data={d} selected={selected?.signal_data?.symbol===d.signal_data?.symbol} onSelect={setSelected} getLev={getLev} getLevClass={getLevClass}/>)}</div>}
        </div>
        <div className="risk-panel"><RiskPanel selected={selected}/></div>
      </div>
    </div>
  );
}
