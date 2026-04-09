export default function BotStatus({
  status,
  portfolio,
  onStart,
  onStop,
  onScan,
  loading,
}) {
  if (!status) return null;

  const isLive = status.running && !status.paused;
  const isPaused = status.paused;
  const isStopped = !status.running;

  const dotColor = isLive
    ? "var(--buy)"
    : isPaused
      ? "var(--hold)"
      : "var(--sell)";
  const stateLabel = isLive ? "LIVE" : isPaused ? "PAUSED" : "STOPPED";
  const fmt = (v) => !v ? "—" : v < 1 ? `$${Number(v).toFixed(5)}` : `$${Number(v).toFixed(2)}`;

  return (
    <div
      className="card"
      style={{ display: "flex", flexDirection: "column", gap: 16 }}
    >
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <div
            style={{
              width: 10,
              height: 10,
              borderRadius: "50%",
              background: dotColor,
              animation: isLive ? "pulse 2s infinite" : "none",
            }}
          />
          <span
            style={{
              fontFamily: "var(--mono)",
              fontSize: 18,
              fontWeight: 600,
              letterSpacing: "0.05em",
            }}
          >
            WELTBOT
          </span>
          <span
            style={{
              fontFamily: "var(--mono)",
              fontSize: 10,
              color: dotColor,
              letterSpacing: "0.1em",
            }}
          >
            {stateLabel}
          </span>
          {status.testnet && <span className="tag testnet">TESTNET</span>}
        </div>
        <div style={{ textAlign: "right" }}>
          <div
            style={{
              fontFamily: "var(--mono)",
              fontSize: 22,
              fontWeight: 600,
              color: "var(--buy)",
            }}
          >
            ${status.balance_usdt?.toFixed(2) || "0.00"}
            <span
              style={{ fontSize: 11, color: "var(--muted)", marginLeft: 6 }}
            >
              USDT
            </span>
          </div>
          {portfolio && (
            <div
              style={{
                fontSize: 10,
                fontFamily: "var(--mono)",
                color:
                  portfolio.unrealized_pnl >= 0 ? "var(--buy)" : "var(--sell)",
                marginTop: 2,
              }}
            >
              Unrealized: {portfolio.unrealized_pnl >= 0 ? "+" : ""}$
              {portfolio.unrealized_pnl?.toFixed(4)}
            </div>
          )}
        </div>
      </div>

      {isPaused && status.pause_reason && (
        <div
          style={{
            background: "rgba(245,166,35,0.08)",
            border: "1px solid rgba(245,166,35,0.25)",
            borderRadius: 6,
            padding: "8px 12px",
            fontSize: 11,
            color: "var(--hold)",
            fontFamily: "var(--mono)",
          }}
        >
          PAUSED: {status.pause_reason}
        </div>
      )}

      <div style={{ display: "flex", gap: 8 }}>
        {!isLive && (
          <button className="btn-start" onClick={onStart} disabled={loading}>
            {loading ? "Starting…" : "Start Bot"}
          </button>
        )}
        {isLive && (
          <button className="btn-stop" onClick={onStop} disabled={loading}>
            Stop Bot
          </button>
        )}
        <button className="btn-scan" onClick={onScan} disabled={loading}>
          Scan Now
        </button>
      </div>

      {status.active_setups?.length > 0 && (
        <div style={{ marginTop: 4 }}>
          <div className="label" style={{ marginBottom: 6 }}>
            Active setups — waiting for entry
          </div>
          <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
            {status.active_setups.map((sym, i) => (
              <div
                key={i}
                style={{
                  background: "rgba(155,109,255,0.12)",
                  border: "1px solid rgba(155,109,255,0.3)",
                  borderRadius: 4,
                  padding: "3px 10px",
                  fontSize: 10,
                  color: "var(--purple)",
                  fontFamily: "var(--mono)",
                }}
              >
                {sym.replace("/USDT", "")}
              </div>
            ))}
          </div>
          <div style={{ fontSize: 10, color: "var(--muted)", marginTop: 4 }}>
            L2 entry watcher checking every 60s
          </div>
        </div>
      )}

      {status.last_scan?.length > 0 && (
        <div>
          <div className="label" style={{ marginBottom: 8 }}>
            Last scan — trades placed
          </div>
          {status.last_scan.map((t, i) => (
            <div
              key={i}
              style={{
                display: "flex",
                justifyContent: "space-between",
                padding: "6px 0",
                borderBottom: "1px solid var(--border)",
                fontSize: 11,
              }}
            >
              <span className="mono" style={{ color: "var(--info)" }}>
                {t.symbol}
              </span>
              <span className={`tag ${t.signal}`}>{t.signal}</span>
              <span className="mono">{fmt(t.entry)}</span>
              <span className="mono" style={{ color: "var(--sell)" }}>
                SL {fmt(t.sl)}
              </span>
              <span className="mono" style={{ color: "var(--buy)" }}>
                TP {fmt(t.tp)}
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}