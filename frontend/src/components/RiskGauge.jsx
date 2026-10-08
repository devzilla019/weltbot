import{fmtMoney}from"../utils/format";

/**
 * Daily loss budget. The bar fills as the budget is consumed, so the
 * remaining headroom is visible at a glance rather than needing to be read
 * off a number.
 */
export default function RiskGauge({risk}){
  if(!risk)return null;

  const used=Math.max(0,Math.min(100,100-(risk.remaining_pct??100)));
  const state=risk.halted?"halted":(risk.remaining_pct<40?"warn":"ok");

  return(
    <div className="gauge" data-state={state}>
      <div className="gauge-head">
        <span className="gauge-title">Daily Loss Budget</span>
        <span className={`chip ${risk.halted?"chip-bear":risk.tradeable?"chip-bull":"chip-wait"}`}>
          {risk.halted?"HALTED":risk.tradeable?"ACTIVE":"BALANCE LOW"}
        </span>
      </div>

      <div className="gauge-bar">
        <div className="gauge-fill" style={{width:`${used}%`}}/>
        <div className="gauge-marker" style={{left:"40%"}} title="40% remaining"/>
      </div>

      <div className="gauge-legend">
        <span><b>{fmtMoney(risk.realised_pnl,false)}</b> today</span>
        <span><b>{fmtMoney(risk.remaining_budget,false)}</b> left</span>
        <span className="dim">of {fmtMoney(risk.daily_limit_amount,false)}</span>
      </div>

      <div className="gauge-stats">
        <div>
          <label>Risk / trade</label>
          <span>{fmtMoney(risk.risk_per_trade,false)} <em>{risk.risk_pct}%</em></span>
        </div>
        <div>
          <label>Open</label>
          <span>{risk.open_positions||0}</span>
        </div>
        <div>
          <label>Closed today</label>
          <span>{risk.trades_today||0}</span>
        </div>
        <div>
          <label>Per-trade cap</label>
          <span>{risk.max_implied_risk_pct}%</span>
        </div>
      </div>

      {risk.halted&&<div className="gauge-alert">Loss limit reached — entries halted until 00:00 UTC</div>}
      {!risk.tradeable&&!risk.halted&&
        <div className="gauge-alert warn">Balance below {fmtMoney(risk.min_balance,false)} — entries will be skipped</div>}
    </div>
  );
}
