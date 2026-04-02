const LABELS = {
  rsi: "RSI", macd: "MACD", trend: "Trend",
  sentiment: "Sentiment", volume: "Volume", onchain: "On-chain",
};

export default function ScoreBreakdown({ subScores }) {
  if (!subScores) return null;
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
      {Object.entries(subScores).map(([key, val]) => {
        const pct   = Math.abs(val) * 50;
        const color = val > 0.1 ? "var(--buy)" : val < -0.1 ? "var(--sell)" : "var(--muted)";
        return (
          <div key={key} style={{ display: "grid", gridTemplateColumns: "70px 1fr 36px", alignItems: "center", gap: 8 }}>
            <span className="label">{LABELS[key]}</span>
            <div style={{ height: 3, background: "var(--sur2)", borderRadius: 2, position: "relative" }}>
              <div style={{
                position: "absolute",
                left: val < 0 ? `${50 - pct}%` : "50%",
                width: `${pct}%`,
                height: "100%",
                background: color,
                borderRadius: 2,
              }}/>
              <div style={{ position: "absolute", left: "50%", width: 1, height: "100%", background: "var(--bord2)" }}/>
            </div>
            <span className="mono" style={{ fontSize: 10, color, textAlign: "right" }}>
              {val > 0 ? "+" : ""}{Number(val).toFixed(2)}
            </span>
          </div>
        );
      })}
    </div>
  );
}