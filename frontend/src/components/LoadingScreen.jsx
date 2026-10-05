import{useState,useEffect}from"react";

/**
 * Animated boot screen.
 * Logo image lives at /logo.png (drop your file in frontend/public/logo.png).
 * Falls back to a built-in SVG mark if the image is missing.
 */
const STEPS=[
  "Initializing WeltBot core…",
  "Loading Kronos AI engine…",
  "Connecting to Binance…",
  "Linking Capital.com…",
  "Calibrating CRT + SMC layers…",
  "Syncing market data…",
  "Ready.",
];

export default function LoadingScreen({onDone}){
  const[step,setStep]=useState(0);
  const[progress,setProgress]=useState(0);
  const[exiting,setExiting]=useState(false);
  const[imgOk,setImgOk]=useState(true);

  useEffect(()=>{
    const total=STEPS.length;
    const tick=setInterval(()=>{
      setStep(s=>{
        const next=s+1;
        setProgress(Math.min(100,Math.round((next/total)*100)));
        if(next>=total){
          clearInterval(tick);
          setTimeout(()=>setExiting(true),420);
          setTimeout(()=>onDone&&onDone(),1000);
          return total-1;
        }
        return next;
      });
    },520);
    return()=>clearInterval(tick);
  },[onDone]);

  return(
    <div className={`loader-screen ${exiting?"exit":""}`}>
      <div className="loader-logo-wrap">
        <div className="loader-ring"/>
        <div className="loader-ring r2"/>
        <div className="loader-ring r3"/>
        {imgOk
          ? <img src="/logo.png" alt="WeltBot" className="loader-logo" onError={()=>setImgOk(false)}/>
          : <div className="loader-logo" style={{display:"flex",alignItems:"center",justifyContent:"center",background:"linear-gradient(135deg,#7c5cf5,#c4b5fd)",fontSize:44}}>⚡</div>
        }
      </div>

      <div style={{textAlign:"center"}}>
        <div className="loader-title"><span className="w">WELT</span><span className="b">BOT</span></div>
        <div className="loader-status" style={{marginTop:8}}>{STEPS[step]}</div>
      </div>

      <div className="loader-bar"><div className="loader-bar-fill" style={{width:`${progress}%`}}/></div>

      <div className="loader-dots">
        <div className="loader-dot"/><div className="loader-dot"/><div className="loader-dot"/>
      </div>
    </div>
  );
}
