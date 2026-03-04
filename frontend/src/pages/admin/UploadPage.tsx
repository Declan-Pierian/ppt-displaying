import { useState, useCallback, useEffect, useRef } from "react";
import { Upload, CheckCircle2, AlertCircle, Loader2, CloudUpload, FileType, Zap, Eye } from "lucide-react";
import api, { API_BASE } from "../../lib/api";

export default function UploadPage() {
  const [isDragging, setIsDragging] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [result, setResult] = useState<{ success: boolean; message: string; id?: number } | null>(null);
  const [progress, setProgress] = useState<{ current_slide: number; total_slides: number; message: string; status: string } | null>(null);
  const eventSourceRef = useRef<EventSource | null>(null);

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
          setResult({ success: true, message: data.message || "Upload complete!", id: presId });
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

  const pct = progress && progress.total_slides > 0
    ? Math.round((progress.current_slide / progress.total_slides) * 100)
    : 0;

  return (
    <div className="animate-fade-in">
      <div className="page-header">
        <div>
          <h1>Upload Presentation</h1>
          <p>Upload a PowerPoint file to make it viewable as a beautiful web page</p>
        </div>
      </div>

      {/* Upload Zone */}
      <div
        onDragOver={(e) => { e.preventDefault(); setIsDragging(true); }}
        onDragLeave={() => setIsDragging(false)}
        onDrop={handleDrop}
        className={`upload-zone ${isDragging ? "dragging" : ""}`}
        onClick={() => document.getElementById("file-input")?.click()}
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
                <p className="upload-title">Extracting Slides...</p>
                <div className="progress-bar-track" style={{ marginTop: 16 }}>
                  <div className="progress-bar-fill" style={{ width: `${pct}%` }} />
                </div>
                <p className="progress-slide-text">
                  Slide <strong>{progress.current_slide}</strong> of <strong>{progress.total_slides}</strong>
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

      {/* Result */}
      {result && (
        <div className={`result-message ${result.success ? "success" : "error"}`}>
          <div className={`result-icon ${result.success ? "success" : "error"}`}>
            {result.success ? <CheckCircle2 size={20} /> : <AlertCircle size={20} />}
          </div>
          <div>
            <p style={{ fontWeight: 700, fontSize: 15, color: result.success ? "#065f46" : "#991b1b" }}>
              {result.success ? "Upload Successful!" : "Upload Failed"}
            </p>
            <p style={{ fontSize: 13, marginTop: 4, color: result.success ? "#047857" : "#b91c1c" }}>
              {result.message}
            </p>
          </div>
        </div>
      )}

      {/* How it works */}
      <div className="how-it-works">
        <h3>How it works</h3>
        <div className="how-steps stagger-children">
          {[
            { icon: Upload, title: "Upload", desc: "Upload a .pptx file using the area above", color: "linear-gradient(135deg, #3b82f6, #4f46e5)" },
            { icon: Zap, title: "Extract", desc: "All content is extracted — text, images, charts, tables, shapes", color: "linear-gradient(135deg, #7c3aed, #9333ea)" },
            { icon: Eye, title: "View", desc: "Each slide is rendered as a beautiful web page", color: "linear-gradient(135deg, #10b981, #14b8a6)" },
          ].map((step, i) => (
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
