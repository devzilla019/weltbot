import{useState,useEffect}from"react";
import CRTSignalCard from"./CRTSignalCard";
import{forexApi}from"../api";

export default function ForexTab(){
  const[data,setData]=useState(null);
  const[loading,setLoading]=useState(true);
  const[err,setErr]=useState(null);
  const[test,setTest]=useState(null);
  const[testing,setTesting]=useState(false);
  const[kronos,setKronos]=useState(null);

  const load=async()=>{
    try{const d=await forexApi.getStatus();setData(d);setErr(null);}
    catch(e){setErr(e.message);}
    finally{setLoading(false);}
  };
  useEffect(()=>{
    load();
    forexApi.kronosStatus().then(setKronos).catch(()=>{});
    const t=setInterval(load,10000);
    return()=>clearInterval(t);
  },[]);

  const runTest=async()=>{
    setTesting(true);setTest(null);
    try{const r=await forexApi.testConnection();setTest(r);}
    catch(e){setTest({connected:false,error:e.message});}
    finally{setTesting(false);}
  };

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
      <div className="sec-sub" style={{marginTop:8}}>Set FOREX_ENABLED=true and add CAPITAL_API_KEY + CAPITAL_EMAIL + CAPITAL_PASSWORD on Railway</div>
    </div>
  );

  const{biases,crt_levels,positions,account,kronos_available,pairs}=data;
  const openPos=positions?.open_positions||[];

  return(
    <div>
      <div className="hero">
        <div style={{display:"flex",alignItems:"flex-start",justifyContent:"space-between",gap:16,flexWrap:"wrap",position:"relative",zIndex:1}}>
          <div>
            <div className="hero-title">Forex & Metals <span className="accent">Trading</span></div>
            <div className="hero-sub">CRT + SMC + Kronos AI · Capital.com</div>
          </div>
          <button className="btn btn-scan btn-sm" onClick={runTest} disabled={testing}>
            {testing?"Testing…":"⚡ Test Connection"}
          </button>
        </div>
        <div className="hero-chips">
          <span className="hero-chip">Kronos <b>{kronos_available?"ACTIVE":"OFFLINE"}</b></span>
          <span className="hero-chip">Pairs <b>{pairs?.length||0}</b></span>
          <span className="hero-chip">Open <b>{positions?.open_count||0}</b></span>
          <span className="hero-chip">Win Rate <b>{positions?.win_rate||0}%</b></span>
        </div>

        {kronos&&kronos.state!=="ready"&&(
          <div className="info-box info-box-warn" style={{marginTop:12,position:"relative",zIndex:1}}>
            <b>Kronos {kronos.state}:</b> {kronos.error||"model not loaded"} — biases will stay NEUTRAL until fixed.
          </div>
        )}

        {test&&(
          <div className={`info-box ${test.connected?"info-box-green":"info-box-red"}`} style={{marginTop:12,position:"relative",zIndex:1}}>
            <div style={{fontWeight:700,marginBottom:6}}>
              {test.connected?"✓ Capital.com connected":"✕ Connection failed"}
            </div>
            <div style={{display:"grid",gridTemplateColumns:"repeat(auto-fit,minmax(150px,1fr))",gap:6,fontFamily:"var(--font-mono)",fontSize:10}}>
              <span>FOREX_ENABLED: <b>{String(test.forex_enabled)}</b></span>
              <span>Environment: <b>{test.environment||"—"}</b></span>
              <span>API key set: <b>{String(test.api_key_set)}</b></span>
              <span>Email set: <b>{String(test.email_set)}</b></span>
              <span>Password set: <b>{String(test.password_set)}</b></span>
              {test.account&&<span>Balance: <b>${test.account.balance?.toFixed(2)}</b></span>}
              {test.account&&<span>P&L: <b>${test.account.profit_loss?.toFixed(2)}</b></span>}
              {test.account&&<span>Currency: <b>{test.account.currency}</b></span>}
              {test.symbols_ok?.length>0&&<span>Symbols OK: <b>{test.symbols_ok.join(", ")}</b></span>}
              {test.symbols_failed?.length>0&&<span>Symbols failed: <b>{test.symbols_failed.join(", ")}</b></span>}
            </div>
            {test.error&&<div style={{marginTop:8,fontSize:11}}>⚠ {test.error}</div>}
          </div>
        )}
      </div>

      <div className="metric-grid">
        <div className="metric">
          <div className="metric-label"><span style={{color:"var(--lav)"}}>◆</span> Forex Balance</div>
          <div className="metric-value" style={{color:"var(--lav-2)"}}>
            ${(account?.balance||0).toLocaleString(undefined,{minimumFractionDigits:2,maximumFractionDigits:2})}
          </div>
          <div className="metric-sub">{account?.currency||"USD"} · Capital.com demo</div>
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
