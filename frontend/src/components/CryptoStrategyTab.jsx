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
        <div className="hero-sub">Silver Bullet + Volume Profile · Binance</div>
        <div className="hero-chips">
          <span className="hero-chip">Session <b>{data?.active_session||"—"}</b></span>
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
          <div className="metric-sub">USDT · separate from forex</div>
        </div>
        <div className="metric">
          <div className="metric-label">Daily Biases</div>
          <div className="metric-value" style={{color:"var(--lav-2)"}}>{biasCount}</div>
          <div className="metric-sub">H4 structure + volume profile</div>
        </div>
        <div className="metric">
          <div className="metric-label">Active Setups</div>
          <div className="metric-value" style={{color:"var(--info)"}}>{Object.keys(setups).length}</div>
          <div className="metric-sub">sweep + MSS + FVG armed</div>
        </div>
        <div className="metric">
          <div className="metric-label">Strategy</div>
          <div className="metric-value" style={{color:"var(--buy)",fontSize:18}}>SILVER BULLET</div>
          <div className="metric-sub">minimum score {data?.min_confidence??88}</div>
        </div>
      </div>

      <div className="sec-head">
        <div className="sec-title">Market Signals</div>
        <div className="sec-sub">{universe.length} symbols · Silver Bullet</div>
      </div>

      {err&&<div className="info-box info-box-red" style={{marginBottom:12}}>⚠ {err}</div>}

      <div className="grid-pairs">
        {universe.map(sym=>{
          const b=biases[sym];
          const lv=levels[sym];
          const st=setups[sym];
          const bias=b?.h4_bias||"NEUTRAL";
          const cls=bias==="BULLISH"?"buy":bias==="BEARISH"?"sell":"";
          const chip=bias==="BULLISH"?"chip-bull":bias==="BEARISH"?"chip-bear":"chip-neutral";
          const poc=lv?.poc, vah=lv?.vah, val=lv?.val;
          const price=st?.fvg_low??null;
          const pos=(price&&vah&&val)?Math.max(0,Math.min(100,((price-val)/(vah-val))*100)):50;
          return(
            <div key={sym} className={`pair-card ${cls}`}>
              <div className="pair-head">
                <div className="pair-symbol">{sym.replace("/USDT","")}<span style={{fontSize:10,color:"var(--text3)"}}>/USDT</span></div>
                <span className={`chip ${chip}`}><span className="chip-dot"/>{bias}</span>
              </div>
              <div className="pair-price-label">Previous-Day Value Area</div>
              {lv?(
                <>
                  <div className="range-meter"><div className="range-marker" style={{left:`${pos}%`}}/></div>
                  <div className="range-labels">
                    <span style={{color:"var(--sell)"}}>VAL {val?.toLocaleString(undefined,{maximumFractionDigits:6})}</span>
                    <span style={{color:"var(--warn)"}}>POC {poc?.toLocaleString(undefined,{maximumFractionDigits:6})}</span>
                    <span style={{color:"var(--buy)"}}>VAH {vah?.toLocaleString(undefined,{maximumFractionDigits:6})}</span>
                  </div>
                  <div style={{textAlign:"center",fontFamily:"var(--font-mono)",fontSize:9,color:"var(--text3)",marginTop:6}}>
                    {lv.source_trusted?`${lv.volume_source} volume`:`${lv.volume_source||"range"} proxy`}
                  </div>
                </>
              ):(
                <div style={{fontFamily:"var(--font-mono)",fontSize:9,color:"var(--text3)",textAlign:"center",padding:"8px 0"}}>
                  No previous-day profile
                </div>
              )}
              {b?.price_position&&(
                <div style={{textAlign:"center",fontFamily:"var(--font-mono)",fontSize:9,color:"var(--text3)",marginTop:4}}>
                  price {String(b.price_position).replace(/_/g," ").toLowerCase()}
                </div>
              )}
              <div className="pipeline">
                <div className={`pipeline-step ${b?"on":""}`}>H4</div>
                <span className="pipeline-arrow">›</span>
                <div className={`pipeline-step ${lv?"on":""}`}>VP</div>
                <span className="pipeline-arrow">›</span>
                <div className={`pipeline-step ${st?"on":""}`}>FVG</div>
              </div>
              {st&&(
                <div className="chip chip-live" style={{marginTop:10}}>
                  <span className="chip-dot pulse"/>
                  {st.state||"ARMED"} · {st.direction} · score {st.confidence??"—"}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
