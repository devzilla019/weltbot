import{useState,useMemo}from"react";
import{useApp}from"../context/AppContext";
import{forexApi}from"../api";
import{useLiveData}from"../hooks/useLiveData";
import{makeApi}from"../api";
import PositionRow from"./PositionRow";
import RiskGauge from"./RiskGauge";
import SessionClock from"./SessionClock";
import{fmtMoney,clockTime,relTime}from"../utils/format";

/**
 * Live control room — the trading surface.
 *
 * Everything needed to run the bot without leaving the page: live P&L,
 * one-click close, close-all with confirmation, the risk budget, and the
 * session clock that says whether trading is currently allowed.
 */
export default function ControlRoom(){
  const{token,showToast}=useApp();
  const api=useMemo(()=>makeApi(token),[token]);
  const live=useLiveData(api,forexApi);

  const[busy,setBusy]=useState(false);
  const[confirmAll,setConfirmAll]=useState(false);

  const positions=live.forexPositions?.open_positions||[];
  const stale=live.forexPositions?.stale;
  const unrealised=positions.reduce((s,p)=>s+(p.pnl||0),0);

  const closed=live.forexTrades.filter(t=>t.outcome!=="OPEN");
  const withPnl=closed.filter(t=>t.pnl!=null);
  const realised=withPnl.reduce((s,t)=>s+(t.pnl||0),0);
  const wins=withPnl.filter(t=>t.pnl>0).length;
  const winRate=withPnl.length?Math.round(wins/withPnl.length*100):0;

  const isLive=live.botStatus?.running&&!live.botStatus?.paused;

  const act=async(fn,label)=>{
    setBusy(true);
    try{await fn();}
    catch(e){showToast(e.message||`${label} failed`,"error");}
    finally{setBusy(false);await live.refresh();}
  };

  const closeOne=id=>act(async()=>{
    const r=await forexApi.closeTrade(id);
    if(r.success)showToast(`Closed ${r.symbol} · ${fmtMoney(r.pnl)}`,"success");
    else showToast(r.error||"Close failed","error");
  },"Close");

  const closeAll=()=>act(async()=>{
    setConfirmAll(false);
    const r=await forexApi.closeAll();
    if(r.failed>0&&r.closed===0)showToast(r.error||"Close all failed","error");
    else showToast(`Closed ${r.closed} · ${fmtMoney(r.total_pnl)}`,r.failed>0?"warn":"success");
  },"Close all");

  const scan=()=>act(async()=>{
    await api.scanNow();
    showToast("Scan triggered","info");
  },"Scan");

  const toggleBot=()=>act(async()=>{
    if(isLive){await api.stopBot();showToast("Bot stopped","warn");}
    else{await api.startBot();showToast("Bot started","success");}
  },"Toggle");

  return(
    <div className="control-room">
      {/* ── Status strip ─────────────────────────────────────────────── */}
      <div className="cr-strip">
        <div className="cr-status" data-live={isLive}>
          <span className="cr-status-dot"/>
          <div>
            <b>{isLive?"LIVE":live.botStatus?.paused?"PAUSED":"STOPPED"}</b>
            <em>{live.botStatus?.pause_reason||"autonomous"}</em>
          </div>
        </div>

        <SessionClock/>

        <div className="cr-strip-actions">
          <button className={`btn ${isLive?"btn-danger":"btn-success"} btn-sm`}
                  disabled={busy} onClick={toggleBot}>
            {isLive?"■ Stop":"▶ Start"}
          </button>
          <button className="btn btn-scan btn-sm" disabled={busy} onClick={scan}>⟳ Scan</button>
          {positions.length>0&&(confirmAll
            ?<>
              <button className="btn btn-danger btn-sm" disabled={busy} onClick={closeAll}>
                Confirm close {positions.length}
              </button>
              <button className="btn btn-ghost btn-sm" onClick={()=>setConfirmAll(false)}>Cancel</button>
             </>
            :<button className="btn btn-danger btn-sm" disabled={busy}
                     onClick={()=>setConfirmAll(true)}>
               ✕ Close All ({positions.length})
             </button>)}
        </div>
      </div>

      {live.backendDown&&(
        <div className="cr-banner danger">
          ⚠ Backend unreachable — showing last known state
          <button onClick={live.refresh}>Retry</button>
        </div>)}
      {stale&&(
        <div className="cr-banner warn">
          ⚠ Broker position data unavailable — figures may be stale
        </div>)}

      {/* ── Headline numbers ─────────────────────────────────────────── */}
      <div className="cr-metrics">
        <div className="cr-metric">
          <label>Unrealised</label>
          <b style={{color:(unrealised||0)>=0?"var(--buy)":"var(--sell)"}}>{fmtMoney(unrealised)}</b>
          <em>{positions.length} open position{positions.length===1?"":"s"}</em>
        </div>
        <div className="cr-metric">
          <label>Realised</label>
          <b style={{color:(realised||0)>=0?"var(--buy)":"var(--sell)"}}>{fmtMoney(realised)}</b>
          <em>{withPnl.length} closed{closed.length>withPnl.length?` · ${closed.length-withPnl.length} unknown`:""}</em>
        </div>
        <div className="cr-metric">
          <label>Win rate</label>
          <b style={{color:closed.length===0?"var(--text3)":winRate>=50?"var(--buy)":"var(--sell)"}}>
            {closed.length===0?"—":`${winRate}%`}
          </b>
          <em>{closed.length===0?"no closed trades":`${wins}W / ${closed.length-wins}L`}</em>
        </div>
        <div className="cr-metric">
          <label>Equity</label>
          <b>{fmtMoney(live.forex?.account?.equity??live.botStatus?.forex_equity,false)}</b>
          <em>balance {fmtMoney(live.forex?.account?.balance??live.botStatus?.forex_balance,false)}</em>
        </div>
      </div>

      <div className="cr-split">
        {/* ── Positions ─────────────────────────────────────────────── */}
        <div className="cr-panel">
          <div className="cr-panel-head">
            <span className="cr-panel-title">Open Positions</span>
            <span className="cr-panel-sub">
              {positions.length?`${fmtMoney(unrealised)} unrealised`:"nothing open"}
            </span>
          </div>

          {positions.length===0
            ?<div className="cr-empty">
              <span className="cr-empty-icon">◇</span>
              <p>No open positions</p>
              <em>The bot opens trades when a valid setup clears {88}% confidence</em>
            </div>
            :<div className="pos-list">
              {positions.map(p=><PositionRow key={p.id} p={p} busy={busy} onClose={closeOne}/>)}
            </div>}
        </div>

        {/* ── Risk + activity ───────────────────────────────────────── */}
        <div className="cr-side">
          <RiskGauge risk={live.dailyRisk}/>

          <div className="cr-panel">
            <div className="cr-panel-head">
              <span className="cr-panel-title">Recent Activity</span>
              <span className="cr-panel-sub">{clockTime(live.lastUpdate)}</span>
            </div>
            <div className="activity">
              {closed.length===0
                ?<div className="cr-empty small"><em>No closed trades yet</em></div>
                :closed.slice(0,8).map(t=>{
                  const has= t.pnl!=null;
                  const up = has && t.pnl>=0;
                  return(
                  <div key={t.id} className="activity-row">
                    <span className={`activity-dot ${has?(up?"win":"loss"):"unknown"}`}/>
                    <span className="activity-sym">{t.symbol}</span>
                    <span className={`chip ${t.signal==="BUY"?"chip-bull":"chip-bear"}`}>{t.signal}</span>
                    <span className="activity-pnl mono"
                          style={{color:has?(up?"var(--buy)":"var(--sell)"):"var(--text3)"}}>
                      {has?fmtMoney(t.pnl):"—"}
                    </span>
                    <span className="activity-time">{relTime(t.closed)}</span>
                  </div>
                  );
                })}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
