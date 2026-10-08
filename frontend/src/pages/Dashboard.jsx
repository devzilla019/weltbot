import{useState,useEffect,useCallback}from"react";
import{useApp}from"../context/AppContext";
import{makeApi}from"../api";
import Sidebar from"../components/Sidebar";
import DisclaimerBanner from"../components/DisclaimerBanner";
import ControlRoom from"../components/ControlRoom";
import OverviewTab from"../components/OverviewTab";
import SignalsTab from"../components/SignalsTab";
import TradesTab from"../components/TradesTab";
import ForexTab from"../components/ForexTab";
import CryptoStrategyTab from"../components/CryptoStrategyTab";
import BuiltBy from"../components/BuiltBy";
export default function Dashboard(){
  const{token,showToast}=useApp();
  const api=makeApi(token);
  const[tab,setTab]=useState("control");
  const[botStatus,setBotStatus]=useState(null);
  const[signals,setSignals]=useState([]);
  const[trades,setTrades]=useState([]);
  const[summary,setSummary]=useState(null);
  const[portfolio,setPortfolio]=useState(null);
  const[loading,setLoading]=useState(false);
  const[actionLoad,setActionLoad]=useState(false);
  const[lastUpdate,setLastUpdate]=useState(null);
  const[backendDown,setBackendDown]=useState(false);
  const[sidebarOpen,setSidebarOpen]=useState(false);
  const load=useCallback(async(silent=false)=>{
    if(!silent)setLoading(true);
    try{
      const[status,sigs,trds,sum,port]=await Promise.all([api.getBotStatus().catch(()=>null),api.getAllSignals().catch(()=>[]),api.getTrades().catch(()=>[]),api.getSummary().catch(()=>null),api.getPortfolio().catch(()=>null)]);
      setBackendDown(false);
      if(status)setBotStatus(status);
      if(sigs)setSignals(Array.isArray(sigs)?sigs:[]);
      if(trds)setTrades(Array.isArray(trds)?trds:[]);
      if(sum)setSummary(sum);
      if(port)setPortfolio(port);
      setLastUpdate(new Date().toLocaleTimeString());
    }catch{setBackendDown(true);if(!silent)showToast("Cannot reach backend","error");}
    finally{setLoading(false);}
  },[token]);
  useEffect(()=>{load();const t=setInterval(()=>load(true),30000);return()=>clearInterval(t);},[load]);
  const handleStart=async()=>{setActionLoad(true);try{const r=await api.startBot();showToast(r.message||"Bot started","success");setTimeout(()=>load(true),2000);}catch{showToast("Failed","error");}finally{setActionLoad(false);}};
  const handleStop=async()=>{setActionLoad(true);try{await api.stopBot();showToast("Stopped");load(true);}catch{showToast("Failed","error");}finally{setActionLoad(false);}};
  const handleScan=async()=>{setActionLoad(true);showToast("Scanning…","info");try{await api.scanNow();setTimeout(()=>load(true),6000);}catch{showToast("Failed","error");}finally{setActionLoad(false);}};
  const handleCloseTrade=async(id)=>{try{const r=await api.closeTrade(id);if(r.success){showToast(`Closed · P&L $${(r.pnl||0).toFixed(4)}`,"success");load(true);}else showToast(r.error||"Failed","error");}catch{showToast("Failed","error");}};
  const handleClearTrades=async()=>{try{const r=await api.clearTrades();if(r.success){showToast(`Cleared ${r.deleted} trades`,"success");load(true);}}catch{showToast("Failed","error");}};
  const handleCloseAll=async()=>{
    try{
      const BASE=import.meta.env.VITE_API_URL||"http://localhost:8000";
      const r=await fetch(BASE+"/api/bot/close-all",{method:"POST"}).then(x=>x.json());
      showToast(`Closed ${r.exchange_closed||0} exchange positions`,"success");
      load(true);
    }catch{showToast("Close all failed","error");}
  };
  const ctx={botStatus,signals,trades,summary,portfolio,loading,actionLoad,lastUpdate,backendDown,handleStart,handleStop,handleScan,handleCloseTrade,handleClearTrades,handleCloseAll,refresh:load};
  const TITLES={control:["Control Room","Live positions · risk · session windows"],overview:["Dashboard","Portfolio overview & live signals"],signals:["Signals","Structure signals across all markets"],trades:["Trades","Full trade history & performance"],forex:["Forex & Metals","CRT + SMC + Kronos AI · Capital.com"],crypto:["Crypto","Kronos + CRT + SMC · Binance futures"]};
  const[title,subtitle]=TITLES[tab]||TITLES.control;
  const isLive=botStatus?.running&&!botStatus?.paused;
  return(
    <div className="app-shell">
      <div className="orb orb-1"/><div className="orb orb-2"/>
      <Sidebar tab={tab} setTab={setTab} botStatus={botStatus} open={sidebarOpen} onClose={()=>setSidebarOpen(false)}/>
      <div className="app-main">
        <DisclaimerBanner/>
        <div className="topbar">
          <div style={{display:"flex",alignItems:"center",gap:12}}>
            <button className="icon-btn sidebar-toggle" onClick={()=>setSidebarOpen(o=>!o)} title="Menu">☰</button>
            <div>
              <div className="topbar-title">{title}</div>
              <div className="topbar-sub">{subtitle}</div>
            </div>
          </div>
          <div className="topbar-right">
            {lastUpdate&&<span style={{fontSize:10,color:"var(--text3)",fontFamily:"var(--font-mono)"}}>{lastUpdate}</span>}
            {!isLive
              ?<button className="btn btn-success btn-sm" onClick={handleStart} disabled={actionLoad}>{actionLoad?"…":"▶ Start"}</button>
              :<button className="btn btn-danger btn-sm" onClick={handleStop} disabled={actionLoad}>{actionLoad?"…":"■ Stop"}</button>}
            <button className="btn btn-scan btn-sm" onClick={handleScan} disabled={actionLoad}>⟳ Scan</button>
            <button className="btn btn-danger btn-sm" onClick={handleCloseAll} title="Close all exchange positions">✕ Close All</button>
          </div>
        </div>
        {backendDown&&<div style={{background:"rgba(255,92,138,0.08)",border:"1px solid rgba(255,92,138,0.2)",padding:"10px 24px",fontSize:11,color:"var(--sell)",fontFamily:"var(--font-mono)",display:"flex",alignItems:"center",gap:8}}>⚠ Backend unreachable — check Railway<button onClick={()=>load()} style={{marginLeft:"auto",fontSize:10,padding:"3px 10px",background:"rgba(255,92,138,0.1)",border:"1px solid rgba(255,92,138,0.3)",color:"var(--sell)",borderRadius:4,cursor:"pointer"}}>Retry</button></div>}
        <div className="page-body animate-in" key={tab}>
          {tab==="control"&&<ControlRoom/>}
          {tab==="overview"&&<OverviewTab {...ctx}/>}
          {tab==="signals"&&<SignalsTab {...ctx}/>}
          {tab==="trades"&&<TradesTab {...ctx}/>}
          {tab==="forex"&&<ForexTab/>}
          {tab==="crypto"&&<CryptoStrategyTab/>}
        </div>
        <BuiltBy/>
      </div>
    </div>
  );
}
