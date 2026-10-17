import{useState,useEffect}from"react";
import{forexApi}from"../api";

/**
 * One pair's Silver Bullet state.
 *
 * Replaces CRTSignalCard. Every value comes from /api/forex/pair/{symbol} and
 * /api/forex/status — nothing here is a placeholder. Where the backend has no
 * value yet (no bias computed, no setup formed) the card says so rather than
 * showing a default that would look like real data.
 *
 * The confidence number is a rule-based RANKING of setup quality, not a
 * probability. It is labelled "score" for that reason.
 */

// The engine's state names, in pipeline order, with what each one means.
const STATE_LABELS={
  WAITING:"Waiting",
  SWEEP_DETECTED:"Sweep",
  MSS_CONFIRMED:"MSS",
  FVG_FOUND:"FVG armed",
  IN_TRADE:"In trade",
  EXPIRED:"Expired",
  INVALID:"Rejected",
};
const STATE_CHIP={
  WAITING:"chip-wait",
  SWEEP_DETECTED:"chip-live",
  MSS_CONFIRMED:"chip-live",
  FVG_FOUND:"chip-bull",
  IN_TRADE:"chip-bull",
  EXPIRED:"chip-neutral",
  INVALID:"chip-bear",
};

// Volume-profile confluence grades, strongest first.
const VP_LABELS={
  POC_OVERLAP:"POC",
  VAH_CONFLUENCE:"VAH",
  VAL_CONFLUENCE:"VAL",
  INSIDE_VALUE:"inside VA",
  NO_CONFLUENCE:"no VP",
};

const biasChip=b=>b==="BULLISH"?"chip-bull":b==="BEARISH"?"chip-bear":"chip-neutral";
const biasGlyph=b=>b==="BULLISH"?"▲":b==="BEARISH"?"▼":"◆";
const fmt=v=>v==null?"—":Number(v).toFixed(5);
const fmtMoney=v=>`${v>=0?"+":""}$${Math.abs(v||0).toFixed(2)}`;

