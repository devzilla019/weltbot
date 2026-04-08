const LABELS = { rsi: "RSI", macd: "MACD", trend: "Trend", sentiment: "Sentiment", volume: "Volume" };

export default function ScoreBreakdown({ subScores }) {
  if (!subScores) return null;
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 5 }}>
      {Object.entries(subScores).map(([key, val]) => {
        const pct   = Math.abs(val) * 50;
        const color = val > 0.1 ? "var(--buy)" : val < -0.1 ? "var(--sell)" : "var(--muted)";
        return (
          <div key={key} style={{ display: "grid", gridTemplateColumns: "64px 1fr 34px", alignItems: "center", gap: 6 }}>
            <span className="label">{LABELS[key] || key}</span>
            <div style={{ height: 3, background: "var(--surface3)", borderRadius: 2, position: "relative" }}>
              <div style={{
                position: "absolute",
                left: val < 0 ? `${50 - pct}%` : "50%",
                width: `${pct}%`,
                height: "100%",
                background: color,
                borderRadius: 2,
              }}/>
              <div style={{ position: "absolute", left: "50%", width: 1, height: "100%", background: "var(--border2)" }}/>
            </div>
            <span className="mono" style={{ fontSize: 9, color, textAlign: "right" }}>
              {val > 0 ? "+" : ""}{Number(val).toFixed(2)}
            </span>
          </div>
        );
      })}
    </div>
  );
}