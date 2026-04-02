import ConfidenceBar from "./ConfidenceBar";
import ScoreBreakdown from "./ScoreBreakdown";

export default function SignalCard({ data, selected, onSelect, onExecute }) {
  const s = data?.signal_data;
  if (!s) return null;

  const change      = s.market?.change_pct ?? 0;
  const changeColor = change >= 0 ? "var(--buy)" : "var(--sell)";
  const price       = s.market?.price ?? 0;

  return (
    <div
      className="card"
      onClick={() => onSelect(data)}
      style={{
        cursor: "pointer",
        outline: selected ? "1px solid var(--info)" : "none",
        display: "flex",
        flexDirection: "column",
        gap: 14,
        transition: "outline 0.15s",
      }}
    >
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
        <div>
          <div className="mono" style={{ fontSize: 15, fontWeight: 500 }}>{s.symbol}</div>
          <div style={{ display: "flex", alignItems: "baseline", gap: 8, marginTop: 4 }}>
            <span style={{ fontSize: 20, fontWeight: 600 }}>
              ${price.toLocaleString(undefined, { maximumFractionDigits: 2 })}
            </span>
            <span className="mono" style={{ fontSize: 11, color: changeColor }}>
              {change >= 0 ? "+" : ""}{change}%
            </span>
          </div>
        </div>
        <span className={`tag ${s.signal}`}>{s.signal}</span>
      </div>

      <ConfidenceBar value={s.confidence} signal={s.signal} />

      <div style={{ borderTop: "1px solid var(--border)", paddingTop: 12 }}>
        <ScoreBreakdown subScores={s.sub_scores} />
      </div>

      <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
        {s.reasoning?.slice(0, 2).map((r, i) => (
          <div key={i} style={{ color: "var(--muted)", fontSize: 11 }}>› {r}</div>
        ))}
      </div>

      <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
        <span className="label">Sentiment</span>
        <span style={{
          fontSize: 11,
          fontWeight: 500,
          color: s.sentiment?.label === "bullish" ? "var(--buy)"
               : s.sentiment?.label === "bearish" ? "var(--sell)" : "var(--muted)",
        }}>
          {s.sentiment?.label?.toUpperCase()}
        </span>
        <span className="mono" style={{ fontSize: 10, color: "var(--muted)" }}>
          ({s.sentiment?.score > 0 ? "+" : ""}{s.sentiment?.score?.toFixed(3)})
        </span>
      </div>

      {s.signal !== "HOLD" && (
        <button
          className="primary"
          onClick={e => { e.stopPropagation(); onExecute(s.symbol); }}
        >
          Simulate {s.signal}
        </button>
      )}
    </div>
  );
}