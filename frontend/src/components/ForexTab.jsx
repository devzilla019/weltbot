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
  const[cascade,setCascade]=useState(null);

  const load=async()=>{
    try{const d=await forexApi.getStatus();setData(d);setErr(null);}
    catch(e){setErr(e.message);}
    finally{setLoading(false);}
  };
  useEffect(()=>{
    load();
    forexApi.kronosStatus().then(setKronos).catch(()=>{});
    forexApi.cascadeStats().then(setCascade).catch(()=>{});
    const t=setInterval(load,60000);
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

  const{biases,crt_levels,positions,account,kronos_available,pairs,daily_risk}=data;
  const openPos=positions?.open_positions||[];
  const risk=daily_risk;

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

      {risk&&(
        <div className="glass" style={{padding:16,marginBottom:16}}>
          <div style={{display:"flex",alignItems:"center",justifyContent:"space-between",marginBottom:12,flexWrap:"wrap",gap:8}}>
            <div style={{display:"flex",alignItems:"center",gap:10}}>
              <span className="sec-title" style={{fontSize:13}}>Daily Risk Budget</span>
              {risk.halted
                ? <span className="chip chip-bear" style={{fontSize:8,padding:"1px 6px"}}>HALTED</span>
                : <span className="chip chip-bull" style={{fontSize:8,padding:"1px 6px"}}>ACTIVE</span>}
              {!risk.tradeable&&<span className="chip chip-wait" style={{fontSize:8,padding:"1px 6px"}}>BALANCE TOO LOW</span>}
            </div>
            <div style={{fontFamily:"var(--font-mono)",fontSize:9,color:"var(--text3)"}}>
              resets 00:00 UTC
            </div>
          </div>

          <div style={{display:"grid",gridTemplateColumns:"repeat(auto-fit,minmax(130px,1fr))",gap:8,marginBottom:12}}>
            <div style={{background:"var(--surface2)",border:"1px solid var(--border)",borderRadius:6,padding:"8px 10px"}}>
              <div style={{fontSize:8,color:"var(--text3)",fontFamily:"var(--font-mono)",letterSpacing:"0.08em"}}>RISK / TRADE</div>
              <div style={{fontSize:14,fontFamily:"var(--font-mono)",color:"var(--lav-2)",fontWeight:600}}>
                ${risk.risk_per_trade?.toFixed(2)}
              </div>
              <div style={{fontSize:9,color:"var(--text3)",fontFamily:"var(--font-mono)"}}>{risk.risk_pct}% of balance</div>
            </div>
            <div style={{background:"rgba(255,92,138,0.08)",border:"1px solid rgba(255,92,138,0.2)",borderRadius:6,padding:"8px 10px"}}>
              <div style={{fontSize:8,color:"var(--text3)",fontFamily:"var(--font-mono)",letterSpacing:"0.08em"}}>TODAY'S P&L</div>
              <div style={{fontSize:14,fontFamily:"var(--font-mono)",fontWeight:600,color:(risk.realised_pnl||0)>=0?"var(--buy)":"var(--sell)"}}>
                {(risk.realised_pnl||0)>=0?"+":""}${(risk.realised_pnl||0).toFixed(2)}
              </div>
              <div style={{fontSize:9,color:"var(--text3)",fontFamily:"var(--font-mono)"}}>{risk.trades_today||0} closed today</div>
            </div>
            <div style={{background:"rgba(245,185,66,0.08)",border:"1px solid rgba(245,185,66,0.2)",borderRadius:6,padding:"8px 10px"}}>
              <div style={{fontSize:8,color:"var(--text3)",fontFamily:"var(--font-mono)",letterSpacing:"0.08em"}}>LOSS BUDGET LEFT</div>
              <div style={{fontSize:14,fontFamily:"var(--font-mono)",fontWeight:600,color:"var(--warn)"}}>
                ${risk.remaining_budget?.toFixed(2)}
              </div>
              <div style={{fontSize:9,color:"var(--text3)",fontFamily:"var(--font-mono)"}}>of ${risk.daily_limit_amount?.toFixed(2)} ({risk.daily_limit_pct}%)</div>
            </div>
            <div style={{background:"var(--surface2)",border:"1px solid var(--border)",borderRadius:6,padding:"8px 10px"}}>
              <div style={{fontSize:8,color:"var(--text3)",fontFamily:"var(--font-mono)",letterSpacing:"0.08em"}}>OPEN</div>
              <div style={{fontSize:14,fontFamily:"var(--font-mono)",color:"var(--text)",fontWeight:600}}>{risk.open_positions||0}</div>
              <div style={{fontSize:9,color:"var(--text3)",fontFamily:"var(--font-mono)"}}>max risk {risk.max_implied_risk_pct}%/trade</div>
            </div>
          </div>

          {/* Loss budget meter */}
          <div style={{height:6,background:"var(--surface2)",borderRadius:3,overflow:"hidden"}}>
            <div style={{
              height:"100%",
              borderRadius:3,
              width:`${Math.min(100,Math.max(0,100-(risk.remaining_pct||0)))}%`,
              background:risk.halted?"var(--sell)":(risk.remaining_pct<40?"var(--warn)":"var(--buy)"),
              transition:"width 0.6s ease",
            }}/>
          </div>
          <div style={{display:"flex",justifyContent:"space-between",marginTop:5,fontSize:9,fontFamily:"var(--font-mono)",color:"var(--text3)"}}>
            <span>{risk.remaining_pct}% budget remaining</span>
            <span>{risk.loss_used>0?`-$${risk.loss_used.toFixed(2)} used`:""}</span>
          </div>

          {risk.halted&&(
            <div className="info-box info-box-red" style={{marginTop:10}}>
              Daily loss limit reached — new forex entries are halted until 00:00 UTC.
            </div>
          )}
          {!risk.tradeable&&!risk.halted&&(
            <div className="info-box info-box-warn" style={{marginTop:10}}>
              Balance ${risk.balance?.toFixed(2)} is below the ${risk.min_balance} minimum — entries will be skipped.
            </div>
          )}
        </div>
      )}

      {cascade&&cascade.chains?.length>0&&(
        <>
          <div className="sec-head">
            <div className="sec-title">Cascade Performance</div>
            <div className="sec-sub">{cascade.total_closed} closed trades · by timeframe chain</div>
          </div>
          <div className="glass" style={{padding:0,marginBottom:16,overflow:"hidden"}}>
            <div className="table-wrap">
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Chain</th><th>POI</th><th>Trades</th><th>Wins</th><th>Losses</th><th>Win Rate</th><th>P&L</th>
                  </tr>
                </thead>
                <tbody>
                  {cascade.chains.map(c=>(
                    <tr key={c.chain}>
                      <td>
                        <span style={{fontFamily:"var(--font-mono)",fontSize:11}}>
                          <span className="chip chip-live" style={{fontSize:8,padding:"1px 6px"}}>{c.crt_timeframe?.toUpperCase()||"?"}</span>
                          <span style={{color:"var(--text3)",margin:"0 4px"}}>›</span>
                          <span className="chip chip-neutral" style={{fontSize:8,padding:"1px 6px"}}>{c.confirm_timeframe?.toUpperCase()||"?"}</span>
                          <span style={{color:"var(--text3)",margin:"0 4px"}}>›</span>
                          <span className="chip chip-neutral" style={{fontSize:8,padding:"1px 6px"}}>{c.entry_timeframe?.toUpperCase()||"?"}</span>
                        </span>
                      </td>
                      <td style={{fontFamily:"var(--font-mono)",fontSize:10,color:"var(--text2)"}}>{c.poi||"—"}</td>
                      <td className="mono">{c.trades}</td>
                      <td className="mono" style={{color:"var(--buy)"}}>{c.wins}</td>
                      <td className="mono" style={{color:"var(--sell)"}}>{c.losses}</td>
                      <td className="mono" style={{color:c.win_rate>=50?"var(--buy)":"var(--sell)"}}>{c.win_rate}%</td>
                      <td className="mono" style={{color:c.pnl>=0?"var(--buy)":"var(--sell)"}}>{c.pnl>=0?"+":""}${Math.abs(c.pnl).toFixed(2)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </>
      )}

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
                {(p.tp1!=null||p.tp2!=null)&&(
                  <div className="range-labels" style={{marginTop:4}}>
                    <span style={{color:"var(--warn)"}}>TP1 {p.tp1?.toFixed(5)??"—"}</span>
                    <span style={{color:"var(--buy)"}}>TP2 {(p.tp2??p.tp)?.toFixed(5)??"—"}</span>
                  </div>
                )}
                <div style={{display:"flex",gap:6,marginTop:10,flexWrap:"wrap"}}>
                  <span className="chip chip-live">{p.lots} lots</span>
                  <span className="chip chip-neutral">{p.confidence}%</span>
                  <span className="chip chip-neutral">{p.kronos_bias}</span>
                  {p.entry_type&&<span className="chip chip-bull">{p.entry_type}</span>}
                  {p.partial_tp_hit&&<span className="chip chip-bull">50% closed</span>}
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
        {pairs?.map((sym,i)=>(
          <CRTSignalCard key={sym} symbol={sym} index={i} bias={biases?.[sym]} levels={crt_levels?.[sym]}/>
        ))}
      </div>
    </div>
  );
}
