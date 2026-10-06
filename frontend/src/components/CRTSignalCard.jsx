import{useState,useEffect}from"react";
import{forexApi}from"../api";

// Human-readable labels for the POI kinds the backend returns
const POI_LABELS={
  order_block:"Order Block",
  breaker_block:"Breaker Block",
  fvg:"FVG",
  support_resistance:"S&R",
};
const poiLabel=k=>POI_LABELS[k]||(k?String(k).replace(/_/g," "):"—");

export default function CRTSignalCard({symbol,bias,levels}){
  const[price,setPrice]=useState(null);
  const[details,setDetails]=useState(null);

  useEffect(()=>{
    let alive=true;
    const fetchDetails=async()=>{
      try{const d=await forexApi.getPair(symbol);if(alive){setPrice(d.current_price);setDetails(d);}}
      catch(e){/* silent */}
    };
    fetchDetails();
    const t=setInterval(fetchDetails,45000);
    return()=>{alive=false;clearInterval(t);};
  },[symbol]);

  const biasVal=bias?.bias||"NEUTRAL";
  const cls=biasVal==="BULLISH"?"buy":biasVal==="BEARISH"?"sell":"";
  const chip=biasVal==="BULLISH"?"chip-bull":biasVal==="BEARISH"?"chip-bear":"chip-neutral";
  const inTrade=!!details?.open_trade;
  const setup=details?.active_setup;
  const crtChip=inTrade?"chip-live":setup?"chip-bull":"chip-wait";
  const crtText=inTrade?"IN TRADE":setup?"SETUP ACTIVE":"WAITING";

  const fmt=v=>v==null?"—":Number(v).toFixed(5);
  const hi=levels?.range_high??levels?.pdh;
  const lo=levels?.range_low??levels?.pdl;
  const tf=levels?.timeframe||"1d";
  const pos=(price&&hi&&lo)?Math.max(0,Math.min(100,((price-lo)/(hi-lo))*100)):50;
  const range=(hi&&lo)?(hi-lo).toFixed(5):"—";
  const ranges=details?.crt_ranges||{};

  return(
    <div className={`pair-card ${cls}`}>
      <div className="pair-head">
        <div className="pair-symbol">{symbol}</div>
        <span className={`chip ${chip}`}><span className="chip-dot"/>{biasVal}</span>
      </div>

      <div className="pair-price-label">Current Price</div>
      <div className="pair-price">{price?fmt(price):"—"}</div>

      {levels&&(
        <>
          <div className="range-meter"><div className="range-marker" style={{left:`${pos}%`}}/></div>
          <div className="range-labels">
            <span style={{color:"var(--sell)"}}>H {fmt(hi)}</span>
            <span style={{color:"var(--buy)"}}>L {fmt(lo)}</span>
          </div>
          <div style={{textAlign:"center",fontFamily:"var(--font-mono)",fontSize:9,color:"var(--text3)",marginTop:6}}>
            {tf.toUpperCase()} range {range}
          </div>
          {Object.keys(ranges).length>1&&(
            <div style={{display:"flex",gap:4,justifyContent:"center",marginTop:6,flexWrap:"wrap"}}>
              {Object.entries(ranges).map(([t,r])=>(
                <span key={t} className="chip chip-neutral" style={{fontSize:8,padding:"1px 6px"}}>
                  {t.toUpperCase()} {r.high!=null?Number(r.high).toFixed(3):"—"}
                </span>
              ))}
            </div>
          )}
        </>
      )}

      <div className="pipeline">
        <div className={`pipeline-step ${bias?"on":""}`}>Kronos</div>
        <span className="pipeline-arrow">›</span>
        <div className={`pipeline-step ${levels?"on":""}`}>CRT</div>
        <span className="pipeline-arrow">›</span>
        <div className={`pipeline-step ${inTrade?"on":""}`}>SMC</div>
      </div>

      {setup&&(
        <div style={{marginTop:10,padding:"8px 10px",borderRadius:8,background:"rgba(167,139,250,0.08)",border:"1px solid var(--border2)"}}>
          <div style={{fontFamily:"var(--font-mono)",fontSize:9,color:"var(--lav-2)",letterSpacing:"0.06em",marginBottom:4}}>
            CASCADE · {setup.direction}
          </div>
          <div style={{display:"flex",alignItems:"center",gap:4,fontFamily:"var(--font-mono)",fontSize:9,flexWrap:"wrap"}}>
            <span className="chip chip-live" style={{fontSize:8,padding:"1px 6px"}}>CRT {setup.timeframe?.toUpperCase()||"—"}</span>
            <span style={{color:"var(--text3)"}}>›</span>
            <span className={`chip ${setup.poi?"chip-bull":"chip-wait"}`} style={{fontSize:8,padding:"1px 6px"}}>
              {setup.confirm_timeframe?.toUpperCase()||"—"} {setup.poi?`✓ ${poiLabel(setup.poi)}`:"· scanning"}
            </span>
            <span style={{color:"var(--text3)"}}>›</span>
            <span className="chip chip-neutral" style={{fontSize:8,padding:"1px 6px"}}>ENTRY {setup.entry_timeframe?.toUpperCase()||"—"}</span>
          </div>
          <div style={{fontFamily:"var(--font-mono)",fontSize:9,color:"var(--text3)",marginTop:4}}>
            {setup.sweep_type} swept · target {setup.target!=null?Number(setup.target).toFixed(5):"—"}
          </div>
          <div style={{fontFamily:"var(--font-mono)",fontSize:9,marginTop:3,color:setup.poi?"var(--buy)":"var(--warn)"}}>
            {setup.poi
              ? `POI confirmed: ${poiLabel(setup.poi)} on ${setup.confirm_timeframe?.toUpperCase()}`
              : `Waiting for POI on ${setup.confirm_timeframe?.toUpperCase()} (OB / breaker / FVG / S&R)`}
          </div>
        </div>
      )}

      <div style={{display:"flex",alignItems:"center",justifyContent:"space-between",marginTop:12}}>
        <span className={`chip ${crtChip}`}><span className={`chip-dot ${inTrade?"pulse":""}`}/>{crtText}</span>
        {bias?.predicted_change_pct!==undefined&&(
          <span style={{fontFamily:"var(--font-mono)",fontSize:10,color:bias.predicted_change_pct>=0?"var(--buy)":"var(--sell)"}}>
            {bias.predicted_change_pct>=0?"+":""}{bias.predicted_change_pct}%
          </span>
        )}
      </div>

      {details&&details.recent_trades_count>0&&(
        <div className="range-labels" style={{marginTop:8,paddingTop:8,borderTop:"1px solid var(--border)"}}>
          <span style={{color:"var(--text3)"}}>Recent</span>
          <span><span style={{color:"var(--buy)"}}>{details.recent_wins}W</span> / <span style={{color:"var(--sell)"}}>{details.recent_losses}L</span></span>
        </div>
      )}
    </div>
  );
}
