import { useState, useCallback, useEffect, useRef } from "react";
import { Upload, CheckCircle2, AlertCircle, Loader2, CloudUpload, FileType, Zap, Eye, Globe, Link } from "lucide-react";
import api, { API_BASE } from "../../lib/api";

type Tab = "file" | "url";

export default function UploadPage() {
  const [activeTab, setActiveTab] = useState<Tab>("file");
  const [isDragging, setIsDragging] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [result, setResult] = useState<{ success: boolean; message: string; id?: number } | null>(null);
  const [progress, setProgress] = useState<{ current_slide: number; total_slides: number; message: string; status: string } | null>(null);
  const eventSourceRef = useRef<EventSource | null>(null);

  // URL tab state
  const [websiteUrl, setWebsiteUrl] = useState("");
  const [maxPages, setMaxPages] = useState(0); // 0 = all pages

  useEffect(() => {
    return () => { eventSourceRef.current?.close(); };
  }, []);

  const startProgressStream = (presId: number) => {
    eventSourceRef.current?.close();
    const es = new EventSource(`${API_BASE}/progress/${presId}`);
    eventSourceRef.current = es;
    es.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        setProgress(data);
        if (data.status === "complete") {
          es.close();
          setUploading(false);
          setResult({ success: true, message: data.message || "Processing complete!", id: presId });
          setProgress(null);
        } else if (data.status === "failed") {
          es.close();
          setUploading(false);
          setResult({ success: false, message: data.message || "Processing failed" });
          setProgress(null);
        }
      } catch { /* ignore parse errors */ }
    };
    es.onerror = () => { es.close(); };
  };

  // ── File Upload ──
  const uploadFile = useCallback(async (file: File) => {
    if (!file.name.toLowerCase().endsWith(".pptx")) {
      setResult({ success: false, message: "Only .pptx files are allowed" });
      return;
    }
    setUploading(true);
    setResult(null);
    setProgress(null);
    const formData = new FormData();
    formData.append("file", file);
    try {
      const res = await api.post("/admin/upload", formData, { headers: { "Content-Type": "multipart/form-data" } });
      startProgressStream(res.data.id);
    } catch (err: any) {
      setUploading(false);
      setResult({ success: false, message: err.response?.data?.detail || "Upload failed" });
    }
  }, []);

  const handleDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(false);
    const file = e.dataTransfer.files[0];
    if (file) uploadFile(file);
  }, [uploadFile]);

  const handleFileSelect = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) uploadFile(file);
    e.target.value = "";
  }, [uploadFile]);

  // ── URL Submit ──
  const submitUrl = useCallback(async () => {
    if (!websiteUrl.trim()) {
      setResult({ success: false, message: "Please enter a website URL" });
      return;
    }
    setUploading(true);
    setResult(null);
    setProgress(null);
    try {
      const res = await api.post("/admin/submit-url", { url: websiteUrl.trim(), max_pages: maxPages });
      startProgressStream(res.data.id);
    } catch (err: any) {
      setUploading(false);
      setResult({ success: false, message: err.response?.data?.detail || "Failed to submit URL" });
    }
  }, [websiteUrl, maxPages]);

  const pct = progress && progress.total_slides > 0
    ? Math.round((progress.current_slide / progress.total_slides) * 100)
    : 0;

  const switchTab = (tab: Tab) => {
    if (uploading) return;
    setActiveTab(tab);
    setResult(null);
    setProgress(null);
  };

  return (
    <div className="animate-fade-in">
      <div className="page-header">
        <div>
          <h1>Create Presentation</h1>
          <p>Upload a PowerPoint file or generate from a website URL</p>
        </div>
      </div>

      {/* Tab Switcher */}
      <div style={{
        display: "flex",
        gap: 0,
        marginBottom: 24,
        background: "var(--c-bg-card)",
        borderRadius: 12,
        padding: 4,
        border: "1px solid var(--c-border)",
      }}>
        <button
          onClick={() => switchTab("file")}
          disabled={uploading}
          style={{
            flex: 1,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            gap: 8,
            padding: "12px 20px",
            borderRadius: 10,
            border: "none",
            cursor: uploading ? "not-allowed" : "pointer",
            fontSize: 14,
            fontWeight: 600,
            transition: "all 0.2s ease",
            background: activeTab === "file"
              ? "linear-gradient(135deg, #6366f1, #4f46e5)"
              : "transparent",
            color: activeTab === "file" ? "#fff" : "var(--c-text-muted)",
          }}
        >
          <Upload size={16} />
          Upload File
        </button>
        <button
          onClick={() => switchTab("url")}
          disabled={uploading}
          style={{
            flex: 1,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            gap: 8,
            padding: "12px 20px",
            borderRadius: 10,
            border: "none",
            cursor: uploading ? "not-allowed" : "pointer",
            fontSize: 14,
            fontWeight: 600,
            transition: "all 0.2s ease",
            background: activeTab === "url"
              ? "linear-gradient(135deg, #6366f1, #4f46e5)"
              : "transparent",
            color: activeTab === "url" ? "#fff" : "var(--c-text-muted)",
          }}
        >
          <Globe size={16} />
          Website URL
        </button>
      </div>

      {/* ── FILE TAB ── */}
      {activeTab === "file" && (
        <div
          onDragOver={(e) => { e.preventDefault(); setIsDragging(true); }}
          onDragLeave={() => setIsDragging(false)}
          onDrop={handleDrop}
          className={`upload-zone ${isDragging ? "dragging" : ""}`}
          onClick={() => !uploading && document.getElementById("file-input")?.click()}
        >
          <input id="file-input" type="file" accept=".pptx" onChange={handleFileSelect} style={{ display: "none" }} />

          {uploading ? (
            <div className="animate-fade-in" style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 20 }}>
              <div style={{ position: "relative" }}>
                <div className="upload-icon-wrapper active">
                  <Loader2 size={40} className="animate-spin" />
                </div>
                <div style={{ position: "absolute", inset: 0, borderRadius: 24 }} className="animate-pulse-glow" />
              </div>
              {progress ? (
                <div style={{ width: "100%", maxWidth: 360 }}>
                  <p className="upload-title">Processing...</p>
                  <div className="progress-bar-track" style={{ marginTop: 16 }}>
                    <div className="progress-bar-fill" style={{ width: `${pct}%` }} />
                  </div>
                  <p className="progress-slide-text">
                    Step <strong>{progress.current_slide}</strong> of <strong>{progress.total_slides}</strong>
                  </p>
                  <p style={{ fontSize: 12, color: "var(--c-text-muted)", marginTop: 4 }}>{progress.message}</p>
                </div>
              ) : (
                <div>
                  <p className="upload-title">Uploading & Processing...</p>
                  <p className="upload-subtitle">Extracting all content from your presentation</p>
                </div>
              )}
            </div>
          ) : (
            <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 20 }}>
              <div className={`upload-icon-wrapper ${isDragging ? "active" : "idle"}`}>
                <CloudUpload size={40} />
              </div>
              <div>
                <p className="upload-title">{isDragging ? "Drop your file here!" : "Drag & drop your .pptx file"}</p>
                <p className="upload-subtitle">or click anywhere to browse your files</p>
              </div>
              <div className="upload-badge">
                <FileType size={16} />
                Supports .pptx files up to 100MB
              </div>
            </div>
          )}
        </div>
      )}

      {/* ── URL TAB ── */}
      {activeTab === "url" && (
        <div style={{
          background: "var(--c-bg-card)",
          borderRadius: 16,
          border: "1px solid var(--c-border)",
          padding: 32,
        }}>
          {uploading ? (
            <div className="animate-fade-in" style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 20, padding: "40px 0" }}>
              <div style={{ position: "relative" }}>
                <div className="upload-icon-wrapper active">
                  <Loader2 size={40} className="animate-spin" />
                </div>
                <div style={{ position: "absolute", inset: 0, borderRadius: 24 }} className="animate-pulse-glow" />
              </div>
              {progress ? (
                <div style={{ width: "100%", maxWidth: 400 }}>
                  <p className="upload-title" style={{ textAlign: "center" }}>Generating Presentation...</p>
                  <div className="progress-bar-track" style={{ marginTop: 16 }}>
                    <div className="progress-bar-fill" style={{ width: `${pct}%` }} />
                  </div>
                  <p className="progress-slide-text" style={{ textAlign: "center" }}>
                    Step <strong>{progress.current_slide}</strong> of <strong>{progress.total_slides}</strong>
                  </p>
                  <p style={{ fontSize: 12, color: "var(--c-text-muted)", marginTop: 4, textAlign: "center" }}>{progress.message}</p>
                </div>
              ) : (
                <div style={{ textAlign: "center" }}>
                  <p className="upload-title">Starting website analysis...</p>
                  <p className="upload-subtitle">Crawling pages and capturing screenshots</p>
                </div>
              )}
            </div>
          ) : (
            <>
              <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 24 }}>
                <div style={{
                  width: 44,
                  height: 44,
                  borderRadius: 12,
                  background: "linear-gradient(135deg, #6366f1, #06b6d4)",
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                  flexShrink: 0,
                }}>
                  <Globe size={22} color="#fff" />
                </div>
                <div>
                  <p style={{ fontWeight: 700, fontSize: 16, color: "var(--c-text)" }}>Website to Presentation</p>
                  <p style={{ fontSize: 13, color: "var(--c-text-muted)" }}>Enter a website URL to generate a professional showcase presentation</p>
                </div>
              </div>

              {/* URL Input */}
              <div style={{ marginBottom: 20 }}>
                <label style={{ display: "block", fontSize: 13, fontWeight: 600, color: "var(--c-text-muted)", marginBottom: 8 }}>
                  Website URL
                </label>
                <div style={{
                  display: "flex",
                  alignItems: "center",
                  gap: 0,
                  background: "var(--c-bg)",
                  borderRadius: 10,
                  border: "1px solid var(--c-border)",
                  overflow: "hidden",
                }}>
                  <div style={{
                    padding: "12px 14px",
                    background: "rgba(99,102,241,0.1)",
                    display: "flex",
                    alignItems: "center",
                    borderRight: "1px solid var(--c-border)",
                  }}>
                    <Link size={16} style={{ color: "var(--c-text-muted)" }} />
                  </div>
                  <input
                    type="url"
                    value={websiteUrl}
                    onChange={(e) => setWebsiteUrl(e.target.value)}
                    placeholder="https://example.com"
                    onKeyDown={(e) => { if (e.key === "Enter") submitUrl(); }}
                    style={{
                      flex: 1,
                      padding: "12px 16px",
                      border: "none",
                      background: "transparent",
                      color: "var(--c-text)",
                      fontSize: 14,
                      outline: "none",
                    }}
                  />
                </div>
              </div>

              {/* Max Pages */}
              <div style={{ marginBottom: 28 }}>
                <label style={{ display: "block", fontSize: 13, fontWeight: 600, color: "var(--c-text-muted)", marginBottom: 8 }}>
                  Pages to Crawl
                </label>
                <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                  {[
                    { value: 0, label: "All pages" },
                    { value: 5, label: "5 pages" },
                    { value: 10, label: "10 pages" },
                    { value: 15, label: "15 pages" },
                  ].map((opt) => (
                    <button
                      key={opt.value}
                      onClick={() => setMaxPages(opt.value)}
                      style={{
                        padding: "8px 20px",
                        borderRadius: 8,
                        border: maxPages === opt.value ? "2px solid #6366f1" : "1px solid var(--c-border)",
                        background: maxPages === opt.value ? "rgba(99,102,241,0.15)" : "var(--c-bg)",
                        color: maxPages === opt.value ? "#818cf8" : "var(--c-text-muted)",
                        fontWeight: 600,
                        fontSize: 13,
                        cursor: "pointer",
                        transition: "all 0.2s ease",
                      }}
                    >
                      {opt.label}
                    </button>
                  ))}
                </div>
                {maxPages === 0 && (
                  <p style={{ fontSize: 11, color: "var(--c-text-muted)", marginTop: 6 }}>
                    All discovered pages will be crawled (up to 50 max)
                  </p>
                )}
              </div>

              {/* Submit Button */}
              <button
                onClick={submitUrl}
                disabled={!websiteUrl.trim()}
                style={{
                  width: "100%",
                  padding: "14px 24px",
                  borderRadius: 10,
                  border: "none",
                  background: websiteUrl.trim()
                    ? "linear-gradient(135deg, #6366f1, #4f46e5)"
                    : "var(--c-bg)",
                  color: websiteUrl.trim() ? "#fff" : "var(--c-text-muted)",
                  fontSize: 15,
                  fontWeight: 700,
                  cursor: websiteUrl.trim() ? "pointer" : "not-allowed",
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                  gap: 10,
                  transition: "all 0.2s ease",
                  opacity: websiteUrl.trim() ? 1 : 0.5,
                }}
              >
                <Zap size={18} />
                Generate Presentation
              </button>
            </>
          )}
        </div>
      )}

      {/* Result */}
      {result && (
        <div className={`result-message ${result.success ? "success" : "error"}`} style={{ marginTop: 20 }}>
          <div className={`result-icon ${result.success ? "success" : "error"}`}>
            {result.success ? <CheckCircle2 size={20} /> : <AlertCircle size={20} />}
          </div>
          <div style={{ flex: 1 }}>
            <p style={{ fontWeight: 700, fontSize: 15, color: result.success ? "#065f46" : "#991b1b" }}>
              {result.success ? "Presentation Created!" : "Processing Failed"}
            </p>
            <p style={{ fontSize: 13, marginTop: 4, color: result.success ? "#047857" : "#b91c1c" }}>
              {result.message}
            </p>
          </div>
          {result.success && result.id && (
            <a
              href={`/api/v1/presentations/${result.id}/webpage`}
              target="_blank"
              rel="noopener noreferrer"
              style={{
                padding: "8px 16px",
                borderRadius: 8,
                background: "#10b981",
                color: "#fff",
                fontSize: 13,
                fontWeight: 600,
                textDecoration: "none",
                display: "flex",
                alignItems: "center",
                gap: 6,
                whiteSpace: "nowrap",
              }}
            >
              <Eye size={14} />
              View
            </a>
          )}
        </div>
      )}

      {/* How it works */}
      <div className="how-it-works">
        <h3>How it works</h3>
        <div className="how-steps stagger-children">
          {(activeTab === "file" ? [
            { icon: Upload, title: "Upload", desc: "Upload a .pptx file using the area above", color: "linear-gradient(135deg, #3b82f6, #4f46e5)" },
            { icon: Zap, title: "Extract", desc: "All content is extracted — text, images, charts, tables, shapes", color: "linear-gradient(135deg, #7c3aed, #9333ea)" },
            { icon: Eye, title: "View", desc: "Each slide is rendered as a beautiful web page", color: "linear-gradient(135deg, #10b981, #14b8a6)" },
          ] : [
            { icon: Globe, title: "Crawl", desc: "Enter a URL — we visit the site and capture all key pages", color: "linear-gradient(135deg, #3b82f6, #4f46e5)" },
            { icon: Zap, title: "Generate", desc: "AI analyzes the content and creates a professional presentation", color: "linear-gradient(135deg, #7c3aed, #9333ea)" },
            { icon: Eye, title: "Present", desc: "View your website as a stunning slide-based presentation", color: "linear-gradient(135deg, #10b981, #14b8a6)" },
          ]).map((step, i) => (
            <div key={i} className="how-step">
              <div className="how-step-icon" style={{ background: step.color }}>
                <step.icon size={18} />
              </div>
              <div>
                <p className="how-step-title">{step.title}</p>
                <p className="how-step-desc">{step.desc}</p>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
