import { Link } from "react-router-dom";
import { Presentation, ArrowRight, Loader2, Layers, Sparkles, Eye } from "lucide-react";
import { usePresentationList } from "../../hooks/usePresentation";
import { formatDate } from "../../lib/slideUtils";

const CARD_COLORS = [
  "rgba(79,70,229,0.06)",
  "rgba(59,130,246,0.06)",
  "rgba(124,58,237,0.06)",
  "rgba(16,185,129,0.06)",
  "rgba(245,158,11,0.06)",
  "rgba(244,63,94,0.06)",
];

export default function HomePage() {
  const { presentations, loading, error } = usePresentationList();

  return (
    <div className="home-page">
      {/* Decorative blobs */}
      <div style={{ position: "fixed", top: -200, right: -200, width: 500, height: 500, background: "rgba(79,70,229,0.04)", borderRadius: "50%", filter: "blur(80px)", pointerEvents: "none" }} />
      <div style={{ position: "fixed", bottom: -200, left: -200, width: 500, height: 500, background: "rgba(124,58,237,0.04)", borderRadius: "50%", filter: "blur(80px)", pointerEvents: "none" }} />

      <header className="home-header">
        <div className="home-header-inner">
          <div className="home-logo animate-fade-in">
            <div className="home-logo-icon"><Presentation size={20} /></div>
            <div>
              <h1 style={{ fontSize: 16, fontWeight: 700, color: "var(--c-text)" }}>PPT Viewer</h1>
              <p style={{ fontSize: 11, color: "var(--c-text-muted)" }}>Interactive Presentations</p>
            </div>
          </div>
          <Link to="/admin/login" className="btn btn-secondary" style={{ padding: "8px 16px", fontSize: 13 }}>Admin</Link>
        </div>
      </header>

      <section className="home-hero">
        <div style={{ maxWidth: 640, margin: "0 auto" }} className="animate-fade-in-up">
          <div className="home-hero-badge"><Sparkles size={14} /> Beautifully rendered presentations</div>
          <h2>View Presentations<br /><span className="gradient-text">Right in Your Browser</span></h2>
          <p>Browse through professionally rendered slides with full content fidelity — text, images, charts, tables, and more.</p>
        </div>
      </section>

      <section style={{ maxWidth: "72rem", margin: "0 auto", padding: "0 24px 96px" }}>
        {loading ? (
          <div className="loading-center animate-fade-in">
            <div className="loading-spinner">
              <div className="loading-icon-wrapper"><div className="loading-icon-glow" /><div className="loading-icon"><Loader2 size={28} className="animate-spin" /></div></div>
              <p className="loading-text">Loading presentations...</p>
            </div>
          </div>
        ) : error ? (
          <div style={{ textAlign: "center", padding: "80px 0", color: "var(--c-error)" }}>{error}</div>
        ) : presentations.length === 0 ? (
          <div className="empty-state animate-fade-in-up" style={{ paddingTop: 96, paddingBottom: 96 }}>
            <div className="empty-icon" style={{ width: 96, height: 96, borderRadius: 24 }}><Layers size={40} /></div>
            <h3 className="empty-title" style={{ fontSize: 22 }}>No presentations yet</h3>
            <p className="empty-desc" style={{ fontSize: 16 }}>Check back later for new content</p>
          </div>
        ) : (
          <div className="pres-grid stagger-children">
            {presentations.map((pres, idx) => (
              <a key={pres.id} href={`/api/v1/presentations/${pres.id}/webpage`} className="pres-card">
                <div className="pres-card-preview" style={{ background: CARD_COLORS[idx % CARD_COLORS.length] }}>
                  <Presentation size={56} style={{ color: "rgba(79,70,229,0.1)", transition: "transform 0.5s" }} />
                  <div style={{ position: "absolute", top: 12, right: 12, background: "rgba(255,255,255,0.85)", backdropFilter: "blur(8px)", padding: "6px 12px", borderRadius: 8, fontSize: 12, fontWeight: 600, color: "var(--c-text-secondary)", display: "flex", alignItems: "center", gap: 6, boxShadow: "0 1px 3px rgba(0,0,0,0.06)" }}>
                    <Layers size={12} /> {pres.slide_count} slides
                  </div>
                  <div style={{ position: "absolute", inset: 0, background: "linear-gradient(to top, rgba(79,70,229,0.08), transparent)", opacity: 0, transition: "opacity 0.3s", display: "flex", alignItems: "flex-end", justifyContent: "center", paddingBottom: 16 }} className="pres-card-overlay">
                    <span style={{ padding: "8px 16px", background: "rgba(255,255,255,0.9)", borderRadius: 8, fontSize: 13, fontWeight: 600, color: "var(--c-primary)", display: "flex", alignItems: "center", gap: 8, boxShadow: "0 4px 12px rgba(0,0,0,0.1)" }}>
                      <Eye size={15} /> View Web Page
                    </span>
                  </div>
                </div>
                <div className="pres-card-body">
                  <h3>{pres.title}</h3>
                  <p className="date">{formatDate(pres.created_at)}</p>
                  <div className="pres-card-cta"><span>Open Web Page</span> <ArrowRight size={15} /></div>
                </div>
              </a>
            ))}
          </div>
        )}
      </section>
    </div>
  );
}
