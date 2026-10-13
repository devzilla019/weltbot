import{useState,useEffect}from"react";
import{settingsApi}from"../api";
import{useApp}from"../context/AppContext";

const pct=v=>Math.round((v??0)*1000)/10;
const fromPct=v=>Math.round(Number(v)*10)/1000;

/**
 * Risk settings panel.
 *
 * Every limit can be switched off. A hard daily stop that cannot be relaxed
 * makes a strategy impossible to evaluate — once it trips nothing fires until
 * the next day, so there is no feedback to act on.
 */
export default function SettingsPanel({onClose,onSaved}){
  const{showToast}=useApp();
  const[s,setS]=useState(null);
  const[limits,setLimits]=useState({});
  const[dirty,setDirty]=useState(false);
  const[saving,setSaving]=useState(false);

  const load=async()=>{
    try{
      const r=await settingsApi.getRisk();
      setS(r.settings);setLimits(r.limits||{});setDirty(false);
    }catch(e){showToast(e.message||"Could not load settings","error");}
  };
  useEffect(()=>{load();},[]);

  const set=(k,v)=>{setS(p=>({...p,[k]:v}));setDirty(true);};

  const save=async()=>{
    setSaving(true);
    try{
      const r=await settingsApi.saveRisk(s);
      setS(r.settings);setDirty(false);
      showToast("Settings applied","success");
      onSaved&&onSaved();
    }catch(e){showToast(e.message||"Save failed","error");}
    finally{setSaving(false);}
  };

  const reset=async()=>{
    setSaving(true);
    try{
      const r=await settingsApi.resetRisk();
      setS(r.settings);setDirty(false);
      showToast("Reset to defaults","success");
      onSaved&&onSaved();
    }catch(e){showToast(e.message||"Reset failed","error");}
    finally{setSaving(false);}
  };

  if(!s)return<div className="settings-overlay"><div className="settings-panel">
    <div className="settings-head"><span>Risk Settings</span></div>
    <div className="cr-empty small"><em>Loading…</em></div>
  </div></div>;

  const Num=({k,label,hint,step=0.001,isPct})=>(
    <div className="set-row">
      <div className="set-label">
        <span>{label}</span>
        {hint&&<em>{hint}</em>}
      </div>
      <div className="set-input">
        <input type="number" step={step}
               value={isPct?pct(s[k]):s[k]}
               onChange={e=>set(k,isPct?fromPct(e.target.value):Number(e.target.value))}/>
        <span className="set-unit">{isPct?"%":"#"}</span>
      </div>
    </div>
  );

  const Toggle=({k,label,hint,danger})=>(
    <div className="set-row">
      <div className="set-label">
        <span>{label}</span>
        {hint&&<em>{hint}</em>}
      </div>
      <button className={`set-toggle ${s[k]?"on":""} ${danger?"danger":""}`}
              onClick={()=>set(k,!s[k])}>
        <span className="set-knob"/>
        {s[k]?"ON":"OFF"}
      </button>
    </div>
  );

  return(
    <div className="settings-overlay" onClick={e=>{if(e.target===e.currentTarget)onClose();}}>
      <div className="settings-panel">
        <div className="settings-head">
          <span>Risk Settings</span>
          <button className="btn btn-ghost btn-sm" onClick={onClose}>✕</button>
        </div>

        <div className="settings-body">
          <div className="settings-note">
            Switching a daily limit off lets the strategy keep trading after a
            losing run. Useful for evaluating whether it actually works — a
            tripped limit otherwise hides the rest of the day.
          </div>

          <div className="settings-group">
            <div className="settings-group-title">Forex · Capital.com</div>
            <Toggle k="forex_enabled" label="Forex trading"
                    hint="master switch for the forex engine"/>
            <Toggle k="forex_daily_limit_enabled" label="Daily loss limit"
                    hint="stop forex entries once the day's loss is reached" danger/>
            <Num k="forex_daily_loss_limit" label="Daily loss limit"
                 hint="share of balance" step={0.005} isPct/>
            <Num k="forex_risk_pct" label="Risk per trade" hint="share of balance" step={0.001} isPct/>
            <Num k="forex_min_confidence" label="Minimum confidence"
                 hint="setups below this are skipped" step={1}/>
            <Num k="forex_max_trades" label="Max open trades" step={1}/>
          </div>

          <div className="settings-group">
            <div className="settings-group-title">Crypto · Binance</div>
            <Toggle k="crypto_enabled" label="Crypto trading"
                    hint="master switch for the crypto engine"/>
            <Toggle k="crypto_daily_limit_enabled" label="Daily loss limit"
                    hint="stop crypto entries once the day's loss is reached" danger/>
            <Num k="crypto_daily_loss_limit" label="Daily loss limit"
                 hint="share of balance" step={0.005} isPct/>
            <Num k="crypto_risk_pct" label="Risk per trade" hint="share of balance" step={0.001} isPct/>
            <Num k="crypto_min_confidence" label="Minimum confidence" step={1}/>
            <Num k="crypto_max_trades" label="Max open trades" step={1}/>
          </div>

          <div className="settings-group">
            <div className="settings-group-title">Behaviour</div>
            <Toggle k="weekend_guard" label="Weekend guard"
                    hint="skip forex when the market is closed (Fri 21:00 – Sun 21:00 UTC)"/>
            <Toggle k="auto_resume" label="Auto-resume on start"
                    hint="clear any pause when the bot boots"/>
          </div>

          <div className="settings-note">
            Both engines are independent: a crypto drawdown no longer halts
            forex, and vice versa.
          </div>
        </div>

        <div className="settings-foot">
          <button className="btn btn-ghost btn-sm" onClick={reset} disabled={saving}>Reset defaults</button>
          <span className="settings-dirty">{dirty?"unsaved changes":"up to date"}</span>
          <button className="btn btn-success btn-sm" onClick={save} disabled={saving||!dirty}>
            {saving?"Saving…":"Save"}
          </button>
        </div>
      </div>
    </div>
  );
}
