import{useApp}from"../context/AppContext";
export default function Navbar({tab,setTab,botStatus,ctx}){
  const{theme,setTheme}=useApp();
  const{handleStart,handleStop,handleScan,handleCloseAll,actionLoad,lastUpdate}=ctx;
  const isLive=botStatus?.running&&!botStatus?.paused;
  const isPaused=botStatus?.paused;
  const balance=botStatus?.balance_usdt??0;
  const statusLabel=isLive?"LIVE":isPaused?"PAUSED":"STOPPED";
  const statusClass=isLive?"live":isPaused?"paused":"stopped";
  return(
    <nav className="navbar">
      <div className="navbar-brand">
        <div className="brand-logo"><span className="w">WELT</span><span className="b">BOT</span></div>
        <span className="brand-tag">v5.1</span>
        <div className={`status-pill ${statusClass}`}><div className={`pulse-dot ${isLive?"live":""}`}/>{statusLabel}</div>
        {botStatus?.testnet&&<span style={{fontSize:9,color:"var(--purple)",padding:"2px 8px",borderRadius:4,background:"rgba(167,139,250,0.1)",border:"1px solid rgba(167,139,250,0.25)",fontFamily:"var(--font-mono)",letterSpacing:"0.1em"}}>TESTNET</span>}
      </div>
      <div className="navbar-center">
        {[["overview","📊 Overview"],["signals","📡 Signals"],["trades","📋 Trades"],["forex","💱 Forex"]].map(([t,l])=>(
          <button key={t} className={`nav-tab ${tab===t?"active":""}`} onClick={()=>setTab(t)}>{l}</button>
        ))}
      </div>
      <div className="navbar-right">
        {lastUpdate&&<span style={{fontSize:10,color:"var(--text3)",fontFamily:"var(--font-mono)"}}>{lastUpdate}</span>}
        <div className="balance-chip">
          <span className="bal">${balance.toLocaleString(undefined,{minimumFractionDigits:2,maximumFractionDigits:2})}</span>
          <span className="bal-label">USDT</span>
        </div>
        {!isLive?<button className="btn btn-success btn-sm" onClick={handleStart} disabled={actionLoad}>{actionLoad?"…":"▶ Start"}</button>:<button className="btn btn-danger btn-sm" onClick={handleStop} disabled={actionLoad}>{actionLoad?"…":"■ Stop"}</button>}
        <button className="btn btn-scan btn-sm" onClick={handleScan} disabled={actionLoad}>⟳ Scan</button>
        <button onClick={handleCloseAll} title="Close all exchange positions" style={{padding:"6px 10px",borderRadius:6,fontSize:10,background:"rgba(255,77,109,0.12)",color:"var(--sell)",border:"1px solid rgba(255,77,109,0.3)",cursor:"pointer",fontFamily:"var(--font-mono)",fontWeight:600}}>✕ Close All</button>
        {/* Theme toggle — replaces the old Settings modal */}
        <button className="icon-btn" onClick={()=>setTheme(theme==="dark"?"light":"dark")} title="Toggle theme">{theme==="dark"?"☀":"☾"}</button>
      </div>
    </nav>
  );
}
