const BASE=import.meta.env.VITE_API_URL||"http://localhost:8000";
const req=async(method,path,body,token)=>{
  const h={"Content-Type":"application/json"};
  if(token)h["Authorization"]=`Bearer ${token}`;
  const r=await fetch(`${BASE}${path}`,{method,headers:h,body:body?JSON.stringify(body):undefined});
  const d=await r.json().catch(()=>({}));
  if(!r.ok)throw new Error(d.detail||d.error||`HTTP ${r.status}`);
  return d;
};
export const authApi={
  register:(name,email,pw)=>req("POST","/api/auth/register",{name,email,password:pw}),
  login:(email,pw)=>req("POST","/api/auth/login",{email,password:pw}),
  getMe:(t)=>req("GET","/api/auth/me",null,t),
  saveKeys:(t,k,s)=>req("POST","/api/auth/keys",{api_key:k,api_secret:s},t),
  getKeyStat:(t)=>req("GET","/api/auth/keys/status",null,t),
  toggleNet:(t,testnet)=>req("POST","/api/auth/network",{testnet},t),
  updateName:(t,name)=>req("PUT","/api/auth/profile",{name},t),
  saveSettings:(t,d)=>req("POST","/api/auth/settings",d,t),
};
export const makeApi=(token)=>({
  getBotStatus:()=>req("GET","/api/bot/status",null,token),
  startBot:()=>req("POST","/api/bot/start",null,token),
  stopBot:()=>req("POST","/api/bot/stop",null,token),
  scanNow:()=>req("POST","/api/bot/scan-now",null,token),
  getAllSignals:()=>req("GET","/api/signals/",null,token),
  getTrades:()=>req("GET","/api/trades/",null,token),
  clearTrades:()=>req("DELETE","/api/trades/clear",null,token),
  closeTrade:(id)=>req("POST",`/api/trades/${id}/close`,null,token),
  getSummary:()=>req("GET","/api/analytics/summary",null,token),
  getPortfolio:()=>req("GET","/api/analytics/portfolio",null,token),
  updateBotSettings:(d)=>req("POST","/api/analytics/settings/bot",d,token),
  getBotSettings:()=>req("GET","/api/analytics/settings/bot",null,token),
});
