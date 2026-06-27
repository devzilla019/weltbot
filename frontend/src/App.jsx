import { useState, useEffect, createContext, useContext } from "react";
import AuthPage    from "./pages/AuthPage";
import Dashboard   from "./pages/Dashboard";
import { AppCtx }  from "./context/AppContext";

export default function App() {
  const [user,  setUser]  = useState(() => {
    try { return JSON.parse(localStorage.getItem("wb_user") || "null"); }
    catch { return null; }
  });
  const [theme, setTheme] = useState(() =>
    localStorage.getItem("wb_theme") || "dark"
  );
  const [toast, setToast] = useState(null);

  useEffect(() => {
    document.documentElement.setAttribute("data-theme", theme);
    localStorage.setItem("wb_theme", theme);
  }, [theme]);

  const showToast = (msg, type = "info", duration = 4000) => {
    setToast({ msg, type, id: Date.now() });
    setTimeout(() => setToast(null), duration);
  };

  const logout = () => {
    localStorage.removeItem("wb_user");
    setUser(null);
    showToast("Logged out successfully");
  };

  return (
    <AppCtx.Provider value={{ user, setUser, theme, setTheme, showToast, logout }}>
      <div className="app-root">
        {!user ? (
          <AuthPage />
        ) : (
          <Dashboard />
        )}

        {toast && (
          <div className={`toast toast-${toast.type}`} key={toast.id}>
            <span className="toast-icon">
              {toast.type === "success" ? "✓" :
               toast.type === "error"   ? "✕" :
               toast.type === "warn"    ? "⚠" : "ℹ"}
            </span>
            {toast.msg}
          </div>
        )}
      </div>
    </AppCtx.Provider>
  );
}

