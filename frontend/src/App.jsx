import { useState, useEffect } from "react";
import AuthPage   from "./pages/AuthPage";
import Dashboard  from "./pages/Dashboard";
import { AppCtx } from "./context/AppContext";

export default function App() {
  const [user,  setUser]  = useState(null);
  const [token, setToken] = useState(null);
  const [theme, setTheme] = useState(() => localStorage.getItem("wb_theme") || "dark");
  const [toast, setToast] = useState(null);
  const [booting, setBooting] = useState(true);

  // Restore session from localStorage
  useEffect(() => {
    const t = localStorage.getItem("wb_token");
    const u = localStorage.getItem("wb_user");
    if (t && u) {
      try {
        setToken(t);
        setUser(JSON.parse(u));
      } catch { clearSession(); }
    }
    setBooting(false);
  }, []);

  useEffect(() => {
    document.documentElement.setAttribute("data-theme", theme);
    localStorage.setItem("wb_theme", theme);
  }, [theme]);

  const setSession = (tok, usr) => {
    localStorage.setItem("wb_token", tok);
    localStorage.setItem("wb_user",  JSON.stringify(usr));
    setToken(tok);
    setUser(usr);
  };

  const clearSession = () => {
    localStorage.removeItem("wb_token");
    localStorage.removeItem("wb_user");
    setToken(null);
    setUser(null);
  };

  const showToast = (msg, type = "info", duration = 4000) => {
    setToast({ msg, type, id: Date.now() });
    setTimeout(() => setToast(null), duration);
  };

  const logout = () => {
    clearSession();
    showToast("Logged out");
  };

  if (booting) return (
    <div style={{ minHeight:"100vh", display:"flex", alignItems:"center", justifyContent:"center", background:"var(--bg)" }}>
      <div style={{ fontFamily:"var(--font-display)", fontSize:32, fontWeight:800 }}>
        <span style={{ color:"var(--info)" }}>WELT</span>BOT
      </div>
    </div>
  );

  return (
    <AppCtx.Provider value={{ user, setUser, token, setSession, clearSession, theme, setTheme, showToast, logout }}>
      <div className="app-root">
        {!user || !token ? <AuthPage /> : <Dashboard />}
        {toast && (
          <div className={`toast toast-${toast.type}`} key={toast.id}>
            <span className="toast-icon">
              {toast.type==="success"?"✓":toast.type==="error"?"✕":toast.type==="warn"?"⚠":"ℹ"}
            </span>
            {toast.msg}
          </div>
        )}
      </div>
    </AppCtx.Provider>
  );
}

