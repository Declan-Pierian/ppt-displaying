import { useState, useRef, useEffect } from "react";
import {
  Send, Loader2, Undo2, ChevronDown, ChevronRight,
  Sparkles, User, Bot, Coins, Clock,
} from "lucide-react";
import type { ChatMessage, EditHistoryData } from "../../types/slide";

interface ChatEditPanelProps {
  messages: ChatMessage[];
  loading: boolean;
  editHistory: EditHistoryData;
  totalSlides: number;
  onSendEdit: (prompt: string, slideNumbers?: number[]) => Promise<boolean>;
  onUndo: () => Promise<boolean>;
  onRefreshIframe: () => void;
}

export default function ChatEditPanel({
  messages,
  loading,
  editHistory,
  totalSlides,
  onSendEdit,
  onUndo,
  onRefreshIframe,
}: ChatEditPanelProps) {
  const [prompt, setPrompt] = useState("");
  const [slideScope, setSlideScope] = useState<"all" | "specific">("all");
  const [selectedSlide, setSelectedSlide] = useState(1);
  const [showHistory, setShowHistory] = useState(false);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  const handleSend = async () => {
    if (!prompt.trim() || loading) return;
    const slideNumbers =
      slideScope === "specific" ? [selectedSlide] : undefined;
    const text = prompt;
    setPrompt("");
    const success = await onSendEdit(text, slideNumbers);
    if (success) {
      onRefreshIframe();
    }
  };

  const handleUndo = async () => {
    if (loading) return;
    const success = await onUndo();
    if (success) {
      onRefreshIframe();
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%", overflow: "hidden" }}>
      {/* Header bar */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          padding: "10px 16px",
          borderBottom: "1px solid var(--c-border)",
          flexShrink: 0,
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
          <Sparkles size={14} style={{ color: "var(--c-primary)" }} />
          <span style={{ fontSize: 13, fontWeight: 600 }}>AI Editor</span>
        </div>
        <div style={{ display: "flex", gap: 4 }}>
          <button
            onClick={handleUndo}
            disabled={loading || editHistory.current_version <= 0}
            title="Undo last edit"
            style={{
              display: "flex",
              alignItems: "center",
              gap: 4,
              padding: "4px 10px",
              fontSize: 12,
              background: "var(--c-surface-dim)",
              border: "1px solid var(--c-border)",
              borderRadius: 6,
              color: "var(--c-text-secondary)",
              cursor:
                editHistory.current_version > 0 && !loading
                  ? "pointer"
                  : "not-allowed",
              opacity: editHistory.current_version > 0 && !loading ? 1 : 0.5,
            }}
          >
            <Undo2 size={12} />
            Undo
          </button>
        </div>
      </div>

      {/* Messages area */}
      <div style={{ flex: 1, overflow: "auto", padding: "12px 16px" }}>
        {messages.length === 0 && (
          <div
            style={{
              textAlign: "center",
              padding: "40px 16px",
              color: "var(--c-text-muted)",
            }}
          >
            <Sparkles
              size={28}
              style={{ margin: "0 auto 12px", color: "var(--c-primary)", opacity: 0.5 }}
            />
            <div style={{ fontSize: 13, fontWeight: 500, marginBottom: 6 }}>
              AI Presentation Editor
            </div>
            <div style={{ fontSize: 12, lineHeight: 1.5 }}>
              Type a prompt to edit your presentation. For example:
              <br />
              <em>"Change the title on slide 1 to 'Our Services'"</em>
              <br />
              <em>"Make all headings blue"</em>
              <br />
              <em>"Add a bullet point about security to slide 3"</em>
            </div>
          </div>
        )}

        {messages.map((msg) => (
          <div
            key={msg.id}
            style={{
              display: "flex",
              gap: 8,
              marginBottom: 12,
              flexDirection: msg.role === "user" ? "row-reverse" : "row",
            }}
          >
            <div
              style={{
                width: 26,
                height: 26,
                borderRadius: "50%",
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                flexShrink: 0,
                background:
                  msg.role === "user"
                    ? "var(--c-primary)"
                    : msg.success === false
                      ? "var(--c-error-light)"
                      : "var(--c-success-light)",
                color:
                  msg.role === "user"
                    ? "#fff"
                    : msg.success === false
                      ? "var(--c-error)"
                      : "var(--c-success)",
              }}
            >
              {msg.role === "user" ? (
                <User size={13} />
              ) : (
                <Bot size={13} />
              )}
            </div>
            <div
              style={{
                maxWidth: "80%",
                padding: "8px 12px",
                borderRadius: 10,
                fontSize: 12,
                lineHeight: 1.5,
                background:
                  msg.role === "user"
                    ? "var(--c-primary-light)"
                    : msg.success === false
                      ? "var(--c-error-light)"
                      : "var(--c-surface-dim)",
                color:
                  msg.success === false
                    ? "var(--c-error)"
                    : "var(--c-text)",
                border: `1px solid ${msg.success === false ? "var(--c-error)" : "var(--c-border)"}`,
              }}
            >
              {msg.content}
              {msg.slideNumbers && (
                <div
                  style={{
                    fontSize: 10,
                    color: "var(--c-text-muted)",
                    marginTop: 4,
                  }}
                >
                  Slide{msg.slideNumbers.length > 1 ? "s" : ""}{" "}
                  {msg.slideNumbers.join(", ")}
                </div>
              )}
              {msg.tokenUsage && (
                <div
                  style={{
                    display: "flex",
                    alignItems: "center",
                    gap: 4,
                    fontSize: 10,
                    color: "var(--c-text-muted)",
                    marginTop: 4,
                  }}
                >
                  <Coins size={10} />
                  {msg.tokenUsage.input_tokens.toLocaleString()} in +{" "}
                  {msg.tokenUsage.output_tokens.toLocaleString()} out
                </div>
              )}
            </div>
          </div>
        ))}

        {loading && (
          <div
            style={{
              display: "flex",
              alignItems: "center",
              gap: 8,
              padding: "8px 12px",
              fontSize: 12,
              color: "var(--c-text-muted)",
            }}
          >
            <Loader2 size={14} className="animate-spin" />
            AI is editing...
          </div>
        )}

        <div ref={messagesEndRef} />
      </div>

      {/* Edit history (collapsible) */}
      {editHistory.versions.length > 0 && (
        <div style={{ borderTop: "1px solid var(--c-border)", flexShrink: 0 }}>
          <button
            onClick={() => setShowHistory(!showHistory)}
            style={{
              display: "flex",
              alignItems: "center",
              gap: 6,
              width: "100%",
              padding: "8px 16px",
              background: "none",
              border: "none",
              fontSize: 11,
              fontWeight: 600,
              color: "var(--c-text-muted)",
              cursor: "pointer",
            }}
          >
            {showHistory ? (
              <ChevronDown size={12} />
            ) : (
              <ChevronRight size={12} />
            )}
            <Clock size={12} />
            Edit History ({editHistory.versions.length})
            {editHistory.current_version > 0 && (
              <span style={{ marginLeft: "auto", fontSize: 10 }}>
                v{editHistory.current_version}
              </span>
            )}
          </button>
          {showHistory && (
            <div
              style={{
                maxHeight: 120,
                overflow: "auto",
                padding: "0 16px 8px",
              }}
            >
              {[...editHistory.versions].reverse().map((v) => (
                <div
                  key={v.version}
                  style={{
                    fontSize: 11,
                    color: "var(--c-text-secondary)",
                    padding: "4px 0",
                    borderBottom: "1px solid var(--c-border)",
                    opacity:
                      v.version <= editHistory.current_version ? 1 : 0.4,
                  }}
                >
                  <div style={{ display: "flex", justifyContent: "space-between" }}>
                    <span style={{ fontWeight: 500 }}>
                      v{v.version}
                    </span>
                    <span style={{ fontSize: 10, color: "var(--c-text-muted)" }}>
                      {v.slides_affected.length > 0 &&
                        `Slide${v.slides_affected.length > 1 ? "s" : ""} ${v.slides_affected.join(", ")}`}
                    </span>
                  </div>
                  {v.prompt && (
                    <div
                      style={{
                        fontSize: 10,
                        color: "var(--c-text-muted)",
                        whiteSpace: "nowrap",
                        overflow: "hidden",
                        textOverflow: "ellipsis",
                      }}
                    >
                      {v.prompt}
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* Input area */}
      <div
        style={{
          borderTop: "1px solid var(--c-border)",
          padding: "12px 16px",
          flexShrink: 0,
        }}
      >
        {/* Slide scope selector */}
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: 8,
            marginBottom: 8,
          }}
        >
          <span style={{ fontSize: 11, color: "var(--c-text-muted)" }}>
            Apply to:
          </span>
          <select
            value={slideScope}
            onChange={(e) =>
              setSlideScope(e.target.value as "all" | "specific")
            }
            style={{
              fontSize: 11,
              padding: "3px 8px",
              border: "1px solid var(--c-border)",
              borderRadius: 4,
              background: "var(--c-surface)",
              color: "var(--c-text)",
              cursor: "pointer",
            }}
          >
            <option value="all">All slides (AI decides)</option>
            <option value="specific">Specific slide</option>
          </select>
          {slideScope === "specific" && (
            <select
              value={selectedSlide}
              onChange={(e) => setSelectedSlide(Number(e.target.value))}
              style={{
                fontSize: 11,
                padding: "3px 8px",
                border: "1px solid var(--c-border)",
                borderRadius: 4,
                background: "var(--c-surface)",
                color: "var(--c-text)",
                cursor: "pointer",
              }}
            >
              {Array.from({ length: totalSlides || 20 }, (_, i) => (
                <option key={i + 1} value={i + 1}>
                  Slide {i + 1}
                </option>
              ))}
            </select>
          )}
        </div>

        {/* Prompt input */}
        <div style={{ display: "flex", gap: 8 }}>
          <textarea
            ref={inputRef}
            value={prompt}
            onChange={(e) => setPrompt(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Describe your edit..."
            rows={2}
            disabled={loading}
            style={{
              flex: 1,
              resize: "none",
              padding: "8px 12px",
              fontSize: 12,
              lineHeight: 1.5,
              border: "1px solid var(--c-border)",
              borderRadius: 8,
              background: "var(--c-surface)",
              color: "var(--c-text)",
              outline: "none",
              fontFamily: "inherit",
            }}
          />
          <button
            onClick={handleSend}
            disabled={!prompt.trim() || loading}
            style={{
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              width: 36,
              height: 36,
              borderRadius: 8,
              border: "none",
              background:
                prompt.trim() && !loading
                  ? "var(--c-primary)"
                  : "var(--c-border)",
              color: "#fff",
              cursor:
                prompt.trim() && !loading ? "pointer" : "not-allowed",
              flexShrink: 0,
              alignSelf: "flex-end",
            }}
          >
            {loading ? (
              <Loader2 size={16} className="animate-spin" />
            ) : (
              <Send size={16} />
            )}
          </button>
        </div>
      </div>
    </div>
  );
}
