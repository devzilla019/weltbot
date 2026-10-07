import{useState,useEffect}from"react";
import{forexApi}from"../api";

// Human-readable labels for the POI kinds the backend returns
const POI_LABELS={
  order_block:"Order Block",
  breaker_block:"Breaker Block",
  fvg:"FVG",
  support_resistance:"S&R",
  QM:"Quasimodo",
  FVG:"FVG",
  OB:"Order Block",
};
const poiLabel=k=>POI_LABELS[k]||(k?String(k).replace(/_/g," "):"—");

const trendChip=t=>t==="BULLISH"?"chip-bull":t==="BEARISH"?"chip-bear":"chip-neutral";
const statusChip=s=>s==="ENTRY TRIGGERED"?"chip-bull":s==="SWEEP CONFIRMED"?"chip-live":s==="RANGE IDENTIFIED"?"chip-warn":"chip-wait";

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
  const trend=setup?.trend_direction||"NEUTRAL";
  const status=inTrade?"ENTRY TRIGGERED":(setup?.crt_status||"WAITING");
  const session=setup?.session||details?.session;
  const crtChip=inTrade?"chip-live":setup?"chip-bull":"chip-wait";
  const crtText=inTrade?"IN TRADE":setup?"SETUP ACTIVE":"WAITING";

  const fmt=v=>v==null?"—":Number(v).toFixed(5);
  const hi=levels?.range_high??levels?.pdh;
  const lo=levels?.range_low??levels?.pdl;
  const tf=levels?.timeframe||"1h";
  const pos=(price&&hi&&lo)?Math.max(0,Math.min(100,((price-lo)/(hi-lo))*100)):50;
  const range=(hi&&lo)?(hi-lo).toFixed(5):"—";
  const ranges=details?.crt_ranges||{};

  return(
    <div className={`pair-card ${cls}`}>
      <div className="pair-head">
        <div className="pair-symbol">{symbol}</div>
        <span className={`chip ${chip}`}><span className="chip-dot"/>{biasVal}</span>
      </div>

      {/* Trend direction + CRT status */}
      <div style={{display:"flex",gap:4,flexWrap:"wrap",marginTop:8}}>
        <span className={`chip ${trendChip(trend)}`} style={{fontSize:8,padding:"1px 6px"}}>
          {trend==="BULLISH"?"▲":trend==="BEARISH"?"▼":"◆"} {trend}
        </span>
        <span className={`chip ${statusChip(status)}`} style={{fontSize:8,padding:"1px 6px"}}>{status}</span>
        {session&&<span className="chip chip-neutral" style={{fontSize:8,padding:"1px 6px"}}>{session}</span>}
        {setup?.poi&&<span className="chip chip-live" style={{fontSize:8,padding:"1px 6px"}}>{poiLabel(setup.poi)}</span>}
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
            CRT PULLBACK · {setup.direction}
          </div>
          <div style={{display:"flex",alignItems:"center",gap:4,fontFamily:"var(--font-mono)",fontSize:9,flexWrap:"wrap"}}>
            <span className="chip chip-live" style={{fontSize:8,padding:"1px 6px"}}>H4 {trend}</span>
            <span style={{color:"var(--text3)"}}>›</span>
            <span className="chip chip-neutral" style={{fontSize:8,padding:"1px 6px"}}>H1 {setup.sweep_type} swept</span>
            <span style={{color:"var(--text3)"}}>›</span>
            <span className={`chip ${setup.poi?"chip-bull":"chip-wait"}`} style={{fontSize:8,padding:"1px 6px"}}>
              {setup.entry_timeframe?.toUpperCase()||"—"} {setup.poi?`✓ ${poiLabel(setup.poi)}`:"· scanning"}
            </span>
          </div>
          <div style={{fontFamily:"var(--font-mono)",fontSize:9,color:"var(--text3)",marginTop:4}}>
            {setup.sweep_type} swept · target {setup.target!=null?Number(setup.target).toFixed(5):"—"}
          </div>
          <div style={{fontFamily:"var(--font-mono)",fontSize:9,marginTop:3,color:setup.poi?"var(--buy)":"var(--warn)"}}>
            {setup.poi
              ? `Entry trigger: ${poiLabel(setup.poi)}`
              : `Waiting for QM / FVG / OB on ${setup.entry_timeframe?.toUpperCase()||"5M"}`}
          </div>
        </div>
      )}

      {details?.open_trade&&(
        <div style={{marginTop:10,padding:"8px 10px",borderRadius:8,background:"rgba(52,229,176,0.08)",border:"1px solid var(--border2)"}}>
          <div style={{fontFamily:"var(--font-mono)",fontSize:9,color:"var(--buy)",letterSpacing:"0.06em",marginBottom:4}}>
            OPEN · {details.open_trade.entry_type||"—"} ENTRY
          </div>
          <div className="range-labels">
            <span style={{color:"var(--warn)"}}>TP1 {fmt(details.open_trade.tp1)}</span>
            <span style={{color:"var(--buy)"}}>TP2 {fmt(details.open_trade.tp2??details.open_trade.tp)}</span>
          </div>
          {details.open_trade.partial_tp_hit&&(
            <div style={{marginTop:5}}>
              <span className="chip chip-bull" style={{fontSize:8,padding:"1px 6px"}}>50% closed</span>
            </div>
          )}
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
