import{useState,useEffect}from"react";
import CRTSignalCard from"./CRTSignalCard";
import{forexApi}from"../api";
import{useApp}from"../context/AppContext";

const fmtMoney=v=>`${v>=0?"+":""}$${Math.abs(v||0).toFixed(2)}`;
const fmtP=v=>v==null?"—":Number(v).toFixed(5);

export default function ForexTab(){
  const{showToast}=useApp();
  const[data,setData]=useState(null);
  const[loading,setLoading]=useState(true);
  const[err,setErr]=useState(null);
  const[test,setTest]=useState(null);
  const[testing,setTesting]=useState(false);
  const[kronos,setKronos]=useState(null);
  const[cascade,setCascade]=useState(null);
  const[busy,setBusy]=useState(false);
  const[history,setHistory]=useState([]);

  const load=async()=>{
    try{
      const d=await forexApi.getStatus();
      setData(d);setErr(null);
      forexApi.getTrades(30).then(setHistory).catch(()=>{});
    }
    catch(e){setErr(e.message);}
    finally{setLoading(false);}
  };

  const handleClose=async(id)=>{
    setBusy(true);
    try{
      const r=await forexApi.closeTrade(id);
      if(r.success){showToast(`Closed ${r.symbol} · P&L ${fmtMoney(r.pnl)}`,"success");await load();}
      else showToast(r.error||"Close failed","error");
    }catch(e){showToast(e.message||"Close failed","error");}
    finally{setBusy(false);}
  };

  const handleCloseAll=async()=>{
    setBusy(true);
    try{
      const r=await forexApi.closeAll();
      if(r.failed>0&&r.closed===0) showToast(r.error||"Close all failed","error");
      else showToast(`Closed ${r.closed} position${r.closed===1?"":"s"} · P&L ${fmtMoney(r.total_pnl)}`,
                     r.failed>0?"warn":"success");
      await load();
    }catch(e){showToast(e.message||"Close all failed","error");}
    finally{setBusy(false);}
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
  const totalOpenPnl=openPos.reduce((s,p)=>s+(p.pnl||0),0);
  const closedTrades=history.filter(t=>t.outcome!=="OPEN");
  const closedPnl=closedTrades.reduce((s,t)=>s+(t.pnl||0),0);

  const handleClearHistory=async()=>{
    setBusy(true);
    try{
      const r=await forexApi.clearTrades();
      if(r.success){showToast(`Cleared ${r.deleted} closed trades`,"success");await load();}
      else showToast(r.error||"Clear failed","error");
    }catch(e){showToast(e.message||"Clear failed","error");}
    finally{setBusy(false);}
  };

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
          <div className="sec-head">
            <div className="sec-title">Open Positions</div>
            <div style={{display:"flex",alignItems:"center",gap:10}}>
              <span className="sec-sub">{openPos.length} live · {fmtMoney(totalOpenPnl)} unrealised</span>
              <button
                className="btn btn-danger btn-sm"
                disabled={busy}
                onClick={handleCloseAll}
                title="Close every open forex position">
                ✕ Close All
              </button>
            </div>
          </div>
          <div className="glass" style={{padding:0,marginBottom:16,overflow:"hidden"}}>
            <div className="table-wrap">
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Symbol</th><th>Side</th><th>Size</th><th>Entry</th>
                    <th>Last Price</th><th>Stop Loss</th><th>Take Profit</th>
                    <th>P&L</th><th>Progress</th><th></th>
                  </tr>
                </thead>
                <tbody>
                  {openPos.map(p=>{
                    const up=(p.pnl||0)>=0;
                    return(
                      <tr key={p.id}>
                        <td>
                          <div style={{display:"flex",alignItems:"center",gap:6}}>
                            <span style={{fontFamily:"var(--font-display)",fontWeight:700,fontSize:12}}>{p.symbol}</span>
                            {p.entry_type&&<span className="chip chip-live" style={{fontSize:8,padding:"1px 5px"}}>{p.entry_type}</span>}
                            {p.partial_tp_hit&&<span className="chip chip-bull" style={{fontSize:8,padding:"1px 5px"}}>50% closed</span>}
                          </div>
                        </td>
                        <td>
                          <span className={`chip ${p.signal==="BUY"?"chip-bull":"chip-bear"}`} style={{fontSize:8,padding:"1px 6px"}}>
                            {p.signal}
                          </span>
                        </td>
                        <td className="mono">{Number(p.size||0).toLocaleString()}</td>
                        <td className="mono">{fmtP(p.entry)}</td>
                        <td className="mono" style={{color:up?"var(--buy)":"var(--sell)"}}>{fmtP(p.current)}</td>
                        <td className="mono" style={{color:"var(--sell)"}}>{fmtP(p.sl)}</td>
                        <td className="mono" style={{color:"var(--buy)"}}>{fmtP(p.tp2??p.tp)}</td>
                        <td className="mono" style={{color:up?"var(--buy)":"var(--sell)",fontWeight:600}}>
                          {up?"+":""}${(p.pnl||0).toFixed(2)}
                          <div style={{fontSize:9,color:"var(--text3)",fontWeight:400}}>
                            {up?"+":""}{(p.pnl_pct||0).toFixed(3)}%
                          </div>
                        </td>
                        <td style={{minWidth:70}}>
                          <div style={{height:4,background:"var(--surface2)",borderRadius:2,overflow:"hidden"}}>
                            <div style={{height:"100%",borderRadius:2,width:`${p.progress||0}%`,
                              background:up?"var(--buy)":"var(--sell)",transition:"width 0.6s ease"}}/>
                          </div>
                          <div style={{fontSize:9,color:"var(--text3)",fontFamily:"var(--font-mono)",marginTop:3}}>
                            {(p.progress||0).toFixed(0)}% · R:R 1:{p.risk_reward||0}
                          </div>
                        </td>
                        <td>
                          <button
                            className="btn btn-danger btn-xs"
                            disabled={busy}
                            onClick={()=>handleClose(p.id)}>
                            Close
                          </button>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
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

      {history.filter(t=>t.outcome!=="OPEN").length>0&&(
        <>
          <div className="sec-head" style={{marginTop:20}}>
            <div className="sec-title">Closed Trades</div>
            <div style={{display:"flex",alignItems:"center",gap:10}}>
              <span className="sec-sub">
                {closedTrades.length} closed · {fmtMoney(closedPnl)} realised
              </span>
              <button
                className="btn btn-sm"
                disabled={busy}
                onClick={handleClearHistory}
                title="Clear closed trade history">
                Clear
              </button>
            </div>
          </div>
          <div className="glass" style={{padding:0,marginBottom:16,overflow:"hidden"}}>
            <div className="table-wrap">
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Symbol</th><th>Side</th><th>Entry</th><th>Exit</th>
                    <th>Type</th><th>Conf</th><th>P&L</th><th>Closed</th>
                  </tr>
                </thead>
                <tbody>
                  {closedTrades.map(t=>{
                    const up=(t.pnl||0)>=0;
                    return(
                      <tr key={t.id}>
                        <td style={{fontFamily:"var(--font-display)",fontWeight:700,fontSize:12}}>{t.symbol}</td>
                        <td>
                          <span className={`chip ${t.signal==="BUY"?"chip-bull":"chip-bear"}`} style={{fontSize:8,padding:"1px 6px"}}>
                            {t.signal}
                          </span>
                        </td>
                        <td className="mono">{fmtP(t.entry)}</td>
                        <td className="mono">{t.pnl!=null?fmtP(t.tp2??t.tp):"—"}</td>
                        <td>{t.entry_type&&<span className="chip chip-live" style={{fontSize:8,padding:"1px 5px"}}>{t.entry_type}</span>}</td>
                        <td className="mono">{(t.confidence||0).toFixed(0)}%</td>
                        <td className="mono" style={{color:up?"var(--buy)":"var(--sell)",fontWeight:600}}>
                          {t.pnl!=null?`${up?"+":""}$${Math.abs(t.pnl).toFixed(2)}`:"—"}
                        </td>
                        <td style={{fontSize:9,color:"var(--text3)",fontFamily:"var(--font-mono)"}}>
                          {t.closed?new Date(t.closed).toLocaleString(undefined,
                            {month:"short",day:"numeric",hour:"2-digit",minute:"2-digit"}):"—"}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
