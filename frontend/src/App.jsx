import{useState,useEffect}from"react";
// AUTH DISABLED — re-enable later by uncommenting the import + the AuthPage branch below
// import AuthPage from"./pages/AuthPage";
import Dashboard from"./pages/Dashboard";
import LoadingScreen from"./components/LoadingScreen";
import{AppCtx}from"./context/AppContext";

export default function App(){
  // AUTH DISABLED — single-user open dashboard. Kept as no-op state so the
  // rest of the app (Navbar, context consumers) keeps working unchanged.
  const[user,setUser]=useState({name:"Trader"});
  const[token,setToken]=useState(null);
  const[theme,setTheme]=useState(()=>localStorage.getItem("wb_theme")||"dark");
  const[toast,setToast]=useState(null);
  const[booting,setBooting]=useState(true);

  useEffect(()=>{
    document.documentElement.setAttribute("data-theme",theme);
    localStorage.setItem("wb_theme",theme);
  },[theme]);

  // AUTH DISABLED — session helpers kept as no-ops for later re-enable
  const setSession=(tok,usr)=>{setToken(tok);setUser(usr);};
  const clearSession=()=>{setToken(null);setUser({name:"Trader"});};
  const showToast=(msg,type="info",duration=4000)=>{
    setToast({msg,type,id:Date.now()});
    setTimeout(()=>setToast(null),duration);
  };
  const logout=()=>{showToast("Auth is disabled");};

  return(
    <AppCtx.Provider value={{user,setUser,token,setSession,clearSession,theme,setTheme,showToast,logout}}>
      <div className="app-root">
        {booting&&<LoadingScreen onDone={()=>setBooting(false)}/>}
        {/* AUTH DISABLED — always show dashboard. Re-enable with:
            {!user||!token?<AuthPage/>:<Dashboard/>} */}
        <Dashboard/>
        {toast&&(
          <div className={`toast toast-${toast.type}`} key={toast.id}>
            <span className="toast-icon">{toast.type==="success"?"✓":toast.type==="error"?"✕":toast.type==="warn"?"⚠":"ℹ"}</span>
            {toast.msg}
          </div>
        )}
      </div>
    </AppCtx.Provider>
  );
}
