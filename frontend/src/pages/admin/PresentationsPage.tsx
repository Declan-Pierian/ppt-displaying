import { useState, useEffect, useCallback } from "react";
import { Link } from "react-router-dom";
import { Eye, EyeOff, Trash2, ExternalLink, Loader2, RefreshCw, FileSliders, Layers, CheckCircle, Clock, AlertCircle, Globe, FileType, PenLine } from "lucide-react";
import api from "../../lib/api";
import { formatDate } from "../../lib/slideUtils";
import type { PresentationAdminMeta } from "../../types/slide";

const STATUS_STYLES: Record<string, { bg: string; color: string; Icon: typeof CheckCircle }> = {
  ready: { bg: "#d1fae5", color: "#10b981", Icon: CheckCircle },
  processing: { bg: "#eef2ff", color: "#4f46e5", Icon: Clock },
  failed: { bg: "#fee2e2", color: "#ef4444", Icon: AlertCircle },
};

export default function PresentationsPage() {
  const [presentations, setPresentations] = useState<PresentationAdminMeta[]>([]);
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    setLoading(true);
    try { const res = await api.get("/admin/presentations"); setPresentations(res.data); }
    catch (err) { console.error(err); }
    finally { setLoading(false); }
  }, []);

  useEffect(() => { refresh(); }, [refresh]);

  const toggleActive = async (id: number, isActive: boolean) => {
    try { await api.patch(`/admin/presentations/${id}`, { is_active: !isActive }); refresh(); }
    catch (err) { console.error(err); }
  };

  const deletePres = async (id: number) => {
    if (!confirm("Delete this presentation?")) return;
    try { await api.delete(`/admin/presentations/${id}`); refresh(); }
    catch (err) { console.error(err); }
  };

  const visible = presentations.filter(p => p.is_active).length;
  const hidden = presentations.filter(p => !p.is_active).length;

  return (
    <div className="animate-fade-in">
      <div className="page-header">
        <div>
          <h1>Presentations</h1>
          <p>Manage all uploaded presentations</p>
        </div>
        <button onClick={refresh} className="btn btn-secondary">
          <RefreshCw size={16} className={loading ? "animate-spin" : ""} />
          Refresh
        </button>
      </div>

      {!loading && presentations.length > 0 && (
        <div className="stat-grid">
          <div className="stat-card">
            <div className="stat-icon primary"><Layers size={20} /></div>
            <div><div className="stat-value">{presentations.length}</div><div className="stat-label">Total</div></div>
          </div>
          <div className="stat-card">
            <div className="stat-icon success"><Eye size={20} /></div>
            <div><div className="stat-value">{visible}</div><div className="stat-label">Visible</div></div>
          </div>
          <div className="stat-card">
            <div className="stat-icon accent"><EyeOff size={20} /></div>
            <div><div className="stat-value">{hidden}</div><div className="stat-label">Hidden</div></div>
          </div>
        </div>
      )}

      {loading ? (
        <div className="loading-center animate-fade-in">
          <div className="loading-spinner">
            <div className="loading-icon-wrapper">
              <div className="loading-icon-glow" />
              <div className="loading-icon"><Loader2 size={28} className="animate-spin" /></div>
            </div>
            <p className="loading-text">Loading presentations...</p>
          </div>
        </div>
      ) : presentations.length === 0 ? (
        <div className="empty-state animate-fade-in-up">
          <div className="empty-icon"><FileSliders size={36} /></div>
          <h3 className="empty-title">No presentations yet</h3>
          <p className="empty-desc">Upload your first presentation to get started</p>
        </div>
      ) : (
        <div className="stagger-children" style={{ display: "flex", flexDirection: "column", gap: 12 }}>
          {presentations.map((pres) => {
            const st = STATUS_STYLES[pres.status] || STATUS_STYLES.processing;
            return (
              <div key={pres.id} className="pres-item">
                <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", gap: 16 }}>
                  <div style={{ minWidth: 0, flex: 1 }}>
                    <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 6 }}>
                      <span className="pres-title">{pres.title}</span>
                      <span className="badge" style={{ background: st.bg, color: st.color }}>
                        <st.Icon size={12} /> {pres.status}
                      </span>
                      {!pres.is_active && <span className="badge-neutral badge">Hidden</span>}
                    </div>
                    <p className="pres-meta" style={{ display: "flex", alignItems: "center", gap: 6 }}>
                      {pres.source_url ? (
                        <Globe size={13} style={{ flexShrink: 0, color: "#06b6d4" }} />
                      ) : (
                        <FileType size={13} style={{ flexShrink: 0, color: "#6366f1" }} />
                      )}
                      {pres.source_url || pres.original_filename} &middot; {pres.slide_count} {pres.source_url ? "pages" : "slides"} &middot; {formatDate(pres.created_at)}
                    </p>
                    {pres.error_message && (
                      <p style={{ display: "flex", alignItems: "center", gap: 6, marginTop: 8, fontSize: 13, color: "var(--c-error)" }}>
                        <AlertCircle size={14} /> {pres.error_message}
                      </p>
                    )}
                  </div>
                  <div style={{ display: "flex", alignItems: "center", gap: 4, flexShrink: 0 }}>
                    {pres.status === "ready" && (
                      <>
                        <Link to={`/admin/presentations/${pres.id}/view`} className="btn-icon" title="View & Edit" style={{ color: "var(--c-primary)" }}><PenLine size={18} /></Link>
                        <a href={`/api/v1/presentations/${pres.id}/webpage`} target="_blank" rel="noopener noreferrer" className="btn-icon" title="View Full Screen"><ExternalLink size={18} /></a>
                      </>
                    )}
                    <button onClick={() => toggleActive(pres.id, pres.is_active)} className={`btn-icon`} title={pres.is_active ? "Hide" : "Show"}>
                      {pres.is_active ? <EyeOff size={18} /> : <Eye size={18} />}
                    </button>
                    <button onClick={() => deletePres(pres.id)} className="btn-icon danger" title="Delete"><Trash2 size={18} /></button>
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
