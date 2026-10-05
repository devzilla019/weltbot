import{useState,useEffect}from"react";
import{forexApi}from"../api";

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
  const crtChip=inTrade?"chip-live":"chip-wait";
  const crtText=inTrade?"IN TRADE":"WAITING";

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
