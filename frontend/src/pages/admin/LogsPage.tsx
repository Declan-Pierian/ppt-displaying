import { useState, useEffect, useCallback } from "react";
import { Loader2, FileText, Filter, CheckCircle, Clock, AlertCircle, Activity, HardDrive, Timer } from "lucide-react";
import api from "../../lib/api";
import { formatDate, formatFileSize } from "../../lib/slideUtils";
import type { UploadLog } from "../../types/slide";

const STATUS_STYLES: Record<string, { bg: string; color: string; Icon: typeof CheckCircle }> = {
  success: { bg: "#d1fae5", color: "#10b981", Icon: CheckCircle },
  processing: { bg: "#eef2ff", color: "#4f46e5", Icon: Clock },
  failed: { bg: "#fee2e2", color: "#ef4444", Icon: AlertCircle },
};

export default function LogsPage() {
  const [logs, setLogs] = useState<UploadLog[]>([]);
  const [loading, setLoading] = useState(true);
  const [statusFilter, setStatusFilter] = useState("");

  const refresh = useCallback(async () => {
    setLoading(true);
    try { const res = await api.get("/admin/logs", { params: statusFilter ? { status: statusFilter } : {} }); setLogs(res.data); }
    catch (err) { console.error(err); }
    finally { setLoading(false); }
  }, [statusFilter]);

  useEffect(() => { refresh(); }, [refresh]);

  const totalSize = logs.reduce((acc, l) => acc + (l.file_size_bytes || 0), 0);
  const avgMs = logs.filter(l => l.processing_time_ms).reduce((acc, l, _, arr) => acc + (l.processing_time_ms || 0) / arr.length, 0);

  return (
    <div className="animate-fade-in">
      <div className="page-header">
        <div>
          <h1>Upload Logs</h1>
          <p>History of all upload attempts</p>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8, padding: "10px 16px", borderRadius: 12, border: "1px solid var(--c-border)", background: "white" }}>
            <Filter size={14} style={{ color: "var(--c-text-muted)" }} />
            <select value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)}
              style={{ fontSize: 13, color: "var(--c-text-secondary)", background: "transparent", border: "none", outline: "none", cursor: "pointer" }}>
              <option value="">All Status</option>
              <option value="success">Success</option>
              <option value="failed">Failed</option>
              <option value="processing">Processing</option>
            </select>
          </div>
        </div>
      </div>

      {!loading && logs.length > 0 && (
        <div className="stat-grid">
          <div className="stat-card">
            <div className="stat-icon primary"><Activity size={20} /></div>
            <div><div className="stat-value">{logs.length}</div><div className="stat-label">Total Uploads</div></div>
          </div>
          <div className="stat-card">
            <div className="stat-icon accent"><HardDrive size={20} /></div>
            <div><div className="stat-value">{formatFileSize(totalSize)}</div><div className="stat-label">Total Size</div></div>
          </div>
          <div className="stat-card">
            <div className="stat-icon success"><Timer size={20} /></div>
            <div><div className="stat-value">{avgMs ? `${(avgMs / 1000).toFixed(1)}s` : "—"}</div><div className="stat-label">Avg Processing</div></div>
          </div>
        </div>
      )}

      {loading ? (
        <div className="loading-center animate-fade-in">
          <div className="loading-spinner">
            <div className="loading-icon-wrapper"><div className="loading-icon-glow" /><div className="loading-icon"><Loader2 size={28} className="animate-spin" /></div></div>
            <p className="loading-text">Loading logs...</p>
          </div>
        </div>
      ) : logs.length === 0 ? (
        <div className="empty-state animate-fade-in-up">
          <div className="empty-icon"><FileText size={36} /></div>
          <h3 className="empty-title">No upload logs found</h3>
          <p className="empty-desc">Upload activity will appear here</p>
        </div>
      ) : (
        <div className="animate-fade-in-up">
          <table className="data-table">
            <thead>
              <tr>
                <th>File</th>
                <th>Size</th>
                <th>Status</th>
                <th>Processing</th>
                <th>Date</th>
              </tr>
            </thead>
            <tbody>
              {logs.map((log) => {
                const st = STATUS_STYLES[log.status] || STATUS_STYLES.processing;
                return (
                  <tr key={log.id}>
                    <td>
                      <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                        <div style={{ width: 32, height: 32, borderRadius: 8, background: "#f1f5f9", display: "flex", alignItems: "center", justifyContent: "center", flexShrink: 0 }}>
                          <FileText size={14} style={{ color: "var(--c-text-muted)" }} />
                        </div>
                        <span style={{ fontSize: 13, fontWeight: 500, color: "var(--c-text)", maxWidth: 200, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                          {log.original_filename}
                        </span>
                      </div>
                    </td>
                    <td style={{ fontSize: 13, fontWeight: 500, color: "var(--c-text-secondary)" }}>{formatFileSize(log.file_size_bytes)}</td>
                    <td>
                      <span className="badge" style={{ background: st.bg, color: st.color }}><st.Icon size={12} /> {log.status}</span>
                    </td>
                    <td style={{ fontSize: 13, color: "var(--c-text-muted)", fontWeight: 500 }}>
                      {log.processing_time_ms ? `${(log.processing_time_ms / 1000).toFixed(1)}s` : "—"}
                    </td>
                    <td style={{ fontSize: 13, color: "var(--c-text-muted)" }}>{formatDate(log.created_at)}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
