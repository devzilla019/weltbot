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
    const t=setInterval(fetchDetails,15000);
    return()=>{alive=false;clearInterval(t);};
  },[symbol]);

  const biasVal=bias?.bias||"NEUTRAL";
  const cls=biasVal==="BULLISH"?"buy":biasVal==="BEARISH"?"sell":"";
  const chip=biasVal==="BULLISH"?"chip-bull":biasVal==="BEARISH"?"chip-bear":"chip-neutral";
  const inTrade=!!details?.open_trade;
  const crtChip=inTrade?"chip-live":"chip-wait";
  const crtText=inTrade?"IN TRADE":"WAITING";

  const fmt=v=>v==null?"—":Number(v).toFixed(5);
  const pos=(price&&levels?.pdh&&levels?.pdl)?Math.max(0,Math.min(100,((price-levels.pdl)/(levels.pdh-levels.pdl))*100)):50;
  const range=(levels?.pdh&&levels?.pdl)?(levels.pdh-levels.pdl).toFixed(5):"—";

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
            <span style={{color:"var(--sell)"}}>PDH {fmt(levels.pdh)}</span>
            <span style={{color:"var(--buy)"}}>PDL {fmt(levels.pdl)}</span>
          </div>
          <div style={{textAlign:"center",fontFamily:"var(--font-mono)",fontSize:9,color:"var(--text3)",marginTop:6}}>
            range {range}
          </div>
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
