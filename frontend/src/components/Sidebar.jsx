import{useState}from"react";
import{useApp}from"../context/AppContext";

const NAV=[
  {section:"Trading"},
  {id:"overview",label:"Dashboard",icon:"◈"},
  {id:"signals", label:"Signals",  icon:"◉"},
  {id:"trades",  label:"Trades",   icon:"▤"},
  {section:"Markets"},
  {id:"forex",   label:"Forex & Metals",icon:"◆"},
  {id:"crypto",  label:"Crypto",   icon:"₿"},
];

export default function Sidebar({tab,setTab,botStatus,open,onClose}){
  const{theme,setTheme}=useApp();
  const[imgOk,setImgOk]=useState(true);
  const isLive=botStatus?.running&&!botStatus?.paused;
  const cryptoBal=botStatus?.balance_usdt??0;
  const forexBal=botStatus?.forex_balance??0;

  const go=(id)=>{setTab(id);onClose&&onClose();};

  return(
    <aside className={`sidebar ${open?"open":""}`}>
      <div className="sidebar-brand">
        {imgOk
          ? <img src="/logo.png" alt="WeltBot" className="sidebar-logo" onError={()=>setImgOk(false)}/>
          : <div className="sidebar-logo" style={{display:"flex",alignItems:"center",justifyContent:"center",background:"linear-gradient(135deg,#7c5cf5,#c4b5fd)",fontSize:18}}>⚡</div>
        }
        <div>
          <div className="sidebar-brand-text"><span className="w">WELT</span><span className="b">BOT</span></div>
          <div className="sidebar-brand-sub">v5.2 · Autonomous</div>
        </div>
      </div>

      {NAV.map((n,i)=>n.section
        ? <div key={i} className="sidebar-section">{n.section}</div>
        : (
          <button key={n.id} className={`sidebar-item ${tab===n.id?"active":""}`} onClick={()=>go(n.id)}>
            <span className="sidebar-item-icon">{n.icon}</span>
            {n.label}
            {n.id==="forex"&&botStatus?.forex_active_setups?.length>0&&
              <span className="sidebar-item-badge">{botStatus.forex_active_setups.length}</span>}
            {n.id==="signals"&&botStatus?.active_setups?.length>0&&
              <span className="sidebar-item-badge">{botStatus.active_setups.length}</span>}
          </button>
        )
      )}

      <div className="sidebar-spacer"/>

      <div className="sidebar-foot">
        <div className="sidebar-balance">
          <div className="sidebar-balance-label"><span style={{color:"var(--warn)"}}>₿</span> Crypto · Binance</div>
          <div className="sidebar-balance-value" style={{color:"var(--buy)"}}>
            ${cryptoBal.toLocaleString(undefined,{minimumFractionDigits:2,maximumFractionDigits:2})}
          </div>
          <div className="sidebar-balance-sub">USDT futures</div>
        </div>
        <div className="sidebar-balance">
          <div className="sidebar-balance-label"><span style={{color:"var(--lav)"}}>◆</span> Forex · Capital</div>
          <div className="sidebar-balance-value" style={{color:"var(--lav-2)"}}>
            ${forexBal.toLocaleString(undefined,{minimumFractionDigits:2,maximumFractionDigits:2})}
          </div>
          <div className="sidebar-balance-sub">Capital.com demo</div>
        </div>

        <div style={{display:"flex",gap:8,alignItems:"center"}}>
          <div className={`status-pill ${isLive?"live":botStatus?.paused?"paused":"stopped"}`} style={{flex:1,justifyContent:"center"}}>
            <div className={`pulse-dot ${isLive?"live":""}`}/>{isLive?"LIVE":botStatus?.paused?"PAUSED":"STOPPED"}
          </div>
          <button className="icon-btn" onClick={()=>setTheme(theme==="dark"?"light":"dark")} title="Toggle theme">
            {theme==="dark"?"☀":"☾"}
          </button>
        </div>
      </div>
    </aside>
  );
}
