export const fmtPrice=v=>v==null?"—":Number(v).toFixed(5);
export const fmtMoney=(v,sign=true)=>{
  if(v==null)return"—";
  const n=Number(v);
  return `${sign&&n>0?"+":""}$${Math.abs(n).toFixed(2)}`;
};
export const fmtUnits=v=>v==null?"—":Number(v).toLocaleString();
export const pnlColor=v=>(v||0)>=0?"var(--buy)":"var(--sell)";
export const relTime=d=>{
  if(!d)return"—";
  const diff=Math.floor((Date.now()-new Date(d).getTime())/1000);
  if(diff<60)return`${diff}s ago`;
  if(diff<3600)return`${Math.floor(diff/60)}m ago`;
  if(diff<86400)return`${Math.floor(diff/3600)}h ago`;
  return`${Math.floor(diff/86400)}d ago`;
};
export const clockTime=d=>d?new Date(d).toLocaleTimeString(undefined,{hour:"2-digit",minute:"2-digit",second:"2-digit"}):"—";
