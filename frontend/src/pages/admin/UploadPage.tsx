import { useState, useCallback, useEffect, useRef } from "react";
import {
  Upload, CheckCircle2, AlertCircle, Loader2, CloudUpload, FileType,
  Zap, Eye, Globe, Link, Image, RefreshCw, XCircle, Search, Sparkles, Coins,
  FileText, Layers,
} from "lucide-react";
import api, { API_BASE } from "../../lib/api";

type Tab = "file" | "url";

interface BackgroundTemplate {
  name: string;
  filename: string;
  url: string;
}

interface DuplicateInfo {
  exists: boolean;
  presentation_id?: number;
  title?: string;
  status?: string;
  created_at?: string;
}

interface ProgressData {
  current_slide: number;
  total_slides: number;
  message: string;
  status: string;
  phase?: string;
  token_usage?: { input_tokens: number; output_tokens: number } | null;
}

export default function UploadPage() {
  const [activeTab, setActiveTab] = useState<Tab>("file");
  const [isDragging, setIsDragging] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [result, setResult] = useState<{ success: boolean; message: string; id?: number; tokenUsage?: { input_tokens: number; output_tokens: number } | null } | null>(null);
  const [progress, setProgress] = useState<ProgressData | null>(null);
  const eventSourceRef = useRef<EventSource | null>(null);
  const currentPresIdRef = useRef<number | null>(null);

  // URL tab state
  const [websiteUrl, setWebsiteUrl] = useState("");
  const [maxPages, setMaxPages] = useState(0);
  const [selectedTemplate, setSelectedTemplate] = useState<string | null>(null);
  const [templates, setTemplates] = useState<BackgroundTemplate[]>([]);
  const [loadingTemplates, setLoadingTemplates] = useState(false);

  // Duplicate URL dialog
  const [duplicateInfo, setDuplicateInfo] = useState<DuplicateInfo | null>(null);
  const [checkingUrl, setCheckingUrl] = useState(false);

  // Cancel state
  const [cancelling, setCancelling] = useState(false);

  // Crawl mode dialog state
  const [showCrawlModeDialog, setShowCrawlModeDialog] = useState(false);
  const [detectedRoute, setDetectedRoute] = useState<string | null>(null);
  const [pendingForceRegenerate, setPendingForceRegenerate] = useState(false);

  // Load background templates when URL tab is active
  useEffect(() => {
    if (activeTab === "url" && templates.length === 0) {
      setLoadingTemplates(true);
      api.get("/admin/background-templates")
        .then((res) => setTemplates(res.data))
        .catch(() => {})
        .finally(() => setLoadingTemplates(false));
    }
  }, [activeTab]);

  useEffect(() => {
    return () => { eventSourceRef.current?.close(); };
  }, []);

  const startProgressStream = (presId: number) => {
    currentPresIdRef.current = presId;
    eventSourceRef.current?.close();
    const es = new EventSource(`${API_BASE}/progress/${presId}`);
    eventSourceRef.current = es;
    es.onmessage = (event) => {
      try {
        const data: ProgressData = JSON.parse(event.data);
        setProgress(data);
        if (data.status === "complete") {
          es.close();
          setUploading(false);
          setCancelling(false);
          currentPresIdRef.current = null;
          setResult({
            success: true,
            message: data.message || "Processing complete!",
            id: presId,
            tokenUsage: data.token_usage,
          });
          setProgress(null);
        } else if (data.status === "failed") {
          es.close();
          setUploading(false);
          setCancelling(false);
          currentPresIdRef.current = null;
          setResult({ success: false, message: data.message || "Processing failed" });
          setProgress(null);
        } else if (data.status === "cancelled") {
          es.close();
          setUploading(false);
          setCancelling(false);
          currentPresIdRef.current = null;
          setResult({ success: false, message: "Generation was cancelled." });
          setProgress(null);
        }
      } catch { /* ignore parse errors */ }
    };
    es.onerror = () => { es.close(); };
  };

  // ── Cancel generation ──
  const cancelGeneration = useCallback(async () => {
    if (!currentPresIdRef.current) return;
    setCancelling(true);
    try {
      await api.post(`/admin/cancel/${currentPresIdRef.current}`);
    } catch {
      setCancelling(false);
    }
  }, []);

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

  // ── Route detection: is this a specific page or a homepage? ──
  const isSpecificRoute = useCallback((url: string): { isRoute: boolean; path: string } => {
    try {
      let normalized = url.trim();
      if (!normalized.startsWith("http://") && !normalized.startsWith("https://")) {
        normalized = "https://" + normalized;
      }
      const parsed = new URL(normalized);
      const path = parsed.pathname.replace(/\/+$/, ""); // strip trailing slashes
      // A homepage has no path or just "/"
      // A specific route has a meaningful path like /about, /products/widget
      if (!path || path === "") {
        return { isRoute: false, path: "/" };
      }
      // Ignore paths that are just common index patterns
      const indexPatterns = ["/index", "/index.html", "/index.htm", "/home", "/default"];
      if (indexPatterns.includes(path.toLowerCase())) {
        return { isRoute: false, path };
      }
      return { isRoute: true, path };
    } catch {
      return { isRoute: false, path: "/" };
    }
  }, []);

  // ── URL Submit (with duplicate check) ──
  const doSubmitUrl = useCallback(async (forceRegenerate: boolean, crawlMode: string = "full_site") => {
    setDuplicateInfo(null);
    setShowCrawlModeDialog(false);
    setUploading(true);
    setResult(null);
    setProgress(null);
    // CRITICAL: when single_page mode, force max_pages to 1 so backend
    // only crawls the target page, regardless of the Pages-to-Crawl selector.
    const effectiveMaxPages = crawlMode === "single_page" ? 1 : maxPages;
    try {
      const res = await api.post("/admin/submit-url", {
        url: websiteUrl.trim(),
        max_pages: effectiveMaxPages,
        background_template: selectedTemplate,
        force_regenerate: forceRegenerate,
        crawl_mode: crawlMode,
      });

      if (res.data.status === "ready" && !forceRegenerate) {
        setUploading(false);
        setResult({
          success: true,
          message: "Using existing presentation (already generated for this URL).",
          id: res.data.id,
        });
        return;
      }

      startProgressStream(res.data.id);
    } catch (err: any) {
      setUploading(false);
      setResult({ success: false, message: err.response?.data?.detail || "Failed to submit URL" });
    }
  }, [websiteUrl, maxPages, selectedTemplate]);

  const submitUrl = useCallback(async () => {
    if (!websiteUrl.trim()) {
      setResult({ success: false, message: "Please enter a website URL" });
      return;
    }

    setCheckingUrl(true);
    setResult(null);
    setDuplicateInfo(null);
    setShowCrawlModeDialog(false);
    try {
      const res = await api.post("/admin/check-url", { url: websiteUrl.trim() });
      if (res.data.exists) {
        setDuplicateInfo(res.data);
        setCheckingUrl(false);
        return;
      }
    } catch (err: any) {
      if (err.response?.data?.detail) {
        setCheckingUrl(false);
        setResult({ success: false, message: err.response.data.detail });
        return;
      }
    }
    setCheckingUrl(false);

    // Check if this is a specific route — ask the user what they want
    const routeCheck = isSpecificRoute(websiteUrl);
    if (routeCheck.isRoute) {
      setDetectedRoute(routeCheck.path);
      setShowCrawlModeDialog(true);
      return;
    }

    // Homepage — crawl full site by default
    doSubmitUrl(false, "full_site");
  }, [websiteUrl, doSubmitUrl, isSpecificRoute]);

  const pct = progress && progress.total_slides > 0
    ? Math.round((progress.current_slide / progress.total_slides) * 100)
    : 0;

  const switchTab = (tab: Tab) => {
    if (uploading) return;
    setActiveTab(tab);
    setResult(null);
    setProgress(null);
    setDuplicateInfo(null);
    setShowCrawlModeDialog(false);
    setDetectedRoute(null);
    setPendingForceRegenerate(false);
  };

  // ── Phase-specific display helpers ──
  const getPhaseInfo = (phase?: string) => {
    switch (phase) {
      case "crawling":
        return {
          icon: <Search size={20} style={{ color: "#60a5fa" }} />,
          label: "Crawling Website",
          color: "#3b82f6",
          bgColor: "rgba(59,130,246,0.1)",
        };
      case "crawl_done":
        return {
          icon: <CheckCircle2 size={20} style={{ color: "#10b981" }} />,
          label: "Crawling Complete",
          color: "#10b981",
          bgColor: "rgba(16,185,129,0.1)",
        };
      case "generating":
      case "webpage":
        return {
          icon: <Sparkles size={20} style={{ color: "#a78bfa" }} />,
          label: "AI Generating Presentation",
          color: "#8b5cf6",
          bgColor: "rgba(139,92,246,0.1)",
        };
      default:
        return {
          icon: <Loader2 size={20} className="animate-spin" style={{ color: "#6366f1" }} />,
          label: "Processing",
          color: "#6366f1",
          bgColor: "rgba(99,102,241,0.1)",
        };
    }
  };

  // ── Render progress section (shared between file & url tabs) ──
  const renderProgress = () => {
    if (!progress) {
      return (
        <div style={{ textAlign: "center" }}>
          <p className="upload-title">
            {activeTab === "url" ? "Validating website..." : "Uploading & Processing..."}
          </p>
          <p className="upload-subtitle">
            {activeTab === "url" ? "Checking domain and preparing to crawl" : "Extracting all content from your presentation"}
          </p>
        </div>
      );
    }

    const phaseInfo = getPhaseInfo(progress.phase);
    const isGenerating = progress.phase === "generating" || progress.phase === "webpage";

    return (
      <div style={{ width: "100%", maxWidth: 420 }}>
        {/* Phase indicator */}
        <div style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          gap: 10,
          marginBottom: 16,
          padding: "10px 16px",
          borderRadius: 10,
          background: phaseInfo.bgColor,
        }}>
          {phaseInfo.icon}
          <span style={{ fontWeight: 700, fontSize: 14, color: phaseInfo.color }}>
            {phaseInfo.label}
          </span>
        </div>

        {/* Progress bar */}
        <div className="progress-bar-track" style={{ marginTop: 8 }}>
          <div
            className="progress-bar-fill"
            style={{
              width: isGenerating ? "100%" : `${pct}%`,
              background: isGenerating
                ? "linear-gradient(90deg, #6366f1, #8b5cf6, #a78bfa, #8b5cf6, #6366f1)"
                : undefined,
              backgroundSize: isGenerating ? "200% 100%" : undefined,
              animation: isGenerating ? "shimmer 2s ease-in-out infinite" : undefined,
            }}
          />
        </div>

        {/* Step counter — hide "of Y" during crawling since total is unknown */}
        {!isGenerating && (
          <p className="progress-slide-text" style={{ textAlign: "center" }}>
            {progress.phase === "crawling" ? (
              <>Page <strong>{progress.current_slide}</strong> crawled</>
            ) : (
              <>Step <strong>{progress.current_slide}</strong> of <strong>{progress.total_slides}</strong></>
            )}
          </p>
        )}

        {/* Status message */}
        <p style={{ fontSize: 12, color: "var(--c-text-muted)", marginTop: 8, textAlign: "center" }}>
          {progress.message}
        </p>

        {/* Cancel button */}
        <button
          onClick={cancelGeneration}
          disabled={cancelling}
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            gap: 6,
            margin: "16px auto 0",
            padding: "8px 20px",
            borderRadius: 8,
            border: "1px solid rgba(239,68,68,0.3)",
            background: cancelling ? "rgba(239,68,68,0.1)" : "transparent",
            color: "#ef4444",
            fontSize: 13,
            fontWeight: 600,
            cursor: cancelling ? "not-allowed" : "pointer",
            transition: "all 0.2s ease",
          }}
        >
          <XCircle size={14} />
          {cancelling ? "Cancelling..." : "Cancel Generation"}
        </button>
      </div>
    );
  };

  return (
    <div className="animate-fade-in">
      {/* Shimmer animation for generating phase */}
      <style>{`
        @keyframes shimmer {
          0% { background-position: 200% 0; }
          100% { background-position: -200% 0; }
        }
      `}</style>

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
              {renderProgress()}
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
              {renderProgress()}
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
                    onChange={(e) => {
                      setWebsiteUrl(e.target.value);
                      setDuplicateInfo(null);
                    }}
                    placeholder="https://example.com"
                    onKeyDown={(e) => { if (e.key === "Enter" && !checkingUrl) submitUrl(); }}
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

              {/* Duplicate URL Dialog */}
              {duplicateInfo && duplicateInfo.exists && (
                <div style={{
                  marginBottom: 20,
                  padding: 20,
                  borderRadius: 12,
                  background: "linear-gradient(135deg, rgba(99,102,241,0.1), rgba(6,182,212,0.1))",
                  border: "1px solid rgba(99,102,241,0.3)",
                }}>
                  <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 12 }}>
                    <AlertCircle size={20} style={{ color: "#818cf8" }} />
                    <p style={{ fontWeight: 700, fontSize: 14, color: "var(--c-text)" }}>
                      Presentation Already Exists
                    </p>
                  </div>
                  <p style={{ fontSize: 13, color: "var(--c-text-muted)", marginBottom: 4 }}>
                    A presentation for this URL has already been generated:
                  </p>
                  <p style={{ fontSize: 13, color: "var(--c-text)", fontWeight: 600, marginBottom: 16 }}>
                    "{duplicateInfo.title}"
                    {duplicateInfo.created_at && (
                      <span style={{ fontWeight: 400, color: "var(--c-text-muted)", marginLeft: 8 }}>
                        ({new Date(duplicateInfo.created_at).toLocaleDateString()})
                      </span>
                    )}
                  </p>
                  <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
                    <button
                      onClick={() => {
                        setDuplicateInfo(null);
                        setResult({
                          success: true,
                          message: "Using existing presentation.",
                          id: duplicateInfo.presentation_id,
                        });
                      }}
                      style={{
                        padding: "10px 20px",
                        borderRadius: 8,
                        border: "none",
                        background: "#10b981",
                        color: "#fff",
                        fontSize: 13,
                        fontWeight: 600,
                        cursor: "pointer",
                        display: "flex",
                        alignItems: "center",
                        gap: 6,
                      }}
                    >
                      <Eye size={14} />
                      Use Existing
                    </button>
                    <button
                      onClick={async () => {
                        const presId = duplicateInfo.presentation_id!;
                        setDuplicateInfo(null);
                        setUploading(true);
                        setResult(null);
                        setProgress(null);
                        try {
                          await api.post(`/admin/regenerate/${presId}`, {
                            crawl_mode: "full_site",
                            max_pages: maxPages,
                            background_template: selectedTemplate,
                          });
                          startProgressStream(presId);
                        } catch (err: any) {
                          setUploading(false);
                          setResult({
                            success: false,
                            message: err.response?.data?.detail || "Regeneration failed",
                          });
                        }
                      }}
                      style={{
                        padding: "10px 20px",
                        borderRadius: 8,
                        border: "1px solid rgba(99,102,241,0.3)",
                        background: "rgba(99,102,241,0.15)",
                        color: "#818cf8",
                        fontSize: 13,
                        fontWeight: 600,
                        cursor: "pointer",
                        display: "flex",
                        alignItems: "center",
                        gap: 6,
                      }}
                    >
                      <RefreshCw size={14} />
                      Regenerate
                    </button>
                  </div>
                </div>
              )}

              {/* Crawl Mode Dialog — shown when specific route detected */}
              {showCrawlModeDialog && detectedRoute && (
                <div style={{
                  marginBottom: 20,
                  padding: 20,
                  borderRadius: 12,
                  background: "linear-gradient(135deg, rgba(168,85,247,0.1), rgba(59,130,246,0.1))",
                  border: "1px solid rgba(168,85,247,0.3)",
                }}>
                  <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 12 }}>
                    <AlertCircle size={20} style={{ color: "#a78bfa" }} />
                    <p style={{ fontWeight: 700, fontSize: 14, color: "var(--c-text)" }}>
                      Specific Page Detected
                    </p>
                  </div>
                  <p style={{ fontSize: 13, color: "var(--c-text-muted)", marginBottom: 4 }}>
                    You've entered a URL with a specific route:
                  </p>
                  <p style={{
                    fontSize: 13,
                    color: "var(--c-text)",
                    fontWeight: 600,
                    marginBottom: 6,
                    padding: "6px 10px",
                    background: "rgba(255,255,255,0.05)",
                    borderRadius: 6,
                    fontFamily: "monospace",
                    wordBreak: "break-all",
                  }}>
                    {websiteUrl.trim()}
                  </p>
                  <p style={{ fontSize: 13, color: "var(--c-text-muted)", marginBottom: 16 }}>
                    Would you like to create a presentation from <strong>this page only</strong>, or crawl <strong>all pages</strong> of the entire website?
                  </p>
                  <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
                    <button
                      onClick={() => { doSubmitUrl(pendingForceRegenerate, "single_page"); setPendingForceRegenerate(false); }}
                      style={{
                        padding: "10px 20px",
                        borderRadius: 8,
                        border: "none",
                        background: "linear-gradient(135deg, #8b5cf6, #7c3aed)",
                        color: "#fff",
                        fontSize: 13,
                        fontWeight: 600,
                        cursor: "pointer",
                        display: "flex",
                        alignItems: "center",
                        gap: 6,
                      }}
                    >
                      <FileText size={14} />
                      This Page Only
                    </button>
                    <button
                      onClick={() => { doSubmitUrl(pendingForceRegenerate, "full_site"); setPendingForceRegenerate(false); }}
                      style={{
                        padding: "10px 20px",
                        borderRadius: 8,
                        border: "1px solid rgba(59,130,246,0.3)",
                        background: "rgba(59,130,246,0.15)",
                        color: "#60a5fa",
                        fontSize: 13,
                        fontWeight: 600,
                        cursor: "pointer",
                        display: "flex",
                        alignItems: "center",
                        gap: 6,
                      }}
                    >
                      <Layers size={14} />
                      Entire Website
                    </button>
                  </div>
                </div>
              )}

              {/* Max Pages — only show when crawl mode dialog is NOT active (i.e. homepage URLs) */}
              {!showCrawlModeDialog && (
              <div style={{ marginBottom: 20 }}>
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
              )}

              {/* Background Template Selector */}
              <div style={{ marginBottom: 28 }}>
                <label style={{ display: "block", fontSize: 13, fontWeight: 600, color: "var(--c-text-muted)", marginBottom: 8 }}>
                  <span style={{ display: "flex", alignItems: "center", gap: 6 }}>
                    <Image size={14} />
                    Background Template
                  </span>
                </label>
                {loadingTemplates ? (
                  <div style={{ display: "flex", alignItems: "center", gap: 8, padding: "12px 0" }}>
                    <Loader2 size={16} className="animate-spin" style={{ color: "var(--c-text-muted)" }} />
                    <span style={{ fontSize: 13, color: "var(--c-text-muted)" }}>Loading templates...</span>
                  </div>
                ) : (
                  <div style={{ display: "flex", gap: 12, flexWrap: "wrap" }}>
                    {/* Default (no template) */}
                    <button
                      onClick={() => setSelectedTemplate(null)}
                      style={{
                        width: 100,
                        height: 64,
                        borderRadius: 10,
                        border: selectedTemplate === null ? "2px solid #6366f1" : "1px solid var(--c-border)",
                        background: selectedTemplate === null
                          ? "linear-gradient(135deg, rgba(99,102,241,0.2), rgba(6,182,212,0.2))"
                          : "linear-gradient(135deg, #0f172a, #1e293b)",
                        cursor: "pointer",
                        display: "flex",
                        flexDirection: "column",
                        alignItems: "center",
                        justifyContent: "center",
                        gap: 4,
                        transition: "all 0.2s ease",
                        position: "relative",
                        overflow: "hidden",
                      }}
                    >
                      <span style={{
                        fontSize: 11,
                        fontWeight: 600,
                        color: selectedTemplate === null ? "#818cf8" : "var(--c-text-muted)",
                      }}>
                        Default
                      </span>
                    </button>
                    {templates.map((tpl) => (
                      <button
                        key={tpl.filename}
                        onClick={() => setSelectedTemplate(tpl.filename)}
                        title={tpl.name}
                        style={{
                          width: 100,
                          height: 64,
                          borderRadius: 10,
                          border: selectedTemplate === tpl.filename ? "2px solid #6366f1" : "1px solid var(--c-border)",
                          cursor: "pointer",
                          padding: 0,
                          overflow: "hidden",
                          transition: "all 0.2s ease",
                          position: "relative",
                          background: "var(--c-bg)",
                          opacity: selectedTemplate === tpl.filename ? 1 : 0.7,
                        }}
                      >
                        <img
                          src={tpl.url}
                          alt={tpl.name}
                          style={{
                            width: "100%",
                            height: "100%",
                            objectFit: "cover",
                          }}
                        />
                        {selectedTemplate === tpl.filename && (
                          <div style={{
                            position: "absolute",
                            inset: 0,
                            background: "rgba(99,102,241,0.15)",
                            display: "flex",
                            alignItems: "center",
                            justifyContent: "center",
                          }}>
                            <CheckCircle2 size={20} style={{ color: "#818cf8" }} />
                          </div>
                        )}
                      </button>
                    ))}
                  </div>
                )}
                <p style={{ fontSize: 11, color: "var(--c-text-muted)", marginTop: 6 }}>
                  Choose a background style for your presentation slides
                </p>
              </div>

              {/* Submit Button — hidden when crawl mode dialog is active (user should pick from dialog) */}
              {!showCrawlModeDialog && (
              <button
                onClick={submitUrl}
                disabled={!websiteUrl.trim() || checkingUrl}
                style={{
                  width: "100%",
                  padding: "14px 24px",
                  borderRadius: 10,
                  border: "none",
                  background: websiteUrl.trim() && !checkingUrl
                    ? "linear-gradient(135deg, #6366f1, #4f46e5)"
                    : "var(--c-bg)",
                  color: websiteUrl.trim() && !checkingUrl ? "#fff" : "var(--c-text-muted)",
                  fontSize: 15,
                  fontWeight: 700,
                  cursor: websiteUrl.trim() && !checkingUrl ? "pointer" : "not-allowed",
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                  gap: 10,
                  transition: "all 0.2s ease",
                  opacity: websiteUrl.trim() && !checkingUrl ? 1 : 0.5,
                }}
              >
                {checkingUrl ? (
                  <>
                    <Loader2 size={18} className="animate-spin" />
                    Checking URL...
                  </>
                ) : (
                  <>
                    <Zap size={18} />
                    Generate Presentation
                  </>
                )}
              </button>
              )}
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
            {/* Token usage display */}
            {result.success && result.tokenUsage && (
              <div style={{
                display: "flex",
                alignItems: "center",
                gap: 6,
                marginTop: 8,
                padding: "6px 12px",
                borderRadius: 8,
                background: "rgba(16,185,129,0.08)",
                border: "1px solid rgba(16,185,129,0.2)",
                width: "fit-content",
              }}>
                <Coins size={14} style={{ color: "#10b981" }} />
                <span style={{ fontSize: 12, color: "#047857", fontWeight: 500 }}>
                  {(result.tokenUsage.input_tokens + result.tokenUsage.output_tokens).toLocaleString()} tokens used
                  <span style={{ color: "#6b7280", fontWeight: 400 }}>
                    {" "}({result.tokenUsage.input_tokens.toLocaleString()} in + {result.tokenUsage.output_tokens.toLocaleString()} out)
                  </span>
                </span>
              </div>
            )}
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