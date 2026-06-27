import { useState } from "react";

const fmt = (v) => {
  if (!v && v !== 0) return "—";
  if (v >= 10000) return `$${v.toLocaleString(undefined,{maximumFractionDigits:0})}`;
  if (v >= 1)     return `$${Number(v).toFixed(4)}`;
  if (v >= 0.01)  return `$${Number(v).toFixed(5)}`;
  return `$${Number(v).toFixed(6)}`;
};

export default function TradesTab({ trades, handleCloseTrade, handleClearTrades, loading }) {
  const [confirmClear, setConfirmClear] = useState(false);
  const [clearing,     setClearing]     = useState(false);
  const [filter,       setFilter]       = useState("all");
  const [search,       setSearch]       = useState("");

  const onClear = async () => {
    if (!confirmClear) {
      setConfirmClear(true);
      setTimeout(() => setConfirmClear(false), 4000);
      return;
    }
    setClearing(true);
    await handleClearTrades();
    setClearing(false);
    setConfirmClear(false);
  };

  const filtered = trades.filter(t => {
    const matchFilter =
      filter === "all"  ? true :
      filter === "open" ? t.outcome === "OPEN" :
      filter === "win"  ? t.outcome === "WIN"  :
      filter === "loss" ? t.outcome === "LOSS" : true;
    const matchSearch = search
      ? t.asset?.toLowerCase().includes(search.toLowerCase())
      : true;
    return matchFilter && matchSearch;
  });

  // Stats
  const closed  = trades.filter(t => t.outcome !== "OPEN");
  const wins    = closed.filter(t => t.outcome === "WIN").length;
  const losses  = closed.filter(t => t.outcome === "LOSS").length;
  const wr      = closed.length > 0 ? ((wins/closed.length)*100).toFixed(1) : "0.0";
  const totalPnl= closed.reduce((s,t) => s + (t.pnl||0), 0);
  const openCnt = trades.filter(t => t.outcome === "OPEN").length;
  const avgWin  = wins > 0
    ? closed.filter(t=>t.outcome==="WIN").reduce((s,t)=>s+(t.pnl||0),0)/wins
    : 0;
  const avgLoss = losses > 0
    ? Math.abs(closed.filter(t=>t.outcome==="LOSS").reduce((s,t)=>s+(t.pnl||0),0)/losses)
    : 0;

  return (
    <div>
      {/* Header */}
      <div style={{ display:"flex", alignItems:"center", justifyContent:"space-between", marginBottom:16, flexWrap:"wrap", gap:10 }}>
        <div>
          <div style={{ fontFamily:"var(--font-display)", fontSize:20, fontWeight:700 }}>Trade History</div>
          <div style={{ fontSize:12, color:"var(--text2)", marginTop:2 }}>
            {trades.length} total · {openCnt} open · {wins}W {losses}L
          </div>
        </div>
        {trades.length > 0 && (
          <button
            onClick={onClear}
            disabled={clearing}
            style={{
              padding:"7px 14px", borderRadius:6, fontSize:11,
              border:"1px solid", cursor:"pointer", fontFamily:"var(--font-mono)",
              background: confirmClear ? "rgba(255,77,109,0.15)" : "var(--surface2)",
              color:      confirmClear ? "var(--sell)" : "var(--text3)",
              borderColor: confirmClear ? "rgba(255,77,109,0.35)" : "var(--border)",
              transition: "all 0.2s",
            }}
          >
            {clearing ? "Clearing…" : confirmClear ? "⚠ Confirm — this cannot be undone" : "Clear History"}
          </button>
        )}
      </div>

      {/* Stats row */}
      <div style={{ display:"grid", gridTemplateColumns:"repeat(auto-fit,minmax(100px,1fr))", gap:8, marginBottom:16 }}>
        {[
          { label:"Total",    value: trades.length,             color:"var(--text)" },
          { label:"Open",     value: openCnt,                   color:"var(--info)" },
          { label:"Wins",     value: wins,                      color:"var(--buy)" },
          { label:"Losses",   value: losses,                    color:"var(--sell)" },
          { label:"Win Rate", value:`${wr}%`,                   color: parseFloat(wr)>=50?"var(--buy)":"var(--sell)" },
          { label:"Total P&L",value:`${totalPnl>=0?"+":""}$${Math.abs(totalPnl).toFixed(4)}`, color:totalPnl>=0?"var(--buy)":"var(--sell)" },
          { label:"Avg Win",  value:avgWin>0?`+$${avgWin.toFixed(4)}`:"—", color:"var(--buy)" },
          { label:"Avg Loss", value:avgLoss>0?`-$${avgLoss.toFixed(4)}`:"—", color:"var(--sell)" },
        ].map(s => (
          <div key={s.label} className="stat-card">
            <div className="stat-label">{s.label}</div>
            <div className="stat-value" style={{ color:s.color, fontSize:14 }}>{s.value}</div>
          </div>
        ))}
      </div>

      {/* Filters */}
      <div style={{ display:"flex", gap:8, marginBottom:12, alignItems:"center", flexWrap:"wrap" }}>
        <div style={{ display:"flex", gap:3 }}>
          {[["all","All"],["open","Open"],["win","Wins"],["loss","Losses"]].map(([k,l]) => (
            <button key={k}
              onClick={() => setFilter(k)}
              style={{
                padding:"5px 12px", borderRadius:5, fontSize:11, cursor:"pointer",
                border:"1px solid", fontFamily:"var(--font-mono)",
                background: filter===k ? "var(--surface3)" : "var(--surface2)",
                color:      filter===k ? "var(--text)" : "var(--text3)",
                borderColor: filter===k ? "var(--border2)" : "var(--border)",
              }}
            >{l}</button>
          ))}
        </div>
        <input
          placeholder="Search asset…"
          value={search}
          onChange={e => setSearch(e.target.value)}
          style={{
            padding:"5px 12px", borderRadius:5, fontSize:11,
            background:"var(--surface2)", border:"1px solid var(--border)",
            color:"var(--text)", fontFamily:"var(--font-mono)", outline:"none",
            width:140,
          }}
        />
      </div>

      {/* Table */}
      <div className="card" style={{ padding:0 }}>
        {filtered.length === 0 ? (
          <div className="empty-state">
            <div className="empty-icon">{trades.length === 0 ? "📋" : "🔍"}</div>
            {trades.length === 0
              ? "No trades yet — start the bot to begin tracking"
              : "No trades match the current filter"
            }
          </div>
        ) : (
          <div className="table-wrap">
            <table className="data-table">
              <thead>
                <tr>
                  <th>#</th>
                  <th>Asset</th>
                  <th>Signal</th>
                  <th>Entry</th>
                  <th>Stop</th>
                  <th>TP</th>
                  <th>Size</th>
                  <th>Conf</th>
                  <th>Status</th>
                  <th>P&L</th>
                  <th>Date</th>
                  <th>Time</th>
                  <th>Closed</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {filtered.map((t, i) => {
                  const pnlColor = (t.pnl||0) >= 0 ? "var(--buy)" : "var(--sell)";
                  const lev = (t.confidence||0) >= 98 ? 100 : (t.confidence||0) >= 95 ? 50 : (t.confidence||0) >= 90 ? 20 : 10;
                  const levCls = (t.confidence||0) >= 98 ? "lev-100" : (t.confidence||0) >= 95 ? "lev-50" : (t.confidence||0) >= 90 ? "lev-20" : "lev-10";
                  return (
                    <tr key={i}>
                      <td style={{ color:"var(--text3)", fontSize:10 }}>{t.id||i+1}</td>
                      <td>
                        <span style={{ fontFamily:"var(--font-display)", fontWeight:700, fontSize:13 }}>
                          {t.asset?.replace("/USDT","")}
                        </span>
                        <span style={{ fontSize:9, color:"var(--text3)" }}>/USDT</span>
                      </td>
                      <td>
                        <div style={{ display:"flex", flexDirection:"column", gap:2 }}>
                          <span className={`tag tag-${t.signal}`}>{t.signal}</span>
                          <span className={`lev-badge ${levCls}`}>{lev}x</span>
                        </div>
                      </td>
                      <td className="mono">{fmt(t.entry_price)}</td>
                      <td className="mono" style={{ color:"var(--sell)" }}>{fmt(t.stop_loss)}</td>
                      <td className="mono" style={{ color:"var(--buy)" }}>{fmt(t.take_profit)}</td>
                      <td className="mono" style={{ color:"var(--text3)", fontSize:11 }}>
                        {t.position_sz?.toFixed(4)||"—"}
                      </td>
                      <td style={{ color:"var(--text2)", fontSize:11, fontFamily:"var(--font-mono)" }}>
                        {t.confidence?.toFixed(1)||"—"}%
                      </td>
                      <td><span className={`tag tag-${t.outcome}`}>{t.outcome}</span></td>
                      <td style={{ fontFamily:"var(--font-mono)", fontSize:12, fontWeight:600, color:pnlColor }}>
                        {t.pnl != null ? `${t.pnl>=0?"+":""}$${t.pnl.toFixed(4)}` : "—"}
                      </td>
                      <td style={{ fontSize:11, color:"var(--text2)", whiteSpace:"nowrap" }}>{t.date||"—"}</td>
                      <td style={{ fontSize:11, color:"var(--text3)", whiteSpace:"nowrap", fontFamily:"var(--font-mono)" }}>{t.time||"—"}</td>
                      <td style={{ fontSize:10, color:"var(--text3)", whiteSpace:"nowrap" }}>
                        {t.closed_date ? `${t.closed_date} ${t.closed_time||""}` : "—"}
                      </td>
                      <td>
                        {t.outcome === "OPEN" && (
                          <button
                            className="btn btn-danger btn-xs"
                            onClick={() => handleCloseTrade(t.id)}
                          >Close</button>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}

