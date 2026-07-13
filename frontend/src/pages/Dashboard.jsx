import{useState,useEffect,useCallback}from"react";
import{useApp}from"../context/AppContext";
import{makeApi}from"../api";
import Navbar from"../components/Navbar";
import DisclaimerBanner from"../components/DisclaimerBanner";
import OverviewTab from"../components/OverviewTab";
import SignalsTab from"../components/SignalsTab";
import TradesTab from"../components/TradesTab";
import SettingsModal from"../components/SettingsModal";
import BuiltBy from"../components/BuiltBy";
export default function Dashboard(){
  const{token,showToast}=useApp();
  const api=makeApi(token);
  const[tab,setTab]=useState("overview");
  const[botStatus,setBotStatus]=useState(null);
  const[signals,setSignals]=useState([]);
  const[trades,setTrades]=useState([]);
  const[summary,setSummary]=useState(null);
  const[portfolio,setPortfolio]=useState(null);
  const[loading,setLoading]=useState(false);
  const[actionLoad,setActionLoad]=useState(false);
  const[lastUpdate,setLastUpdate]=useState(null);
  const[showSettings,setShowSettings]=useState(false);
  const[backendDown,setBackendDown]=useState(false);
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
  const ctx={botStatus,signals,trades,summary,portfolio,loading,actionLoad,lastUpdate,backendDown,handleStart,handleStop,handleScan,handleCloseTrade,handleClearTrades,refresh:load};
  return(
    <div className="app-root">
      <DisclaimerBanner/>
      <Navbar tab={tab} setTab={setTab} botStatus={botStatus} onSettings={()=>setShowSettings(true)} ctx={ctx}/>
      {backendDown&&<div style={{background:"rgba(255,77,109,0.08)",border:"1px solid rgba(255,77,109,0.2)",padding:"10px 24px",fontSize:11,color:"var(--sell)",fontFamily:"var(--font-mono)",display:"flex",alignItems:"center",gap:8}}>⚠ Backend unreachable — check Railway<button onClick={()=>load()} style={{marginLeft:"auto",fontSize:10,padding:"3px 10px",background:"rgba(255,77,109,0.1)",border:"1px solid rgba(255,77,109,0.3)",color:"var(--sell)",borderRadius:4,cursor:"pointer"}}>Retry</button></div>}
      <div className="page-body animate-in">
        {tab==="overview"&&<OverviewTab {...ctx}/>}
        {tab==="signals"&&<SignalsTab {...ctx}/>}
        {tab==="trades"&&<TradesTab {...ctx}/>}
      </div>
      <BuiltBy/>
      {showSettings&&<SettingsModal onClose={()=>setShowSettings(false)} onRefresh={()=>load(true)}/>}
    </div>
  );
}
