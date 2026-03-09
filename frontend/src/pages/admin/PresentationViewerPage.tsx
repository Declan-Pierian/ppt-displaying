import { useState, useEffect, useRef, useCallback } from "react";
import { useParams, useNavigate } from "react-router-dom";
import {
  ArrowLeft, BookOpen, MessageSquare, PanelRightClose, PanelRightOpen,
  Loader2, RefreshCw,
} from "lucide-react";
import api, { API_BASE } from "../../lib/api";
import { useSlideSync } from "../../hooks/useSlideSync";
import { useChatEdit } from "../../hooks/useChatEdit";
import ReferencesPanel from "../../components/admin/ReferencesPanel";
import ChatEditPanel from "../../components/admin/ChatEditPanel";

type SidebarTab = "references" | "chat";

export default function PresentationViewerPage() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const presentationId = Number(id);

  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [activeTab, setActiveTab] = useState<SidebarTab>("references");
  const [title, setTitle] = useState("Presentation");
  const [loadingMeta, setLoadingMeta] = useState(true);
  const [sourceUrl, setSourceUrl] = useState<string | null>(null);
  const [regenerating, setRegenerating] = useState(false);
  const [regenMessage, setRegenMessage] = useState<string | null>(null);
  const regenEsRef = useRef<EventSource | null>(null);

  const { currentSlideIndex, totalSlides, iframeRef, refreshIframe } =
    useSlideSync();
  const { messages, loading, sendEdit, undo, editHistory, fetchHistory } =
    useChatEdit(presentationId);

  // Auth check
  useEffect(() => {
    const token = localStorage.getItem("token");
    if (!token) {
      navigate("/admin/login");
    }
  }, [navigate]);

  // Load presentation metadata
  useEffect(() => {
    async function loadMeta() {
      try {
        const res = await api.get("/admin/presentations");
        const pres = res.data.find(
          (p: { id: number }) => p.id === presentationId
        );
        if (pres) {
          setTitle(pres.title);
          setSourceUrl(pres.source_url || null);
        }
      } catch {
        // Ignore — title just won't update
      } finally {
        setLoadingMeta(false);
      }
    }
    loadMeta();
    fetchHistory();
  }, [presentationId, fetchHistory]);

  // Cleanup SSE on unmount
  useEffect(() => {
    return () => { regenEsRef.current?.close(); };
  }, []);

  const handleRegenerate = useCallback(async () => {
    if (regenerating) return;
    const confirmed = confirm(
      "Regenerate this presentation?\n\n" +
      "This will re-crawl the source website and regenerate slides if the content has changed.\n" +
      "Note: Any CSS changes from AI chat edits will be preserved in the template, " +
      "but slide content will be regenerated from the new crawl data."
    );
    if (!confirmed) return;

    setRegenerating(true);
    setRegenMessage("Starting regeneration...");

    try {
      await api.post(`/admin/regenerate/${presentationId}`, {
        crawl_mode: "full_site",
        max_pages: 0,
      });

      // Start SSE progress stream
      regenEsRef.current?.close();
      const es = new EventSource(`${API_BASE}/progress/${presentationId}`);
      regenEsRef.current = es;

      es.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data);
          setRegenMessage(data.message || "Processing...");

          if (data.status === "complete") {
            es.close();
            setRegenerating(false);
            setRegenMessage(null);
            refreshIframe();
          } else if (data.status === "failed" || data.status === "cancelled") {
            es.close();
            setRegenerating(false);
            setRegenMessage(null);
            alert(data.status === "failed"
              ? `Regeneration failed: ${data.message}`
              : "Regeneration was cancelled.");
          }
        } catch { /* ignore parse errors */ }
      };
      es.onerror = () => {
        es.close();
        setRegenerating(false);
        setRegenMessage(null);
      };
    } catch (err: unknown) {
      setRegenerating(false);
      setRegenMessage(null);
      const msg = err instanceof Error ? err.message : "Failed to start regeneration";
      alert(msg);
    }
  }, [presentationId, regenerating, refreshIframe]);

  if (!id || isNaN(presentationId)) {
    return (
      <div style={{ padding: 40, textAlign: "center" }}>
        Invalid presentation ID
      </div>
    );
  }

  const token = localStorage.getItem("token") || "";
  const iframeSrc = `${API_BASE}/admin/presentations/${presentationId}/admin-webpage?token=${encodeURIComponent(token)}`;

  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        height: "100vh",
        overflow: "hidden",
        background: "var(--c-surface-dim)",
      }}
    >
      {/* Top bar */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          padding: "8px 16px",
          background: "var(--c-surface)",
          borderBottom: "1px solid var(--c-border)",
          flexShrink: 0,
          height: 48,
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
          <button
            onClick={() => navigate("/admin/presentations")}
            style={{
              display: "flex",
              alignItems: "center",
              gap: 6,
              padding: "6px 12px",
              fontSize: 13,
              background: "none",
              border: "1px solid var(--c-border)",
              borderRadius: 6,
              color: "var(--c-text-secondary)",
              cursor: "pointer",
            }}
          >
            <ArrowLeft size={14} />
            Back
          </button>
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            {loadingMeta ? (
              <Loader2 size={14} className="animate-spin" />
            ) : (
              <span
                style={{
                  fontSize: 14,
                  fontWeight: 600,
                  color: "var(--c-text)",
                  maxWidth: 400,
                  overflow: "hidden",
                  textOverflow: "ellipsis",
                  whiteSpace: "nowrap",
                }}
              >
                {title}
              </span>
            )}
            <span
              style={{
                fontSize: 11,
                color: "var(--c-text-muted)",
                background: "var(--c-surface-dim)",
                padding: "2px 8px",
                borderRadius: 10,
              }}
            >
              Slide {currentSlideIndex + 1}
              {totalSlides > 0 && ` / ${totalSlides}`}
            </span>
          </div>
        </div>

        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          {/* Regeneration progress banner */}
          {regenerating && regenMessage && (
            <span
              style={{
                fontSize: 11,
                color: "var(--c-primary)",
                background: "var(--c-primary-light)",
                padding: "3px 10px",
                borderRadius: 10,
                display: "flex",
                alignItems: "center",
                gap: 5,
                maxWidth: 280,
                overflow: "hidden",
                textOverflow: "ellipsis",
                whiteSpace: "nowrap",
              }}
            >
              <Loader2 size={12} className="animate-spin" />
              {regenMessage}
            </span>
          )}

          {/* Regenerate button — only for website presentations */}
          {sourceUrl && (
            <button
              onClick={handleRegenerate}
              disabled={regenerating}
              title="Re-crawl website and regenerate if content changed"
              style={{
                display: "flex",
                alignItems: "center",
                gap: 6,
                padding: "6px 12px",
                fontSize: 12,
                background: regenerating
                  ? "var(--c-surface-dim)"
                  : "var(--c-surface-dim)",
                border: "1px solid var(--c-border)",
                borderRadius: 6,
                color: regenerating
                  ? "var(--c-text-muted)"
                  : "var(--c-text-secondary)",
                cursor: regenerating ? "not-allowed" : "pointer",
                opacity: regenerating ? 0.7 : 1,
              }}
            >
              <RefreshCw
                size={14}
                className={regenerating ? "animate-spin" : ""}
              />
              Regenerate
            </button>
          )}

          <button
            onClick={() => setSidebarOpen(!sidebarOpen)}
            title={sidebarOpen ? "Close sidebar" : "Open sidebar"}
            style={{
              display: "flex",
              alignItems: "center",
              gap: 6,
              padding: "6px 12px",
              fontSize: 12,
              background: sidebarOpen
                ? "var(--c-primary-light)"
                : "var(--c-surface-dim)",
              border: "1px solid var(--c-border)",
              borderRadius: 6,
              color: sidebarOpen
                ? "var(--c-primary)"
                : "var(--c-text-secondary)",
              cursor: "pointer",
            }}
          >
            {sidebarOpen ? (
              <PanelRightClose size={14} />
            ) : (
              <PanelRightOpen size={14} />
            )}
            {sidebarOpen ? "Close Panel" : "Open Panel"}
          </button>
        </div>
      </div>

      {/* Main content area */}
      <div style={{ display: "flex", flex: 1, overflow: "hidden" }}>
        {/* Iframe area */}
        <div
          style={{
            flex: 1,
            position: "relative",
            background: "#0f172a",
          }}
        >
          <iframe
            ref={iframeRef}
            src={iframeSrc}
            title="Presentation Viewer"
            style={{
              width: "100%",
              height: "100%",
              border: "none",
              display: "block",
            }}
          />
        </div>

        {/* Sidebar */}
        {sidebarOpen && (
          <div
            style={{
              width: 360,
              flexShrink: 0,
              display: "flex",
              flexDirection: "column",
              background: "var(--c-surface)",
              borderLeft: "1px solid var(--c-border)",
              overflow: "hidden",
            }}
          >
            {/* Tab bar */}
            <div
              style={{
                display: "flex",
                borderBottom: "1px solid var(--c-border)",
                flexShrink: 0,
              }}
            >
              <TabButton
                active={activeTab === "references"}
                onClick={() => setActiveTab("references")}
                icon={<BookOpen size={14} />}
                label="References"
              />
              <TabButton
                active={activeTab === "chat"}
                onClick={() => setActiveTab("chat")}
                icon={<MessageSquare size={14} />}
                label="AI Editor"
                badge={loading}
              />
            </div>

            {/* Tab content */}
            <div style={{ flex: 1, overflow: "hidden" }}>
              {activeTab === "references" ? (
                <ReferencesPanel
                  presentationId={presentationId}
                  currentSlideIndex={currentSlideIndex}
                  totalSlides={totalSlides}
                />
              ) : (
                <ChatEditPanel
                  messages={messages}
                  loading={loading}
                  editHistory={editHistory}
                  totalSlides={totalSlides}
                  onSendEdit={sendEdit}
                  onUndo={undo}
                  onRefreshIframe={refreshIframe}
                />
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

function TabButton({
  active,
  onClick,
  icon,
  label,
  badge,
}: {
  active: boolean;
  onClick: () => void;
  icon: React.ReactNode;
  label: string;
  badge?: boolean;
}) {
  return (
    <button
      onClick={onClick}
      style={{
        flex: 1,
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        gap: 6,
        padding: "10px 12px",
        fontSize: 12,
        fontWeight: active ? 600 : 400,
        background: active ? "var(--c-surface)" : "var(--c-surface-dim)",
        border: "none",
        borderBottom: active
          ? "2px solid var(--c-primary)"
          : "2px solid transparent",
        color: active ? "var(--c-primary)" : "var(--c-text-secondary)",
        cursor: "pointer",
        transition: "all 0.15s ease",
        position: "relative",
      }}
    >
      {icon}
      {label}
      {badge && (
        <span
          style={{
            width: 6,
            height: 6,
            borderRadius: "50%",
            background: "var(--c-primary)",
            position: "absolute",
            top: 8,
            right: "calc(50% - 30px)",
          }}
        />
      )}
    </button>
  );
}
