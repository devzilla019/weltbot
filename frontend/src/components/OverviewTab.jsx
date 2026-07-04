import { useState } from "react";
import SignalCard   from "./SignalCard";
import PositionCard from "./PositionCard";
import RiskPanel    from "./RiskPanel";

const getLev      = c => c>=98?100:c>=95?50:c>=90?20:10;
const getLevClass = c => c>=98?"lev-100":c>=95?"lev-50":c>=90?"lev-20":"lev-10";

export default function OverviewTab(props) {
  const { summary, portfolio, signals, botStatus, handleCloseTrade, loading } = props;
  const [selected, setSelected] = useState(null);

  const pnl       = summary?.total_pnl ?? 0;
  const wr        = summary?.win_rate  ?? 0;
  const positions = portfolio?.positions || [];
  const activeS   = signals.filter(s=>s.signal_data?.signal!=="HOLD").sort((a,b)=>(b.signal_data?.confidence||0)-(a.signal_data?.confidence||0));
  const holdS     = signals.filter(s=>s.signal_data?.signal==="HOLD");

  const stats = [
    {label:"Balance",    value:`$${(botStatus?.balance_usdt||0).toLocaleString(undefined,{minimumFractionDigits:2,maximumFractionDigits:2})}`, color:"var(--buy)"},
    {label:"Trades",     value:summary?.total??0,  color:"var(--text)"},
    {label:"Open",       value:summary?.open??0,   color:"var(--info)"},
    {label:"Wins",       value:summary?.wins??0,   color:"var(--buy)"},
    {label:"Losses",     value:summary?.losses??0, color:"var(--sell)"},
    {label:"Win Rate",   value:`${wr}%`,           color:wr>=50?"var(--buy)":"var(--sell)"},
    {label:"P&L",        value:`${pnl>=0?"+":""}$${Math.abs(pnl).toFixed(4)}`, color:pnl>=0?"var(--buy)":"var(--sell)"},
    {label:"Unrealized", value:`${(portfolio?.unrealized_pnl??0)>=0?"+":""}$${Math.abs(portfolio?.unrealized_pnl??0).toFixed(4)}`, color:(portfolio?.unrealized_pnl??0)>=0?"var(--buy)":"var(--sell)"},
  ];

  return (
    <div>
      {/* Stats */}
      <div className="stat-grid" style={{ marginBottom:16 }}>
        {stats.map(s=>(
          <div key={s.label} className="stat-card">
            <div className="stat-label">{s.label}</div>
            <div className="stat-value" style={{color:s.color,fontSize:15}}>{s.value}</div>
          </div>
        ))}
      </div>

      {/* Active setups badge */}
      {botStatus?.active_setups?.length>0 && (
        <div style={{display:"flex",gap:6,alignItems:"center",marginBottom:12,flexWrap:"wrap"}}>
          <span style={{fontSize:10,color:"var(--text3)",fontFamily:"var(--font-mono)"}}>L2 WATCHING:</span>
          {botStatus.active_setups.map(s=>(
            <span key={s} style={{fontSize:10,padding:"2px 9px",borderRadius:4,
              background:"rgba(167,139,250,0.1)",color:"var(--purple)",
              border:"1px solid rgba(167,139,250,0.2)",fontFamily:"var(--font-mono)"}}>
              {s.replace("/USDT","")}
            </span>
          ))}
          <span style={{fontSize:10,color:"var(--text3)"}}>· checking every 60s</span>
        </div>
      )}

      {/* Open positions */}
      {positions.length>0 && (
        <div style={{marginBottom:16}}>
          <div className="section-header">
            <div className="section-title">Open Positions — {positions.length}</div>
          </div>
          <div style={{display:"grid",gridTemplateColumns:"repeat(auto-fill,minmax(260px,1fr))",gap:10}}>
            {positions.map((p,i)=>(
              <PositionCard key={i} position={p} onClose={()=>handleCloseTrade(p.trade_id)}/>
            ))}
          </div>
        </div>
      )}

      {/* Main grid */}
      <div className="page-grid">
        <div>
          {/* Leverage guide */}
          <div style={{display:"flex",gap:6,alignItems:"center",marginBottom:12,flexWrap:"wrap"}}>
            <span style={{fontSize:10,color:"var(--text3)",fontFamily:"var(--font-mono)"}}>LEVERAGE:</span>
            {[["98%+ → 100x","lev-100"],["95%+ → 50x","lev-50"],["90-94% → 20x","lev-20"],["85-89% → 10x","lev-10"]].map(([l,c])=>(
              <span key={l} className={`lev-badge ${c}`}>{l}</span>
            ))}
          </div>

          {/* Signals header */}
          <div className="section-header" style={{marginBottom:12}}>
            <div>
              <div className="section-title">Structure Signals — {signals.length} assets</div>
              <div className="section-sub">BOS → Fib → OB → MA → Entry · HTF bias filter active</div>
            </div>
            <div style={{display:"flex",gap:4}}>
              {["BOS","Fib","OB","MA","Entry"].map(s=>(
                <span key={s} style={{fontSize:9,padding:"2px 8px",borderRadius:3,
                  background:"var(--surface2)",color:"var(--text3)",
                  border:"1px solid var(--border)",fontFamily:"var(--font-mono)"}}>{s}</span>
              ))}
            </div>
          </div>

          {activeS.length>0 && (
            <div style={{marginBottom:10}}>
              <div style={{fontSize:10,color:"var(--info)",fontFamily:"var(--font-mono)",marginBottom:6,letterSpacing:"0.06em"}}>✦ ACTIVE — {activeS.length}</div>
              <div className="signal-grid">
                {activeS.map(data=>(
                  <SignalCard key={data.signal_data?.symbol} data={data}
                    selected={selected?.signal_data?.symbol===data.signal_data?.symbol}
                    onSelect={setSelected} getLev={getLev} getLevClass={getLevClass}/>
                ))}
              </div>
            </div>
          )}

          <div className="signal-grid">
            {holdS.map(data=>(
              <SignalCard key={data.signal_data?.symbol} data={data}
                selected={selected?.signal_data?.symbol===data.signal_data?.symbol}
                onSelect={setSelected} getLev={getLev} getLevClass={getLevClass}/>
            ))}
          </div>

          {signals.length===0&&!loading&&(
            <div className="card"><div className="empty-state"><div className="empty-icon">📡</div>Warming signal cache — 30–60s on first load</div></div>
          )}
        </div>

        <div className="risk-panel"><RiskPanel selected={selected}/></div>
      </div>
    </div>
  );
}

