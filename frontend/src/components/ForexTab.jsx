import{useState,useEffect}from"react";
import CRTSignalCard from"./CRTSignalCard";
import{forexApi}from"../api";

export default function ForexTab(){
  const[data,setData]=useState(null);
  const[loading,setLoading]=useState(true);
  const[err,setErr]=useState(null);

  const load=async()=>{
    try{const d=await forexApi.getStatus();setData(d);setErr(null);}
    catch(e){setErr(e.message);}
    finally{setLoading(false);}
  };
  useEffect(()=>{load();const t=setInterval(load,10000);return()=>clearInterval(t);},[]);

  if(loading)return(
    <div className="grid-pairs">
      {[...Array(8)].map((_,i)=><div key={i} className="skeleton" style={{height:210}}/>)}
    </div>
  );

  if(err)return<div className="info-box info-box-red">⚠ {err}</div>;

  if(!data||!data.enabled)return(
    <div className="glass" style={{padding:40,textAlign:"center"}}>
      <div style={{fontSize:40,marginBottom:12}}>◆</div>
      <div className="sec-title" style={{justifyContent:"center"}}>Forex Trading Disabled</div>
      <div className="sec-sub" style={{marginTop:8}}>Set FOREX_ENABLED=true and add METAAPI_TOKEN + METAAPI_ACCOUNT_ID on Railway</div>
    </div>
  );

  const{biases,crt_levels,positions,account,kronos_available,pairs}=data;
  const openPos=positions?.open_positions||[];

  return(
    <div>
      <div className="hero">
        <div className="hero-title">Forex & Metals <span className="accent">Trading</span></div>
        <div className="hero-sub">CRT + SMC + Kronos AI · IC Markets via MetaApi</div>
        <div className="hero-chips">
          <span className="hero-chip">Kronos <b>{kronos_available?"ACTIVE":"OFFLINE"}</b></span>
          <span className="hero-chip">Pairs <b>{pairs?.length||0}</b></span>
          <span className="hero-chip">Open <b>{positions?.open_count||0}</b></span>
          <span className="hero-chip">Win Rate <b>{positions?.win_rate||0}%</b></span>
        </div>
      </div>

      <div className="metric-grid">
        <div className="metric">
          <div className="metric-label"><span style={{color:"var(--lav)"}}>◆</span> MT5 Balance</div>
          <div className="metric-value" style={{color:"var(--lav-2)"}}>
            ${(account?.balance||0).toLocaleString(undefined,{minimumFractionDigits:2,maximumFractionDigits:2})}
          </div>
          <div className="metric-sub">{account?.currency||"USD"} · IC Markets demo</div>
        </div>
        <div className="metric">
          <div className="metric-label">Equity</div>
          <div className="metric-value" style={{color:"var(--text)"}}>
            ${(account?.equity||0).toLocaleString(undefined,{minimumFractionDigits:2,maximumFractionDigits:2})}
          </div>
          <div className="metric-sub">free margin ${(account?.free_margin||0).toFixed(2)}</div>
        </div>
        <div className="metric">
          <div className="metric-label">Total P&L</div>
          <div className="metric-value" style={{color:(positions?.total_pnl||0)>=0?"var(--buy)":"var(--sell)"}}>
            {(positions?.total_pnl||0)>=0?"+":""}${(positions?.total_pnl||0).toFixed(2)}
          </div>
          <div className="metric-sub">{positions?.closed_trades||0} closed trades</div>
        </div>
        <div className="metric">
          <div className="metric-label">Win Rate</div>
          <div className="metric-value" style={{color:"var(--info)"}}>{positions?.win_rate||0}%</div>
          <div className="metric-sub"><span style={{color:"var(--buy)"}}>{positions?.wins||0}W</span> / <span style={{color:"var(--sell)"}}>{positions?.losses||0}L</span></div>
        </div>
      </div>

      {openPos.length>0&&(
        <>
          <div className="sec-head"><div className="sec-title">Open Positions</div><div className="sec-sub">{openPos.length} live</div></div>
          <div className="grid-pairs" style={{marginBottom:8}}>
            {openPos.map(p=>(
              <div key={p.id} className={`pair-card ${p.signal==="BUY"?"buy":"sell"}`}>
                <div className="pair-head">
                  <div className="pair-symbol">{p.symbol}</div>
                  <span className={`chip ${p.signal==="BUY"?"chip-bull":"chip-bear"}`}><span className="chip-dot pulse"/>{p.signal}</span>
                </div>
                <div className="pair-price-label">Live P&L</div>
                <div className="pair-price" style={{color:p.pnl>=0?"var(--buy)":"var(--sell)"}}>
                  {p.pnl>=0?"+":""}${p.pnl?.toFixed(2)}
                </div>
                <div className="range-labels" style={{marginTop:10}}>
                  <span>Entry {p.entry?.toFixed(5)}</span>
                  <span>Now {p.current?.toFixed(5)}</span>
                </div>
                <div className="range-labels" style={{marginTop:4}}>
                  <span style={{color:"var(--sell)"}}>SL {p.sl?.toFixed(5)}</span>
                  <span style={{color:"var(--buy)"}}>TP {p.tp?.toFixed(5)}</span>
                </div>
                <div style={{display:"flex",gap:6,marginTop:10,flexWrap:"wrap"}}>
                  <span className="chip chip-live">{p.lots} lots</span>
                  <span className="chip chip-neutral">{p.confidence}%</span>
                  <span className="chip chip-neutral">{p.kronos_bias}</span>
                </div>
              </div>
            ))}
          </div>
        </>
      )}

      <div className="sec-head">
        <div className="sec-title">Market Signals</div>
        <div className="sec-sub">{pairs?.length||0} pairs · PDH/PDL + Kronos bias</div>
      </div>

      <div className="grid-pairs">
        {pairs?.map(sym=>(
          <CRTSignalCard key={sym} symbol={sym} bias={biases?.[sym]} levels={crt_levels?.[sym]}/>
        ))}
      </div>
    </div>
  );
}
