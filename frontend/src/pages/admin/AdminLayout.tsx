import { Outlet, NavLink, useNavigate } from "react-router-dom";
import { useEffect } from "react";
import { Upload, FileSliders, FileText, LogOut, Presentation, ExternalLink } from "lucide-react";
import { useAuth } from "../../hooks/useAuth";

export default function AdminLayout() {
  const { isAuthenticated, user, logout } = useAuth();
  const navigate = useNavigate();

  useEffect(() => {
    if (!isAuthenticated) {
      navigate("/admin/login");
    }
  }, [isAuthenticated, navigate]);

  if (!isAuthenticated) return null;

  const handleLogout = () => {
    logout();
    navigate("/admin/login");
  };

  const navItems = [
    { to: "/admin/upload", label: "Upload", icon: Upload },
    { to: "/admin/presentations", label: "Presentations", icon: FileSliders },
    { to: "/admin/logs", label: "Logs", icon: FileText },
  ];

  return (
    <div style={{ minHeight: "100vh", display: "flex", background: "linear-gradient(135deg, #f8fafc 0%, #f1f5f9 50%, #eef2ff 100%)" }}>
      <aside className="admin-sidebar">
        <div className="admin-sidebar-logo">
          <div className="admin-sidebar-logo-icon">
            <Presentation size={20} />
          </div>
          <div>
            <h1>PPT Viewer</h1>
            <p>Admin Panel</p>
          </div>
        </div>

        <nav className="admin-nav">
          {navItems.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              className={({ isActive }) => `admin-nav-item ${isActive ? "active" : ""}`}
            >
              <item.icon size={18} />
              {item.label}
            </NavLink>
          ))}
        </nav>

        <div className="admin-sidebar-footer">
          <div className="admin-sidebar-user">
            <div>
              <p>{user?.username}</p>
              <p>{user?.role}</p>
            </div>
            <button onClick={handleLogout} className="btn-icon danger" title="Logout">
              <LogOut size={16} />
            </button>
          </div>
          <a href="/" style={{ display: "flex", alignItems: "center", justifyContent: "center", gap: 6, padding: "8px 16px", marginTop: 12, fontSize: 12, fontWeight: 500, color: "#94a3b8", borderRadius: 8, transition: "all 0.2s" }}>
            <ExternalLink size={12} />
            View public page
          </a>
        </div>
      </aside>

      <main className="admin-content">
        <div className="admin-content-inner">
          <Outlet />
        </div>
      </main>
    </div>
  );
}
