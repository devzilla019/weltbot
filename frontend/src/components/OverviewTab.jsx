import{useState,useEffect}from"react";
import SignalCard from"./SignalCard";
import PositionCard from"./PositionCard";
import RiskPanel from"./RiskPanel";
const getLev=c=>c>=98?100:c>=95?50:c>=90?20:10;
const getLevClass=c=>c>=98?"lev-100":c>=95?"lev-50":c>=90?"lev-20":"lev-10";
const fmtB=v=>`$${(v||0).toLocaleString(undefined,{minimumFractionDigits:2,maximumFractionDigits:2})}`;

export default function OverviewTab({summary,portfolio,signals,botStatus,handleCloseTrade,loading,backendDown}){
  const[selected,setSelected]=useState(null);
  const[prevBal,setPrevBal]=useState(null);
  const[balFlash,setBalFlash]=useState(null);
  const pnl=summary?.total_pnl??0;
  const wr=summary?.win_rate??0;
  const positions=portfolio?.positions||[];
  const cryptoBal=portfolio?.balance_usdt??botStatus?.balance_usdt??0;
  const forexBal=portfolio?.forex_balance??botStatus?.forex_balance??0;
  const forexPL=portfolio?.forex_profit_loss??botStatus?.forex_unrealized??0;
  const totalBal=portfolio?.total_balance??(cryptoBal+forexBal);
  const unrealized=portfolio?.unrealized_pnl??0;

  useEffect(()=>{
    if(prevBal!==null&&cryptoBal!==prevBal&&cryptoBal>0){setBalFlash(cryptoBal>prevBal?"up":"down");setTimeout(()=>setBalFlash(null),2000);}
    if(cryptoBal>0)setPrevBal(cryptoBal);
  },[cryptoBal]);

  const activeS=signals.filter(s=>s.signal_data?.signal!=="HOLD").sort((a,b)=>(b.signal_data?.confidence||0)-(a.signal_data?.confidence||0));
  const holdS=signals.filter(s=>s.signal_data?.signal==="HOLD");

  return(
    <div>
      <div className="hero">
        <div className="hero-title">Autonomous <span className="accent">Trading Engine</span></div>
        <div className="hero-sub">Kronos AI · CRT · Smart Money Concepts — Forex, Metals & Crypto</div>
        <div className="hero-chips">
          <span className="hero-chip">Status <b>{botStatus?.running?(botStatus?.paused?"PAUSED":"LIVE"):"STOPPED"}</b></span>
          <span className="hero-chip">Signals <b>{signals.length}</b></span>
          <span className="hero-chip">Open <b>{summary?.open??0}</b></span>
          <span className="hero-chip">Win Rate <b>{wr}%</b></span>
        </div>
      </div>

      <div className="metric-grid">
        <div className="metric" style={{boxShadow:balFlash?`0 0 24px ${balFlash==="up"?"rgba(52,229,176,0.25)":"rgba(255,92,138,0.25)"}`:"none"}}>
          <div className="metric-label">Total Balance</div>
          <div className="metric-value" style={{color:"var(--text)",fontSize:22}}>{fmtB(totalBal)}</div>
          <div style={{marginTop:8,display:"flex",flexDirection:"column",gap:3,fontFamily:"var(--font-mono)",fontSize:11}}>
            <div style={{display:"flex",justifyContent:"space-between"}}>
              <span style={{color:"var(--text3)"}}><span style={{color:"var(--warn)"}}>₿</span> Crypto</span>
              <span style={{color:"var(--buy)"}}>{fmtB(cryptoBal)}</span>
            </div>
            <div style={{display:"flex",justifyContent:"space-between"}}>
              <span style={{color:"var(--text3)"}}><span style={{color:"var(--lav)"}}>◆</span> Forex</span>
              <span style={{color:"var(--lav-2)"}}>{fmtB(forexBal)}</span>
            </div>
            <div style={{display:"flex",justifyContent:"space-between",borderTop:"1px solid var(--border)",marginTop:3,paddingTop:3,fontWeight:700}}>
              <span style={{color:"var(--text2)"}}>Total</span>
              <span style={{color:"var(--text)"}}>{fmtB(totalBal)}</span>
            </div>
          </div>
        </div>
        <div className="metric">
          <div className="metric-label">Forex P&L</div>
          <div className="metric-value" style={{color:forexPL>=0?"var(--buy)":"var(--sell)"}}>{forexPL>=0?"+":""}${Math.abs(forexPL).toFixed(2)}</div>
          <div className="metric-sub">Capital.com demo</div>
        </div>
        <div className="metric">
          <div className="metric-label">Realized P&L</div>
          <div className="metric-value" style={{color:pnl>=0?"var(--buy)":"var(--sell)"}}>{pnl>=0?"+":""}${Math.abs(pnl).toFixed(2)}</div>
          <div className="metric-sub">{summary?.total??0} total trades</div>
        </div>
        <div className="metric">
          <div className="metric-label">Unrealized</div>
          <div className="metric-value" style={{color:unrealized>=0?"var(--buy)":"var(--sell)"}}>{unrealized>=0?"+":""}${Math.abs(unrealized).toFixed(2)}</div>
          <div className="metric-sub">{positions.length} open positions</div>
        </div>
        <div className="metric">
          <div className="metric-label">Win Rate</div>
          <div className="metric-value" style={{color:wr>=55?"var(--buy)":wr>=45?"var(--warn)":"var(--sell)"}}>{wr}%</div>
          <div className="metric-sub"><span style={{color:"var(--buy)"}}>{summary?.wins??0}W</span> / <span style={{color:"var(--sell)"}}>{summary?.losses??0}L</span></div>
        </div>
      </div>

      {botStatus?.active_setups?.length>0&&(
        <div style={{display:"flex",gap:6,alignItems:"center",marginBottom:12,flexWrap:"wrap"}}>
          <span style={{fontSize:10,color:"var(--text3)",fontFamily:"var(--font-mono)"}}>L2 WATCHING:</span>
          {botStatus.active_setups.map(s=><span key={s} className="chip chip-live">{s.replace("/USDT","")}</span>)}
          <span style={{fontSize:10,color:"var(--text3)"}}>· checking every 60s</span>
        </div>
      )}

      {positions.length>0&&(
        <div style={{marginBottom:16}}>
          <div className="sec-head"><div className="sec-title">Live Positions</div><div className="sec-sub">{positions.length} open · live risk & reward</div></div>

          {/* Aggregate risk dashboard */}
          <div className="metric-grid" style={{marginBottom:12}}>
            <div className="metric">
              <div className="metric-label">Total at Risk</div>
              <div className="metric-value" style={{color:"var(--sell)",fontSize:20}}>-${(portfolio?.total_risk_usd??0).toFixed(2)}</div>
              <div className="metric-sub">{(portfolio?.risk_pct_of_balance??0).toFixed(2)}% of balance</div>
            </div>
            <div className="metric">
              <div className="metric-label">Total Target</div>
              <div className="metric-value" style={{color:"var(--buy)",fontSize:20}}>+${(portfolio?.total_reward_usd??0).toFixed(2)}</div>
              <div className="metric-sub">if all TP hit</div>
            </div>
            <div className="metric">
              <div className="metric-label">Avg R:R</div>
              <div className="metric-value" style={{color:"var(--lav-2)",fontSize:20}}>1:{(portfolio?.avg_risk_reward??0).toFixed(2)}</div>
              <div className="metric-sub">reward / risk</div>
            </div>
            <div className="metric">
              <div className="metric-label">Open P&L</div>
              <div className="metric-value" style={{color:unrealized>=0?"var(--buy)":"var(--sell)",fontSize:20}}>{unrealized>=0?"+":""}${Math.abs(unrealized).toFixed(2)}</div>
              <div className="metric-sub">unrealized</div>
            </div>
          </div>

          <div style={{display:"grid",gridTemplateColumns:"repeat(auto-fill,minmax(280px,1fr))",gap:12}}>
            {positions.map((p,i)=><PositionCard key={i} position={p} onClose={()=>handleCloseTrade(p.trade_id)}/>)}
          </div>
        </div>
      )}

      <div className="page-grid">
        <div>
          <div style={{display:"flex",gap:6,alignItems:"center",marginBottom:12,flexWrap:"wrap"}}>
            <span style={{fontSize:10,color:"var(--text3)",fontFamily:"var(--font-mono)"}}>LEVERAGE:</span>
            {[["98%+→100x","lev-100"],["95%+→50x","lev-50"],["90-94%→20x","lev-20"],["85-89%→10x","lev-10"]].map(([l,c])=><span key={l} className={`lev-badge ${c}`}>{l}</span>)}
          </div>
          <div className="sec-head">
            <div><div className="sec-title">Structure Signals</div><div className="sec-sub">{signals.length} assets · BOS→Fib→OB→MA→Entry</div></div>
          </div>
          {activeS.length>0&&<div style={{marginBottom:10}}><div style={{fontSize:10,color:"var(--lav-2)",fontFamily:"var(--font-mono)",marginBottom:6,letterSpacing:"0.06em"}}>✦ ACTIVE — {activeS.length}</div><div className="signal-grid">{activeS.map(d=><SignalCard key={d.signal_data?.symbol} data={d} selected={selected?.signal_data?.symbol===d.signal_data?.symbol} onSelect={setSelected} getLev={getLev} getLevClass={getLevClass}/>)}</div></div>}
          <div className="signal-grid">{holdS.map(d=><SignalCard key={d.signal_data?.symbol} data={d} selected={selected?.signal_data?.symbol===d.signal_data?.symbol} onSelect={setSelected} getLev={getLev} getLevClass={getLevClass}/>)}</div>
          {signals.length===0&&!loading&&<div className="glass" style={{padding:0}}><div className="empty-state"><div className="empty-icon">📡</div>Warming signal cache — 30–60s on first load</div></div>}
        </div>
        <div className="risk-panel"><RiskPanel selected={selected}/></div>
      </div>
    </div>
  );
}
