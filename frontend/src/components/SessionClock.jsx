import{useState,useEffect}from"react";

const SESSIONS=[
  {name:"London",      open:8,  close:9,  note:"Silver Bullet"},
  {name:"NY Morning",  open:15, close:16, note:"Prime time"},
  {name:"NY Afternoon",open:19, close:20, note:"Silver Bullet"},
];

/**
 * Session clock. Shows which trading window is open, how long is left, and
 * counts down to the next one — so it is obvious at a glance whether the bot
 * is inside a window where it is allowed to trade.
 */
export default function SessionClock(){
  const[now,setNow]=useState(new Date());
  useEffect(()=>{
    const t=setInterval(()=>setNow(new Date()),1000);
    return()=>clearInterval(t);
  },[]);

  const h=now.getUTCHours();
  const active=SESSIONS.find(s=>h>=s.open&&h<s.close);
  const next=SESSIONS.find(s=>s.open>h)||SESSIONS[0];

  const secsLeft=active
    ? (active.close*3600)-(h*3600+now.getUTCMinutes()*60+now.getUTCSeconds())
    : null;

  const secsToNext=next
    ? ((next.open-h+24)%24*3600)-(now.getUTCMinutes()*60+now.getUTCSeconds())
    : null;

  const fmt=s=>{
    if(s==null||s<0)return"—";
    const hh=Math.floor(s/3600),mm=Math.floor((s%3600)/60),ss=s%60;
    return hh>0?`${hh}h ${mm}m`:`${mm}m ${String(ss).padStart(2,"0")}s`;
  };

  return(
    <div className="session-clock" data-active={!!active}>
      <div className="session-head">
        <span className="session-dot"/>
        <span className="session-name">
          {active?`${active.name} OPEN`:"MARKET QUIET"}
        </span>
        <span className="session-utc">{String(now.getUTCHours()).padStart(2,"0")}:
          {String(now.getUTCMinutes()).padStart(2,"0")} UTC</span>
      </div>

      {active
        ?<div className="session-body">
          <div className="session-count">
            <label>closes in</label>
            <b>{fmt(secsLeft)}</b>
          </div>
          <div className="session-note">{active.note}</div>
        </div>
        :<div className="session-body">
          <div className="session-count">
            <label>next · {next.name}</label>
            <b>{fmt(secsToNext)}</b>
          </div>
          <div className="session-note">no trades outside windows</div>
        </div>}

      <div className="session-track">
        {SESSIONS.map(s=>(
          <span key={s.name}
                className="session-slot"
                data-state={active?.name===s.name?"active":(h<s.open?"upcoming":"done")}
                title={`${s.name} ${String(s.open).padStart(2,"0")}:00–${String(s.close).padStart(2,"0")}:00 UTC`}>
            {String(s.open).padStart(2,"0")}
          </span>
        ))}
      </div>
    </div>
  );
}
