import{useState,useEffect,useCallback,useRef}from"react";

/**
 * Live control-room data layer.
 *
 * Polls the endpoints the control room needs and exposes a single refresh()
 * so any action (close, close-all, scan) can pull fresh state immediately
 * instead of waiting for the next tick.
 */
export function useLiveData(api,forexApi){
  const[state,setState]=useState({
    botStatus:null, forex:null, forexPositions:null, forexTrades:[],
    signals:[], summary:null, portfolio:null, dailyRisk:null, backendDown:false,
  });
  const[loading,setLoading]=useState(true);
  const[lastUpdate,setLastUpdate]=useState(null);
  const busy=useRef(false);

  const refresh=useCallback(async()=>{
    if(busy.current)return;
    busy.current=true;
    try{
      const[st,fx,fxpos,fxtr,sigs,sum,port,risk]=await Promise.all([
        api.getBotStatus().catch(()=>null),
        forexApi.getStatus().catch(()=>null),
        forexApi.getPositions().catch(()=>null),
        forexApi.getTrades(50).catch(()=>[]),
        api.getAllSignals().catch(()=>[]),
        api.getSummary().catch(()=>null),
        api.getPortfolio().catch(()=>null),
        forexApi.dailyRisk().catch(()=>null),
      ]);
      setState({
        botStatus:st,
        forex:fx,
        forexPositions:fxpos,
        forexTrades:Array.isArray(fxtr)?fxtr:[],
        signals:Array.isArray(sigs)?sigs:[],
        summary:sum,
        portfolio:port,
        dailyRisk:risk||fx?.daily_risk||null,
        backendDown:!st,
      });
      setLastUpdate(new Date());
    }catch{
      setState(s=>({...s,backendDown:true}));
    }finally{
      setLoading(false);
      busy.current=false;
    }
  },[api,forexApi]);

  useEffect(()=>{
    refresh();
    const t=setInterval(refresh,15000);
    return()=>clearInterval(t);
  },[refresh]);

  return{...state,loading,lastUpdate,refresh};
}
