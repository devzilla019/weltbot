import{useState,useEffect}from"react";
import{useApp}from"../context/AppContext";
import{authApi,makeApi}from"../api";
export default function SettingsModal({onClose,onRefresh}){
  const{user,setUser,token,theme,setTheme,showToast,logout}=useApp();
  const api=makeApi(token);
  const[section,setSection]=useState("apikeys");
  const[apiKey,setApiKey]=useState("");
  const[apiSecret,setApiSecret]=useState("");
  const[showKey,setShowKey]=useState(false);
  const[showSec,setShowSec]=useState(false);
  const[saving,setSaving]=useState(false);
  const[keyStatus,setKeyStatus]=useState(null);
  const[testnet,setTestnet]=useState(user?.testnet??true);
  const[togglingNet,setTogglingNet]=useState(false);
  const[riskPct,setRiskPct]=useState("3.0");
  const[maxTrades,setMaxTrades]=useState("2");
  const[minConf,setMinConf]=useState("88");
  const[dailyLimit,setDailyLimit]=useState("5");
  const[savingBot,setSavingBot]=useState(false);
  const[editName,setEditName]=useState(user?.name||"");

  useEffect(()=>{
    authApi.getKeyStat(token).then(s=>{setKeyStatus(s);setTestnet(s.testnet??true);}).catch(()=>{});
    api.getBotSettings().then(s=>{if(s){setRiskPct(String(s.risk_pct||3));setMaxTrades(String(s.max_trades||2));setMinConf(String(s.min_conf||88));setDailyLimit(String(s.daily_limit||5));}}).catch(()=>{});
  },[token]);

  const saveApiKeys=async()=>{
    if(!apiKey.trim()||!apiSecret.trim()){showToast("Both keys required","error");return;}
    setSaving(true);
    try{
      const r=await authApi.saveKeys(token,apiKey.trim(),apiSecret.trim());
      if(r.success){showToast(r.message,"success");setApiKey("");setApiSecret("");const s=await authApi.getKeyStat(token);setKeyStatus(s);onRefresh();}
      else showToast(r.error||"Failed","error");
    }catch(e){showToast(e.message||"Error","error");}
    finally{setSaving(false);}
  };

  const toggleNetwork=async(isTestnet)=>{
    setTogglingNet(true);
    try{const r=await authApi.toggleNet(token,isTestnet);if(r.success){setTestnet(isTestnet);const me={...user,testnet:isTestnet};setUser(me);localStorage.setItem("wb_user",JSON.stringify(me));showToast(r.message,"success");onRefresh();}}
    catch(e){showToast(e.message||"Error","error");}
    finally{setTogglingNet(false);}
  };

  const saveBotSettings=async()=>{
    setSavingBot(true);
    try{const r=await api.updateBotSettings({risk_pct:parseFloat(riskPct),max_trades:parseInt(maxTrades),min_conf:parseFloat(minConf),daily_limit:parseFloat(dailyLimit)});if(r.success)showToast("Settings applied!","success");else showToast(r.error||"Failed","error");}
    catch(e){showToast(e.message,"error");}
    finally{setSavingBot(false);}
  };

  const saveName=async()=>{
    if(!editName.trim())return;
    try{await authApi.updateName(token,editName.trim());const me={...user,name:editName.trim()};setUser(me);localStorage.setItem("wb_user",JSON.stringify(me));showToast("Name updated","success");}
    catch(e){showToast(e.message,"error");}
  };

  const sections=[{key:"apikeys",icon:"🔑",label:"API Keys"},{key:"network",icon:"🌐",label:"Network"},{key:"bot",icon:"🤖",label:"Bot Settings"},{key:"appearance",icon:"🎨",label:"Appearance"},{key:"account",icon:"👤",label:"Account"},{key:"risk",icon:"🛡",label:"Risk Guide"},{key:"about",icon:"ℹ",label:"About"}];

  return(
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal modal-lg" onClick={e=>e.stopPropagation()} style={{padding:0,display:"flex",flexDirection:"column",width:580,maxHeight:"90vh"}}>
        <div style={{padding:"20px 24px 16px",borderBottom:"1px solid var(--border)",display:"flex",justifyContent:"space-between",alignItems:"center"}}>
          <div><div className="modal-title">Settings</div><div className="modal-subtitle">Logged in as {user?.email}</div></div>
          <button className="icon-btn" onClick={onClose}>✕</button>
        </div>
        <div style={{display:"flex",flex:1,overflow:"hidden"}}>
          <div style={{width:160,borderRight:"1px solid var(--border)",padding:"10px 8px",display:"flex",flexDirection:"column",gap:2,flexShrink:0}}>
            {sections.map(s=><button key={s.key} onClick={()=>setSection(s.key)} style={{display:"flex",alignItems:"center",gap:8,padding:"8px 10px",borderRadius:6,border:"none",cursor:"pointer",textAlign:"left",fontSize:12,fontWeight:500,fontFamily:"var(--font-body)",background:section===s.key?"var(--surface2)":"transparent",color:section===s.key?"var(--text)":"var(--text2)"}}><span style={{fontSize:14}}>{s.icon}</span>{s.label}</button>)}
            <div style={{flex:1}}/>
            <button onClick={logout} style={{display:"flex",alignItems:"center",gap:8,padding:"8px 10px",borderRadius:6,border:"none",cursor:"pointer",textAlign:"left",fontSize:12,fontFamily:"var(--font-body)",background:"transparent",color:"var(--sell)",marginTop:8}}><span>⎋</span>Sign Out</button>
          </div>
          <div style={{flex:1,padding:"20px 24px",overflowY:"auto"}}>
            {section==="apikeys"&&(
              <div>
                <div className="settings-title">Binance API Keys</div>
                {keyStatus&&<div className={`info-box ${keyStatus.has_keys?"info-box-green":"info-box-red"}`} style={{marginBottom:14}}>{keyStatus.has_keys?`✓ Connected — Key: ${keyStatus.key_preview}`:"✗ No keys — bot cannot trade without them"}</div>}
                <div className="info-box info-box-blue" style={{marginBottom:14,fontSize:11}}><strong>Demo Trading:</strong> Get keys from <span style={{color:"var(--info)"}}>demo-fapi.binance.com</span> → Account → API Management → Create HMAC key.<br/><br/><strong>Live Trading:</strong> Binance.com → API Management → Enable Futures only.</div>
                <div className="form-group"><label className="form-label">API Key</label><div className="form-input-wrap"><input className="form-input" type={showKey?"text":"password"} value={apiKey} onChange={e=>setApiKey(e.target.value)} placeholder="Paste Binance API key"/><button className="form-input-eye" onClick={()=>setShowKey(!showKey)}>{showKey?"○":"●"}</button></div></div>
                <div className="form-group"><label className="form-label">Secret Key</label><div className="form-input-wrap"><input className="form-input" type={showSec?"text":"password"} value={apiSecret} onChange={e=>setApiSecret(e.target.value)} placeholder="Paste Binance secret key"/><button className="form-input-eye" onClick={()=>setShowSec(!showSec)}>{showSec?"○":"●"}</button></div></div>
                <button className="btn btn-primary" style={{width:"100%",justifyContent:"center"}} onClick={saveApiKeys} disabled={saving}>{saving?"Saving & Testing…":"Save & Connect API Keys"}</button>
                <div className="info-box info-box-warn" style={{marginTop:12}}>🔒 Keys are encrypted before storage. They are never exposed in plain text.</div>
              </div>
            )}
            {section==="network"&&(
              <div>
                <div className="settings-title">Trading Network</div>
                <div className="info-box info-box-blue" style={{marginBottom:16}}>Switch between demo (testnet) and real money (mainnet). Your API keys must match the selected mode.</div>
                <div style={{display:"grid",gridTemplateColumns:"1fr 1fr",gap:12,marginBottom:16}}>
                  {[{label:"🧪 Testnet (Demo)",desc:"Virtual funds · Zero real risk · Safe for testing",val:true},{label:"🔴 Mainnet (Live)",desc:"Real money · Real profits and losses",val:false}].map(({label,desc,val})=>(
                    <div key={String(val)} onClick={()=>!togglingNet&&toggleNetwork(val)} style={{padding:16,borderRadius:10,cursor:togglingNet?"not-allowed":"pointer",border:`2px solid ${testnet===val?"var(--info)":"var(--border)"}`,background:testnet===val?"rgba(77,159,255,0.06)":"var(--surface2)",transition:"all 0.15s"}}>
                      <div style={{fontSize:14,fontWeight:700,marginBottom:6}}>{label}</div>
                      <div style={{fontSize:11,color:"var(--text2)",lineHeight:1.5}}>{desc}</div>
                      {testnet===val&&<div style={{marginTop:8,fontSize:10,color:"var(--info)",fontFamily:"var(--font-mono)"}}>● ACTIVE</div>}
                    </div>
                  ))}
                </div>
                {!testnet&&<div className="info-box info-box-red">⚠ MAINNET ACTIVE — Real USDT at risk. Ensure API keys are from Binance.com not demo-fapi.</div>}
                {testnet&&<div className="info-box info-box-green">✓ Testnet active — All trades use virtual funds. Safe to experiment.</div>}
              </div>
            )}
            {section==="bot"&&(
              <div>
                <div className="settings-title">Trading Parameters</div>
                <div className="form-row" style={{marginBottom:12}}>
                  <div className="form-group" style={{marginBottom:0}}><label className="form-label">Risk per Trade (%)</label><input className="form-input" type="number" min="0.1" max="10" step="0.1" value={riskPct} onChange={e=>setRiskPct(e.target.value)}/><div style={{fontSize:10,color:"var(--text3)",marginTop:4}}>Kelly optimal: 3% · Never exceed 10%</div></div>
                  <div className="form-group" style={{marginBottom:0}}><label className="form-label">Max Positions</label><input className="form-input" type="number" min="1" max="10" value={maxTrades} onChange={e=>setMaxTrades(e.target.value)}/><div style={{fontSize:10,color:"var(--text3)",marginTop:4}}>Recommended: 2</div></div>
                </div>
                <div className="form-row" style={{marginBottom:16}}>
                  <div className="form-group" style={{marginBottom:0}}><label className="form-label">Min Confidence (%)</label><input className="form-input" type="number" min="70" max="99" value={minConf} onChange={e=>setMinConf(e.target.value)}/><div style={{fontSize:10,color:"var(--text3)",marginTop:4}}>Higher = fewer, better trades</div></div>
                  <div className="form-group" style={{marginBottom:0}}><label className="form-label">Daily Loss Limit (%)</label><input className="form-input" type="number" min="1" max="20" value={dailyLimit} onChange={e=>setDailyLimit(e.target.value)}/><div style={{fontSize:10,color:"var(--text3)",marginTop:4}}>Bot pauses when hit</div></div>
                </div>
                <div className="settings-title">Leverage Tiers (automatic)</div>
                <div style={{display:"grid",gridTemplateColumns:"1fr 1fr",gap:8,marginBottom:16}}>
                  {[["lev-100","100x","≥98% conf","BTC/ETH only"],["lev-50","50x","≥95% conf","Major pairs"],["lev-20","20x","90-94%","All assets"],["lev-10","10x","85-89%","All assets"]].map(([cls,lev,conf,note])=>(
                    <div key={lev} className="card-sm" style={{display:"flex",justifyContent:"space-between",alignItems:"center"}}>
                      <div><span className={`lev-badge ${cls}`}>{lev}</span><div style={{fontSize:10,color:"var(--text3)",marginTop:3}}>{note}</div></div>
                      <div style={{fontSize:12,fontFamily:"var(--font-mono)",color:"var(--text2)"}}>{conf}</div>
                    </div>
                  ))}
                </div>
                <button className="btn btn-primary" onClick={saveBotSettings} disabled={savingBot} style={{width:"100%",justifyContent:"center"}}>{savingBot?"Applying…":"Apply Settings to Bot"}</button>
              </div>
            )}
            {section==="appearance"&&(
              <div>
                <div className="settings-title">Theme</div>
                <div className="settings-row">
                  <div><div className="settings-row-label">Color Mode</div><div className="settings-row-desc">Dark recommended for trading</div></div>
                  <div className="theme-selector">{[["dark","🌙 Dark"],["light","☀ Light"]].map(([t,l])=><button key={t} className={`theme-btn ${theme===t?"active":""}`} onClick={()=>setTheme(t)}>{l}</button>)}</div>
                </div>
                <div className="settings-row">
                  <div><div className="settings-row-label">Accent Color</div><div className="settings-row-desc">Primary interface color</div></div>
                  <div className="color-picker">{[["#4d9fff","Blue"],["#00e5a0","Green"],["#a78bfa","Purple"],["#f59e0b","Amber"],["#f43f5e","Rose"]].map(([c,n])=><div key={c} className="color-swatch" style={{background:c}} title={n} onClick={()=>{document.documentElement.style.setProperty("--info",c);showToast(`Accent: ${n}`);}}/>)}</div>
                </div>
              </div>
            )}
            {section==="account"&&(
              <div>
                <div className="settings-title">Profile</div>
                <div style={{display:"flex",alignItems:"center",gap:14,padding:"14px 0",borderBottom:"1px solid var(--border)",marginBottom:16}}>
                  <div style={{width:52,height:52,borderRadius:"50%",background:"linear-gradient(135deg,var(--info),var(--purple))",display:"flex",alignItems:"center",justifyContent:"center",fontSize:22,fontWeight:700,color:"#fff"}}>{user?.name?.charAt(0)?.toUpperCase()||"U"}</div>
                  <div><div style={{fontSize:16,fontWeight:600}}>{user?.name}</div><div style={{fontSize:12,color:"var(--text3)"}}>{user?.email}</div><div style={{fontSize:10,color:"var(--text3)",marginTop:2,fontFamily:"var(--font-mono)"}}>TRADER · Joined {user?.created_at?new Date(user.created_at).toLocaleDateString():"—"}</div></div>
                </div>
                <div className="form-group"><label className="form-label">Display Name</label><div style={{display:"flex",gap:8}}><input className="form-input" value={editName} onChange={e=>setEditName(e.target.value)}/><button className="btn btn-ghost" onClick={saveName}>Save</button></div></div>
                <div className="form-group"><label className="form-label">Email</label><input className="form-input" value={user?.email||""} disabled style={{opacity:0.6}}/></div>
                <div className="info-box info-box-blue" style={{marginTop:12}}>Your account is stored in the server database. Login from any device with your email and password.</div>
              </div>
            )}
            {section==="risk"&&(
              <div>
                <div className="settings-title">Risk Management</div>
                <div className="info-box info-box-warn" style={{marginBottom:14}}>⚠ Read all safeguards before trading with real money.</div>
                {[["🛡","1% Base Risk Per Trade","Each trade risks a Kelly-optimal % of balance. Scales UP after wins, DOWN during losses."],["📉","5% Daily Stop","Bot auto-pauses if you lose 5% in a single day."],["⏱","SL Cooldown","After a stop-loss, that asset is blocked for 6 hours."],["📊","Max 2 Positions","Never over-exposed. Max 2 open trades at once."],["🎯","Liquidation Guard","Leverage auto-reduces if liquidation price is too close."],["🔒","100x Whitelist","Extreme leverage restricted to BTC and ETH only."],["📡","HTF Bias Filter","Blocks trades against the 4H + 1H structure direction."],["📰","News Blackout","Trading pauses 15 min before high-impact events."],["📈","Kelly Compounding","Position sizes grow automatically as balance increases."]].map(([icon,title,desc])=>(
                  <div key={title} style={{display:"flex",gap:12,padding:"11px 0",borderBottom:"1px solid var(--border)"}}>
                    <span style={{fontSize:18,flexShrink:0}}>{icon}</span>
                    <div><div style={{fontSize:13,fontWeight:600,marginBottom:3}}>{title}</div><div style={{fontSize:11,color:"var(--text2)",lineHeight:1.6}}>{desc}</div></div>
                  </div>
                ))}
              </div>
            )}
            {section==="about"&&(
              <div>
                <div style={{textAlign:"center",padding:"14px 0 20px"}}>
                  <div style={{fontFamily:"var(--font-display)",fontSize:34,fontWeight:800,marginBottom:4}}><span style={{color:"var(--info)"}}>WELT</span>BOT</div>
                  <div style={{fontSize:11,color:"var(--text3)",fontFamily:"var(--font-mono)"}}>v5.1 · Autonomous Crypto Trading · Built by Zilla</div>
                </div>
                {[["Strategy","SMC v5.1 — BOS + Fib + OB + MA + HTF Bias"],["Position Sizing","Kelly Criterion with full compounding"],["Leverage","Auto 10x/20x/50x/100x by confidence"],["Auth","JWT tokens · Passwords hashed · Keys encrypted"],["Backend","Python FastAPI + SQLite + APScheduler"],["Hosting","Railway (backend) · Vercel (frontend)"],["Built by","Zilla · Syntrion Lab"]].map(([k,v])=>(
                  <div key={k} style={{display:"flex",justifyContent:"space-between",padding:"9px 0",borderBottom:"1px solid var(--border)",fontSize:12}}>
                    <span style={{color:"var(--text3)"}}>{k}</span>
                    <span style={{color:"var(--text)",textAlign:"right",maxWidth:260}}>{v}</span>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