export default function SilverBulletCard({symbol,bias,index=0}){
  const[details,setDetails]=useState(null);
  const[loading,setLoading]=useState(true);
  const[err,setErr]=useState(null);

  useEffect(()=>{
    let alive=true;
    const fetchDetails=async()=>{
      try{
        const d=await forexApi.getPair(symbol);
        if(alive){setDetails(d);setErr(null);}
      }catch(e){
        if(alive)setErr(e.message||"Failed to load");
      }finally{
        if(alive)setLoading(false);
      }
    };
    // Stagger the first call per card so a wall of cards does not hit the API
    // in the same tick.
    const start=setTimeout(fetchDetails,index*400);
    const t=setInterval(fetchDetails,90000);
    return()=>{alive=false;clearTimeout(start);clearInterval(t);};
  },[symbol,index]);

  if(loading){
    return<div className="pair-card"><div className="skeleton" style={{height:180}}/></div>;
  }
  if(err){
    return(
      <div className="pair-card">
        <div className="pair-head"><div className="pair-symbol">{symbol}</div></div>
        <div className="info-box info-box-red" style={{marginTop:10,fontSize:10}}>⚠ {err}</div>
      </div>
    );
  }

  const sb=details?.silver_bullet;
  const trade=details?.open_trade;
  const price=details?.current_price;

  // The card falls back to the status payload's bias when the per-pair call has
  // not supplied one yet, so it never shows "no bias" while a bias exists.
  const h4=sb?.h4_bias??bias?.h4_bias??bias?.bias??null;
  const vp=sb?.vp_levels;
  const setup=sb?.setup;
  const state=setup?.state;
  const conf=setup?.confidence;
  const minConf=sb?.min_confidence??88;

  const poc=vp?.poc,vah=vp?.vah,val=vp?.val;
  const pos=(price&&vah&&val)?Math.max(0,Math.min(100,((price-val)/(vah-val))*100)):null;

  return(
    <div className={`pair-card ${h4==="BULLISH"?"buy":h4==="BEARISH"?"sell":""}`}>
      <div className="pair-head">
        <div className="pair-symbol">{symbol}</div>
        <span className={`chip ${biasChip(h4)}`}>
          <span className="chip-dot"/>{h4?`${biasGlyph(h4)} ${h4}`:"no bias"}
        </span>
      </div>

      {/* Session + setup status */}
      <div style={{display:"flex",gap:4,flexWrap:"wrap",marginTop:8}}>
        {sb?.session_levels&&(
          <span className="chip chip-neutral" style={{fontSize:8,padding:"1px 6px"}}>
            {sb.session_levels.session} levels
          </span>
        )}
        {setup?.session&&(
          <span className="chip chip-neutral" style={{fontSize:8,padding:"1px 6px"}}>{setup.session}</span>
        )}
        {state&&(
          <span className={`chip ${STATE_CHIP[state]||"chip-wait"}`} style={{fontSize:8,padding:"1px 6px"}}>
            {STATE_LABELS[state]||state}
          </span>
        )}
        {setup?.vp_confluence&&(
          <span className={`chip ${setup.vp_confluence==="NO_CONFLUENCE"?"chip-wait":"chip-bull"}`}
                style={{fontSize:8,padding:"1px 6px"}}>
            {VP_LABELS[setup.vp_confluence]||setup.vp_confluence}
          </span>
        )}
      </div>

      <div className="pair-price-label">Current Price</div>
      <div className="pair-price">{price?fmt(price):"—"}</div>

      {/* Volume profile levels */}
      <div className="pair-price-label" style={{marginTop:8}}>Previous-Day Volume Profile</div>
      {vp?(
        <>
          <div className="range-meter">
            {pos!=null&&<div className="range-marker" style={{left:`${pos}%`}}/>}
          </div>
          <div className="range-labels">
            <span style={{color:"var(--sell)"}}>VAL {fmt(val)}</span>
            <span style={{color:"var(--warn)"}}>POC {fmt(poc)}</span>
            <span style={{color:"var(--buy)"}}>VAH {fmt(vah)}</span>
          </div>
          <div style={{textAlign:"center",fontFamily:"var(--font-mono)",fontSize:9,color:"var(--text3)",marginTop:6}}>
            {vp.source_trusted
              ? `${vp.volume_source} volume`
              : `${vp.volume_source||"range"} proxy — not gating`}
          </div>
          {vp.valid===false&&vp.warning&&(
            <div style={{textAlign:"center",fontFamily:"var(--font-mono)",fontSize:9,color:"var(--warn)",marginTop:3}}>
              {vp.warning}
            </div>
          )}
        </>
      ):(
        <div style={{fontFamily:"var(--font-mono)",fontSize:9,color:"var(--text3)",textAlign:"center",padding:"8px 0"}}>
          No previous-day profile
        </div>
      )}

      {sb?.price_position&&(
        <div style={{textAlign:"center",fontFamily:"var(--font-mono)",fontSize:9,color:"var(--text3)",marginTop:4}}>
          price {sb.price_position.replace(/_/g," ").toLowerCase()}
          {sb.vp_bias?` · ${sb.vp_bias}`:""}
        </div>
      )}

      {/* Pending setup */}
      {setup&&(
        <div style={{marginTop:10,padding:"8px 10px",borderRadius:8,background:"rgba(167,139,250,0.08)",border:"1px solid var(--border2)"}}>
          <div style={{display:"flex",justifyContent:"space-between",alignItems:"center",marginBottom:4}}>
            <span style={{fontFamily:"var(--font-mono)",fontSize:9,color:"var(--lav-2)",letterSpacing:"0.06em"}}>
              SETUP · {setup.direction||"—"}
            </span>
            {conf!=null&&(
              <span style={{fontFamily:"var(--font-mono)",fontSize:9,
                            color:conf>=minConf?"var(--buy)":"var(--warn)"}}>
                score {conf} / min {minConf}
              </span>
            )}
          </div>
          <div className="range-labels">
            <span style={{color:"var(--text3)"}}>FVG {fmt(setup.fvg_low)}</span>
            <span style={{color:"var(--text3)"}}>{fmt(setup.fvg_high)}</span>
          </div>
          <div style={{fontFamily:"var(--font-mono)",fontSize:9,color:"var(--text3)",marginTop:4}}>
            sweep wick {fmt(setup.sweep_wick)}
            {setup.expires_at?` · expires ${String(setup.expires_at).slice(11,16)} UTC`:""}
          </div>
          {setup.executable===false&&setup.reject_reason&&(
            <div style={{fontFamily:"var(--font-mono)",fontSize:9,color:"var(--warn)",marginTop:4}}>
              {setup.reject_reason}
            </div>
          )}
        </div>
      )}

      {/* Open position: targets, P&L, breakeven state */}
      {trade&&(
        <div style={{marginTop:10,padding:"8px 10px",borderRadius:8,background:"rgba(52,229,176,0.08)",border:"1px solid var(--border2)"}}>
          <div style={{display:"flex",justifyContent:"space-between",alignItems:"center",marginBottom:4}}>
            <span style={{fontFamily:"var(--font-mono)",fontSize:9,color:"var(--buy)",letterSpacing:"0.06em"}}>
              OPEN · {trade.signal} · {trade.entry_type||"—"}
            </span>
            {trade.partial_close_pct>0&&(
              <span className="chip chip-bull" style={{fontSize:8,padding:"1px 6px"}}>
                {Number(trade.partial_close_pct).toFixed(0)}% closed
              </span>
            )}
          </div>

          <div className="range-labels" style={{marginTop:2}}>
            <span style={{color:"var(--text3)"}}>Entry {fmt(trade.entry)}</span>
            <span style={{color:"var(--warn)"}}>SL {fmt(trade.sl)}</span>
          </div>
          <div className="range-labels" style={{marginTop:3}}>
            <span style={{color:trade.tp1_done?"var(--buy)":"var(--text3)"}}>TP1 {fmt(trade.tp1)}</span>
            <span style={{color:trade.tp2_done?"var(--buy)":"var(--text3)"}}>TP2 {fmt(trade.tp2)}</span>
            <span style={{color:trade.tp3_done?"var(--buy)":"var(--text3)"}}>TP3 {fmt(trade.tp3)}</span>
          </div>

          <div style={{display:"flex",gap:4,flexWrap:"wrap",marginTop:6}}>
            {trade.breakeven_done&&(
              <span className="chip chip-live" style={{fontSize:8,padding:"1px 6px"}}>
                stop at entry
              </span>
            )}
            {trade.trailing_active&&(
              <span className="chip chip-live" style={{fontSize:8,padding:"1px 6px"}}>trailing</span>
            )}
            {trade.vp_confluence&&(
              <span className="chip chip-neutral" style={{fontSize:8,padding:"1px 6px"}}>
                {VP_LABELS[trade.vp_confluence]||trade.vp_confluence}
              </span>
            )}
          </div>
          {/* A stop at entry caps the loss at entry. It is NOT a guaranteed
              profit: fees, financing and any gap through the stop still lose. */}
          {trade.breakeven_done&&(
            <div style={{fontFamily:"var(--font-mono)",fontSize:8,color:"var(--text3)",marginTop:4}}>
              stop at entry caps the loss — not a guaranteed profit after fees
            </div>
          )}
        </div>
      )}

      <div style={{display:"flex",alignItems:"center",justifyContent:"space-between",marginTop:12}}>
        <span className={`chip ${trade?"chip-live":setup?"chip-bull":"chip-wait"}`}>
          <span className={`chip-dot ${trade?"pulse":""}`}/>
          {trade?"IN TRADE":setup?"ARMED":"WAITING"}
        </span>
        {details?.recent_trades_count>0&&(
          <span style={{fontFamily:"var(--font-mono)",fontSize:9,color:"var(--text3)"}}>
            <span style={{color:"var(--buy)"}}>{details.recent_wins}W</span>
            {" / "}
            <span style={{color:"var(--sell)"}}>{details.recent_losses}L</span>
          </span>
        )}
      </div>
    </div>
  );
}
