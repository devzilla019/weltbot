import{useState,useEffect}from"react";
import{forexApi}from"../api";

const BASE=import.meta.env.VITE_API_URL||"http://localhost:8000";
const get=async(p)=>{const r=await fetch(BASE+p);if(!r.ok)throw new Error(`HTTP ${r.status}`);return r.json();};

export default function CryptoStrategyTab(){
  const[data,setData]=useState(null);
  const[balance,setBalance]=useState(null);
  const[loading,setLoading]=useState(true);
  const[err,setErr]=useState(null);

  const load=async()=>{
    try{
      const[s,b]=await Promise.all([
        get("/api/crypto/strategy").catch(()=>null),
        get("/api/crypto/balance").catch(()=>null),
      ]);
      if(s)setData(s);
      if(b)setBalance(b);
      setErr(null);
    }catch(e){setErr(e.message);}
    finally{setLoading(false);}
  };
  useEffect(()=>{load();const t=setInterval(load,15000);return()=>clearInterval(t);},[]);

  if(loading)return(
    <div className="grid-pairs">
      {[...Array(6)].map((_,i)=><div key={i} className="skeleton" style={{height:190}}/>)}
    </div>
  );

  const biases=data?.biases||{};
  const levels=data?.crt_levels||{};
  const setups=data?.active_setups||{};
  const universe=data?.universe||[];
  const biasCount=Object.keys(biases).length;

  return(
    <div>
      <div className="hero">
        <div className="hero-title">Crypto <span className="accent">Strategy Engine</span></div>
        <div className="hero-sub">Kronos AI bias → CRT sweep → SMC entry · Binance USDT futures</div>
        <div className="hero-chips">
          <span className="hero-chip">Kronos <b>{data?.kronos_available?"ACTIVE":"OFFLINE"}</b></span>
          <span className="hero-chip">Universe <b>{universe.length}</b></span>
          <span className="hero-chip">Biases <b>{biasCount}</b></span>
          <span className="hero-chip">Setups <b>{Object.keys(setups).length}</b></span>
        </div>
      </div>

      <div className="metric-grid">
        <div className="metric">
          <div className="metric-label"><span style={{color:"var(--warn)"}}>₿</span> Binance Balance</div>
          <div className="metric-value" style={{color:"var(--buy)"}}>
            ${(balance?.balance||0).toLocaleString(undefined,{minimumFractionDigits:2,maximumFractionDigits:2})}
          </div>
          <div className="metric-sub">USDT futures · separate from forex</div>
        </div>
        <div className="metric">
          <div className="metric-label">Kronos Biases</div>
          <div className="metric-value" style={{color:"var(--lav-2)"}}>{biasCount}</div>
          <div className="metric-sub">updated every 15 min</div>
        </div>
        <div className="metric">
          <div className="metric-label">Active Setups</div>
          <div className="metric-value" style={{color:"var(--info)"}}>{Object.keys(setups).length}</div>
          <div className="metric-sub">CRT confirmed + Kronos aligned</div>
        </div>
        <div className="metric">
          <div className="metric-label">Engine</div>
          <div className="metric-value" style={{color:data?.kronos_enabled?"var(--buy)":"var(--text3)",fontSize:18}}>
            {data?.kronos_enabled?"ONLINE":"DISABLED"}
          </div>
          <div className="metric-sub">set KRONOS_ENABLED=true</div>
        </div>
      </div>

      <div className="sec-head">
        <div className="sec-title">Market Signals</div>
        <div className="sec-sub">{universe.length} symbols · Kronos + CRT</div>
      </div>

      {err&&<div className="info-box info-box-red" style={{marginBottom:12}}>⚠ {err}</div>}

      <div className="grid-pairs">
        {universe.map(sym=>{
          const b=biases[sym];
          const lv=levels[sym];
          const st=setups[sym];
          const bias=b?.bias||"NEUTRAL";
          const cls=bias==="BULLISH"?"buy":bias==="BEARISH"?"sell":"";
          const chip=bias==="BULLISH"?"chip-bull":bias==="BEARISH"?"chip-bear":"chip-neutral";
          const pos=(lv&&b?.current_close)?Math.max(0,Math.min(100,((b.current_close-lv.pdl)/(lv.pdh-lv.pdl))*100)):50;
          return(
            <div key={sym} className={`pair-card ${cls}`}>
              <div className="pair-head">
                <div className="pair-symbol">{sym.replace("/USDT","")}<span style={{fontSize:10,color:"var(--text3)"}}>/USDT</span></div>
                <span className={`chip ${chip}`}><span className="chip-dot"/>{bias}</span>
              </div>
              <div className="pair-price-label">Kronos Forecast Close</div>
              <div className="pair-price">{b?.predicted_close_24h?b.predicted_close_24h.toLocaleString(undefined,{maximumFractionDigits:4}):"—"}</div>
              {b?.predicted_change_pct!==undefined&&(
                <div style={{fontFamily:"var(--font-mono)",fontSize:11,marginTop:2,color:b.predicted_change_pct>=0?"var(--buy)":"var(--sell)"}}>
                  {b.predicted_change_pct>=0?"+":""}{b.predicted_change_pct}% · 24h
                </div>
              )}
              {lv&&(
                <>
                  <div className="range-meter"><div className="range-marker" style={{left:`${pos}%`}}/></div>
                  <div className="range-labels">
                    <span style={{color:"var(--sell)"}}>PDH {lv.pdh?.toLocaleString(undefined,{maximumFractionDigits:4})}</span>
                    <span style={{color:"var(--buy)"}}>PDL {lv.pdl?.toLocaleString(undefined,{maximumFractionDigits:4})}</span>
                  </div>
                </>
              )}
              <div className="pipeline">
                <div className={`pipeline-step ${b?"on":""}`}>Kronos</div>
                <span className="pipeline-arrow">›</span>
                <div className={`pipeline-step ${lv?"on":""}`}>CRT</div>
                <span className="pipeline-arrow">›</span>
                <div className={`pipeline-step ${st?"on":""}`}>SMC</div>
              </div>
              {st&&<div className="chip chip-live" style={{marginTop:10}}><span className="chip-dot pulse"/>SETUP · {st.direction} → {st.target?.toLocaleString(undefined,{maximumFractionDigits:4})}</div>}
            </div>
          );
        })}
      </div>
    </div>
  );
}
