import { useState, useEffect } from "react";
import {
  Globe, FileType, ExternalLink, Loader2, AlertCircle, BookOpen,
} from "lucide-react";
import api from "../../lib/api";
import type { ReferencesData, SlideReference } from "../../types/slide";

interface ReferencesPanelProps {
  presentationId: number;
  currentSlideIndex: number;
  totalSlides: number;
}

export default function ReferencesPanel({
  presentationId,
  currentSlideIndex,
  totalSlides,
}: ReferencesPanelProps) {
  const [data, setData] = useState<ReferencesData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    async function fetchRefs() {
      setLoading(true);
      setError(null);
      try {
        const res = await api.get(
          `/admin/presentations/${presentationId}/references`
        );
        if (!cancelled) setData(res.data);
      } catch {
        if (!cancelled) setError("Failed to load references");
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    fetchRefs();
    return () => { cancelled = true; };
  }, [presentationId]);

  if (loading) {
    return (
      <div style={{ display: "flex", alignItems: "center", justifyContent: "center", padding: 40, color: "var(--c-text-muted)" }}>
        <Loader2 size={20} className="animate-spin" />
        <span style={{ marginLeft: 8 }}>Loading...</span>
      </div>
    );
  }

  if (error || !data) {
    return (
      <div style={{ padding: 20, color: "var(--c-error)", display: "flex", alignItems: "center", gap: 8 }}>
        <AlertCircle size={16} />
        {error || "No data available"}
      </div>
    );
  }

  // Find the source page for the current slide
  const sourceSlide: SlideReference | null =
    data.slides.length > 0
      ? data.slides[Math.min(currentSlideIndex, data.slides.length - 1)]
      : null;

  const content = sourceSlide?.content;

  // Gather all content into a simple list of text items
  const contentItems: string[] = [];
  if (content?.sections) {
    for (const sec of content.sections) {
      if (sec.heading) contentItems.push(sec.heading);
      if (sec.content) {
        for (const text of sec.content) {
          if (text.trim()) contentItems.push(text);
        }
      }
    }
  }
  if (content?.key_paragraphs) {
    for (const p of content.key_paragraphs) {
      if (p.trim() && !contentItems.includes(p)) contentItems.push(p);
    }
  }
  if (content?.cards) {
    for (const c of content.cards) {
      if (c.trim() && !contentItems.includes(c)) contentItems.push(c);
    }
  }
  if (content?.list_items) {
    for (const item of content.list_items) {
      if (item.trim() && !contentItems.includes(item)) contentItems.push(item);
    }
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%", overflow: "hidden" }}>
      {/* Slide indicator */}
      <div style={{
        padding: "12px 16px",
        borderBottom: "1px solid var(--c-border)",
        flexShrink: 0,
        display: "flex",
        alignItems: "center",
        justifyContent: "space-between",
      }}>
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <BookOpen size={14} style={{ color: "var(--c-primary)" }} />
          <span style={{ fontSize: 13, fontWeight: 600, color: "var(--c-text)" }}>
            Source Info
          </span>
        </div>
        <span style={{
          fontSize: 11,
          color: "var(--c-text-muted)",
          background: "var(--c-surface-dim)",
          padding: "2px 8px",
          borderRadius: 10,
        }}>
          Slide {currentSlideIndex + 1}{totalSlides > 0 ? ` / ${totalSlides}` : ""}
        </span>
      </div>

      {/* Scrollable content */}
      <div style={{ flex: 1, overflow: "auto", padding: "16px" }}>

        {/* Source link card */}
        {(data.source_url || sourceSlide?.page_url) && (
          <div style={{
            background: "var(--c-surface-dim)",
            borderRadius: 10,
            padding: "14px 16px",
            marginBottom: 14,
            border: "1px solid var(--c-border)",
          }}>
            <div style={{ fontSize: 11, color: "var(--c-text-muted)", marginBottom: 6, fontWeight: 500 }}>
              {data.source_type === "website" ? (
                <span style={{ display: "flex", alignItems: "center", gap: 5 }}>
                  <Globe size={12} style={{ color: "#06b6d4" }} />
                  Source Website
                </span>
              ) : (
                <span style={{ display: "flex", alignItems: "center", gap: 5 }}>
                  <FileType size={12} style={{ color: "#6366f1" }} />
                  Uploaded File
                </span>
              )}
            </div>

            {/* Page title */}
            {sourceSlide?.page_title && (
              <div style={{ fontSize: 13, fontWeight: 600, color: "var(--c-text)", marginBottom: 6 }}>
                {sourceSlide.page_title}
              </div>
            )}

            {/* Description */}
            {content?.meta_description && (
              <div style={{ fontSize: 12, color: "var(--c-text-secondary)", lineHeight: 1.5, marginBottom: 8 }}>
                {content.meta_description}
              </div>
            )}

            {/* Link */}
            {(sourceSlide?.page_url || data.source_url) && (
              <a
                href={sourceSlide?.page_url || data.source_url || ""}
                target="_blank"
                rel="noopener noreferrer"
                style={{
                  display: "inline-flex",
                  alignItems: "center",
                  gap: 5,
                  fontSize: 12,
                  color: "var(--c-primary)",
                  padding: "4px 10px",
                  borderRadius: 6,
                  background: "var(--c-primary-light)",
                  fontWeight: 500,
                  textDecoration: "none",
                }}
              >
                <ExternalLink size={12} />
                Open source page
              </a>
            )}
          </div>
        )}

        {/* No data */}
        {!sourceSlide && (
          <div style={{ fontSize: 13, color: "var(--c-text-muted)", textAlign: "center", padding: 24 }}>
            No reference data for this presentation.
          </div>
        )}

        {/* Content used for this slide */}
        {contentItems.length > 0 && (
          <div>
            <div style={{ fontSize: 12, fontWeight: 600, color: "var(--c-text)", marginBottom: 10 }}>
              Content used for this slide
            </div>
            <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
              {contentItems.slice(0, 15).map((item, i) => (
                <div
                  key={i}
                  style={{
                    fontSize: 12,
                    color: "var(--c-text-secondary)",
                    lineHeight: 1.5,
                    padding: "8px 12px",
                    background: "var(--c-surface-dim)",
                    borderRadius: 8,
                    borderLeft: "3px solid var(--c-primary-light)",
                  }}
                >
                  {item}
                </div>
              ))}
              {contentItems.length > 15 && (
                <div style={{ fontSize: 11, color: "var(--c-text-muted)", textAlign: "center", padding: 4 }}>
                  + {contentItems.length - 15} more items
                </div>
              )}
            </div>
          </div>
        )}

        {/* Navigation links from the page */}
        {content?.nav_items && content.nav_items.length > 0 && (
          <div style={{ marginTop: 14 }}>
            <div style={{ fontSize: 12, fontWeight: 600, color: "var(--c-text)", marginBottom: 8 }}>
              Page navigation links
            </div>
            <div style={{
              display: "flex",
              flexWrap: "wrap",
              gap: 6,
            }}>
              {content.nav_items.slice(0, 12).map((nav, i) => (
                <span
                  key={i}
                  style={{
                    fontSize: 11,
                    color: "var(--c-text-secondary)",
                    background: "var(--c-surface-dim)",
                    border: "1px solid var(--c-border)",
                    padding: "3px 10px",
                    borderRadius: 12,
                  }}
                >
                  {nav}
                </span>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
