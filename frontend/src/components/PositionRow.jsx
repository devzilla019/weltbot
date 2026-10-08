import{useState}from"react";
import{fmtPrice,fmtMoney,fmtUnits,pnlColor}from"../utils/format";

/**
 * One open position. Expands inline to show the full risk picture and the
 * TP1/TP2/TP3 ladder, and carries a confirm-guarded close button so a
 * position is never closed by a stray click.
 */
export default function PositionRow({p,onClose,busy}){
  const[open,setOpen]=useState(false);
  const[confirming,setConfirming]=useState(false);
  const up=(p.pnl||0)>=0;

  const doClose=async()=>{
    setConfirming(false);
    await onClose(p.id);
  };

  return(
    <div className="pos-row" data-side={p.signal}>
      <div className="pos-main" onClick={()=>setOpen(o=>!o)}>
        <span className="pos-caret">{open?"▾":"▸"}</span>

        <div className="pos-sym">
          <span className="pos-sym-name">{p.symbol}</span>
          <span className={`chip ${p.signal==="BUY"?"chip-bull":"chip-bear"}`}>{p.signal}</span>
        </div>

        <div className="pos-cell">
          <label>Size</label>
          <span className="mono">{fmtUnits(p.size)}</span>
        </div>

        <div className="pos-cell">
          <label>Entry</label>
          <span className="mono">{fmtPrice(p.entry)}</span>
        </div>

        <div className="pos-cell">
          <label>Last</label>
          <span className="mono" style={{color:pnlColor(p.pnl)}}>{fmtPrice(p.current)}</span>
        </div>

        <div className="pos-cell pos-cell-pnl">
          <label>P&L</label>
          <span className="mono pos-pnl" style={{color:pnlColor(p.pnl)}}>
            {fmtMoney(p.pnl)}
            <em>{(p.pnl_pct||0).toFixed(3)}%</em>
          </span>
        </div>

        <div className="pos-progress">
          <div className="pos-progress-bar">
            <div className="pos-progress-fill"
                 style={{width:`${Math.max(0,Math.min(100,p.progress||0))}%`,
                         background:pnlColor(p.pnl)}}/>
          </div>
          <span className="pos-progress-label">{(p.progress||0).toFixed(0)}% to TP</span>
        </div>

        <div className="pos-actions" onClick={e=>e.stopPropagation()}>
          {confirming
            ?<>
              <button className="btn btn-danger btn-xs" disabled={busy} onClick={doClose}>Confirm</button>
              <button className="btn btn-ghost btn-xs" onClick={()=>setConfirming(false)}>✕</button>
             </>
            :<button className="btn btn-danger btn-xs" disabled={busy}
                     onClick={()=>setConfirming(true)}>Close</button>}
        </div>
      </div>

      {open&&(
        <div className="pos-detail">
          <div className="pos-detail-grid">
            <div className="pos-detail-cell">
              <label>Stop Loss</label>
              <span className="mono" style={{color:"var(--sell)"}}>{fmtPrice(p.sl)}</span>
            </div>
            <div className="pos-detail-cell">
              <label>TP1 · 1:1</label>
              <span className="mono" style={{color:"var(--warn)"}}>{fmtPrice(p.tp1)}</span>
            </div>
            <div className="pos-detail-cell">
              <label>TP2 · 1:2</label>
              <span className="mono" style={{color:"var(--buy)"}}>{fmtPrice(p.tp2??p.tp)}</span>
            </div>
            <div className="pos-detail-cell">
              <label>R:R</label>
              <span className="mono">1:{p.risk_reward||0}</span>
            </div>
            <div className="pos-detail-cell">
              <label>Confidence</label>
              <span className="mono">{(p.confidence||0).toFixed(0)}%</span>
            </div>
            <div className="pos-detail-cell">
              <label>Entry Type</label>
              <span>{p.entry_type
                ?<span className="chip chip-live">{p.entry_type}</span>
                :<span className="dim">—</span>}</span>
            </div>
          </div>

          <div className="pos-tags">
            {p.partial_tp_hit&&<span className="chip chip-bull">50% closed · SL at breakeven</span>}
            {p.kronos_bias&&p.kronos_bias!=="NEUTRAL"&&<span className="chip chip-neutral">Kronos {p.kronos_bias}</span>}
            {p.crt_setup&&p.crt_setup!=="NONE"&&<span className="chip chip-neutral">{p.crt_setup} setup</span>}
            {p.opened_at&&<span className="chip chip-neutral">opened {relTimeShort(p.opened_at)}</span>}
          </div>
        </div>
      )}
    </div>
  );
}

function relTimeShort(d){
  const diff=Math.floor((Date.now()-new Date(d).getTime())/1000);
  if(diff<3600)return`${Math.floor(diff/60)}m ago`;
  if(diff<86400)return`${Math.floor(diff/3600)}h ago`;
  return`${Math.floor(diff/86400)}d ago`;
}
