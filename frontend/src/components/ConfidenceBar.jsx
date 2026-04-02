export default function ConfidenceBar({ value, signal }) {
  const color =
    signal === "BUY"  ? "var(--buy)"  :
    signal === "SELL" ? "var(--sell)" : "var(--hold)";

  return (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 5 }}>
        <span className="label">Confidence</span>
        <span className="mono" style={{ fontSize: 11, color }}>{value}%</span>
      </div>
      <div style={{ height: 3, background: "var(--sur2)", borderRadius: 2 }}>
        <div style={{
          height: "100%",
          width: `${value}%`,
          background: color,
          borderRadius: 2,
          transition: "width 0.8s ease",
        }}/>
      </div>
      <div style={{ fontSize: 10, color: "var(--muted)", marginTop: 3 }}>
        Signal alignment — not a win probability
      </div>
    </div>
  );
}