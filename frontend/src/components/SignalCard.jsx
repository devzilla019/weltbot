import ConfidenceBar from "./ConfidenceBar";

export default function SignalCard({ data, selected, onSelect }) {
  const s = data?.signal_data;
  if (!s) return null;

  const price       = s.market?.price ?? 0;
  const change      = s.market?.change_pct ?? 0;
  const changeColor = change >= 0 ? "var(--buy)" : "var(--sell)";
  const bos         = s.bos;
  const fib         = s.fib;
  const ob          = s.ob;
  const hasSetup    = bos && fib && ob;
  const reason      = s.reason || "";
  const entryType   = s.entry_type || null;
  const entryTf     = s.entry_tf || null;

  const stageColor = (met) => met ? "var(--buy)" : "var(--muted)";

  const stages = [
    { label: "BOS",    met: !!bos },
    { label: "Fib",    met: !!(bos && fib) },
    { label: "OB",     met: !!(bos && fib && ob) },
    { label: "MA",     met: !!(hasSetup && s.sub_scores?.ma !== undefined) },
    { label: "Entry",  met: !!(entryType) },
  ];

  return (
    <div
      className="card"
      onClick={() => onSelect(data)}
      style={{
        cursor: "pointer",
        outline: selected ? "1px solid var(--info)" : "none",
        display: "flex",
        flexDirection: "column",
        gap: 10,
        transition: "outline 0.15s",
        opacity: s.signal === "HOLD" ? 0.75 : 1,
      }}
    >
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
        <div>
          <div className="mono" style={{ fontSize: 13, fontWeight: 600 }}>
            {s.symbol?.replace("/USDT", "")}
            <span style={{ fontSize: 9, color: "var(--muted)", marginLeft: 4 }}>/USDT</span>
          </div>
          <div style={{ display: "flex", alignItems: "baseline", gap: 6, marginTop: 3 }}>
            <span style={{ fontSize: 17, fontWeight: 600 }}>
              ${price < 1 ? price.toFixed(6) : price.toLocaleString(undefined, { maximumFractionDigits: 4 })}
            </span>
            <span className="mono" style={{ fontSize: 10, color: changeColor }}>
              {change >= 0 ? "+" : ""}{change}%
            </span>
          </div>
        </div>
        <span className={`tag ${s.signal}`}>{s.signal}</span>
      </div>

      {s.signal !== "HOLD" && (
        <ConfidenceBar value={s.confidence} signal={s.signal} />
      )}

      <div style={{ display: "flex", gap: 6 }}>
        {stages.map(({ label, met }) => (
          <div key={label} style={{
            flex: 1, textAlign: "center",
            background: met ? "rgba(0,208,132,0.08)" : "var(--surface2)",
            border: `1px solid ${met ? "rgba(0,208,132,0.25)" : "var(--border)"}`,
            borderRadius: 4, padding: "4px 2px",
          }}>
            <div style={{ fontSize: 9, color: stageColor(met), fontFamily: "var(--mono)", fontWeight: 600 }}>
              {label}
            </div>
            <div style={{ fontSize: 8, color: met ? "var(--buy)" : "var(--dim)", marginTop: 1 }}>
              {met ? "✓" : "–"}
            </div>
          </div>
        ))}
      </div>

      {s.signal !== "HOLD" && hasSetup && (
        <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
          {s.reasoning?.slice(0, 3).map((r, i) => (
            <div key={i} style={{ color: "var(--muted)", fontSize: 10 }}>› {r}</div>
          ))}
        </div>
      )}

      {s.signal === "HOLD" && reason && (
        <div style={{
          background: "var(--surface2)", borderRadius: 6, padding: "6px 8px",
          fontSize: 10, color: "var(--muted)", lineHeight: 1.5,
        }}>
          {reason.length > 80 ? reason.slice(0, 80) + "…" : reason}
        </div>
      )}

      {entryType && (
        <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
          <span style={{
            background: "rgba(0,208,132,0.1)",
            border: "1px solid rgba(0,208,132,0.3)",
            borderRadius: 4, padding: "2px 8px",
            fontSize: 10, color: "var(--buy)", fontFamily: "var(--mono)",
          }}>
            {entryType} on {entryTf}
          </span>
        </div>
      )}
    </div>
  );
}