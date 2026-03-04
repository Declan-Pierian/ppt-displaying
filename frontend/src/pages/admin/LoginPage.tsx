import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "../../hooks/useAuth";
import { Presentation, LogIn, ArrowRight } from "lucide-react";

export default function LoginPage() {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const { login, loading, error } = useAuth();
  const navigate = useNavigate();

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    const success = await login(username, password);
    if (success) navigate("/admin");
  };

  return (
    <div className="login-page">
      <div className="login-blob top-right" />
      <div className="login-blob bottom-left" />

      <div style={{ width: "100%", maxWidth: 420, position: "relative", zIndex: 10 }} className="animate-fade-in-up">
        <div style={{ textAlign: "center", marginBottom: 32 }}>
          <div className="login-logo-icon">
            <Presentation size={32} />
          </div>
          <h1 style={{ fontSize: 28, fontWeight: 800, color: "var(--c-text)", letterSpacing: "-0.02em" }}>PPT Viewer</h1>
          <p style={{ color: "var(--c-text-muted)", marginTop: 6, fontWeight: 500, fontSize: 14 }}>Admin Panel</p>
        </div>

        <div className="login-card">
          <h2 className="login-title">Sign in to your account</h2>
          {error && <div className="error-alert animate-fade-in">{error}</div>}

          <form onSubmit={handleSubmit} style={{ display: "flex", flexDirection: "column", gap: 20 }}>
            <div>
              <label className="form-label">Username</label>
              <input type="text" value={username} onChange={(e) => setUsername(e.target.value)} className="form-input" placeholder="Enter username" required />
            </div>
            <div>
              <label className="form-label">Password</label>
              <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} className="form-input" placeholder="Enter password" required />
            </div>
            <button type="submit" disabled={loading} className="btn btn-primary" style={{ width: "100%", padding: "14px", marginTop: 4, fontSize: 15, opacity: loading ? 0.6 : 1 }}>
              {loading ? (
                <div style={{ width: 20, height: 20, border: "2px solid rgba(255,255,255,0.3)", borderTopColor: "white", borderRadius: "50%" }} className="animate-spin" />
              ) : (
                <><LogIn size={18} /> Sign In</>
              )}
            </button>
          </form>
        </div>

        <div style={{ textAlign: "center", marginTop: 28 }}>
          <a href="/" style={{ display: "inline-flex", alignItems: "center", gap: 6, fontSize: 13, fontWeight: 500, color: "#94a3b8" }}>
            Go to Viewer <ArrowRight size={14} />
          </a>
        </div>
      </div>
    </div>
  );
}
