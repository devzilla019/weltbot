import { useState, useEffect } from "react";
import { api } from "../api";

export default function ApiKeyModal({ onClose, showToast }) {
  const [apiKey,    setApiKey]    = useState("");
  const [apiSecret, setApiSecret] = useState("");
  const [status,    setStatus]    = useState(null);
  const [saving,    setSaving]    = useState(false);
  const [showSecret, setShowSecret] = useState(false);

  useEffect(() => {
    api.getApiKeyStatus().then(setStatus).catch(() => {});
  }, []);

  const handleSave = async () => {
    if (!apiKey.trim() || !apiSecret.trim()) {
      showToast("Both API key and secret are required", "error");
      return;
    }
    setSaving(true);
    try {
      const r = await api.updateApiKeys(apiKey.trim(), apiSecret.trim());
      if (r.success) {
        showToast("API keys updated successfully", "success");
        setApiKey(""); setApiSecret("");
        const s = await api.getApiKeyStatus();
        setStatus(s);
      } else {
        showToast(r.error || "Update failed", "error");
      }
    } catch {
      showToast("Failed to update keys", "error");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal" onClick={e => e.stopPropagation()}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 20 }}>
          <div>
            <div style={{ fontFamily: "var(--display)", fontSize: 18, fontWeight: 700 }}>API Settings</div>
            <div style={{ fontSize: 11, color: "var(--muted)", marginTop: 2 }}>
              Connect your Binance account
            </div>
          </div>
          <button onClick={onClose} style={{ background: "none", color: "var(--muted)", fontSize: 18, padding: "4px 8px" }}>✕</button>
        </div>

        {status && (
          <div style={{
            padding: "10px 14px", borderRadius: 8, marginBottom: 16,
            background: status.configured ? "rgba(0,229,160,0.08)" : "rgba(255,77,109,0.08)",
            border: `1px solid ${status.configured ? "rgba(0,229,160,0.2)" : "rgba(255,77,109,0.2)"}`,
            fontSize: 11,
            color: status.configured ? "var(--buy)" : "var(--sell)",
          }}>
            {status.configured
              ? `✓ Connected — Key: ${status.key_preview}`
              : "✗ No API keys configured"}
          </div>
        )}

        <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
          <div>
            <div className="label" style={{ marginBottom: 6 }}>API Key</div>
            <input
              type="text"
              value={apiKey}
              onChange={e => setApiKey(e.target.value)}
              placeholder="Enter your Binance API key"
              style={{
                width: "100%", padding: "10px 12px", borderRadius: 8,
                background: "var(--surface)", border: "1px solid var(--border2)",
                color: "var(--text)", fontFamily: "var(--mono)", fontSize: 12,
                outline: "none",
              }}
            />
          </div>

          <div>
            <div className="label" style={{ marginBottom: 6 }}>API Secret</div>
            <div style={{ position: "relative" }}>
              <input
                type={showSecret ? "text" : "password"}
                value={apiSecret}
                onChange={e => setApiSecret(e.target.value)}
                placeholder="Enter your Binance secret key"
                style={{
                  width: "100%", padding: "10px 36px 10px 12px", borderRadius: 8,
                  background: "var(--surface)", border: "1px solid var(--border2)",
                  color: "var(--text)", fontFamily: "var(--mono)", fontSize: 12,
                  outline: "none",
                }}
              />
              <button
                onClick={() => setShowSecret(!showSecret)}
                style={{
                  position: "absolute", right: 10, top: "50%", transform: "translateY(-50%)",
                  background: "none", color: "var(--muted)", padding: "2px 4px", fontSize: 12,
                }}
              >
                {showSecret ? "○" : "●"}
              </button>
            </div>
          </div>

          <div style={{
            padding: "10px 12px", borderRadius: 8,
            background: "rgba(77,159,255,0.06)", border: "1px solid rgba(77,159,255,0.15)",
            fontSize: 11, color: "var(--muted)", lineHeight: 1.6,
          }}>
            ⚠ Keys are stored in memory only. They reset on server restart.
            For Binance demo trading use keys from <span style={{ color: "var(--info)" }}>demo-fapi.binance.com</span>
          </div>

          <div style={{ display: "flex", gap: 8, marginTop: 4 }}>
            <button onClick={onClose} className="btn-settings" style={{ flex: 1 }}>Cancel</button>
            <button onClick={handleSave} disabled={saving} className="btn-start" style={{ flex: 2 }}>
              {saving ? "Saving…" : "Save API Keys"}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}