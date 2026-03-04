import { useParams, Link } from "react-router-dom";
import { ArrowLeft, ChevronLeft, ChevronRight, Loader2, AlertTriangle, Home, Layers, X } from "lucide-react";
import { useState, useCallback, useEffect } from "react";
import { usePresentationSlides } from "../../hooks/usePresentation";
import { getMediaUrl } from "../../lib/slideUtils";

export default function SlideViewer() {
  const { id } = useParams<{ id: string }>();
  const presentationId = id ? parseInt(id) : null;
  const { data, loading, error } = usePresentationSlides(presentationId);
  const [current, setCurrent] = useState(0);
  const [direction, setDirection] = useState<"next" | "prev">("next");
  const [animating, setAnimating] = useState(false);
  const [showNav, setShowNav] = useState(false);

  const totalSlides = data?.slides?.length || 0;

  const goTo = useCallback((idx: number) => {
    if (animating || !data) return;
    const clamped = Math.max(0, Math.min(idx, totalSlides - 1));
    if (clamped === current) return;
    setDirection(clamped > current ? "next" : "prev");
    setAnimating(true);
    setCurrent(clamped);
    setTimeout(() => setAnimating(false), 500);
  }, [current, totalSlides, animating, data]);

  const next = useCallback(() => goTo(current + 1), [goTo, current]);
  const prev = useCallback(() => goTo(current - 1), [goTo, current]);

  // Keyboard navigation
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.target instanceof HTMLInputElement || e.target instanceof HTMLTextAreaElement) return;
      if (e.key === "ArrowRight" || e.key === "PageDown") { e.preventDefault(); next(); }
      if (e.key === "ArrowLeft" || e.key === "PageUp") { e.preventDefault(); prev(); }
      if (e.key === "Home") { e.preventDefault(); goTo(0); }
      if (e.key === "End") { e.preventDefault(); goTo(totalSlides - 1); }
      if (e.key === "Escape") setShowNav(false);
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [next, prev, goTo, totalSlides]);

  if (loading) {
    return (
      <div className="wp-loading">
        <div className="animate-fade-in-up" style={{ textAlign: "center" }}>
          <Loader2 size={40} className="animate-spin" style={{ color: "var(--c-primary)", marginBottom: 20 }} />
          <p style={{ fontSize: 18, fontWeight: 600, color: "var(--c-text)" }}>Loading...</p>
        </div>
      </div>
    );
  }

  if (error || !data) {
    return (
      <div className="wp-loading">
        <div className="animate-fade-in-up" style={{ textAlign: "center", maxWidth: 400 }}>
          <AlertTriangle size={48} style={{ color: "var(--c-warning)", marginBottom: 20 }} />
          <h2 style={{ fontSize: 22, fontWeight: 700, color: "var(--c-text)" }}>Not Found</h2>
          <p style={{ color: "var(--c-text-secondary)", marginTop: 8 }}>{error || "This presentation doesn't exist."}</p>
          <Link to="/" className="btn btn-primary" style={{ marginTop: 24 }}><Home size={16} /> Home</Link>
        </div>
      </div>
    );
  }

  const slide = data.slides[current];
  const imageUrl = slide?.slide_image ? getMediaUrl(data.presentation_id, slide.slide_image) : null;
  const progress = totalSlides > 1 ? ((current) / (totalSlides - 1)) * 100 : 100;

  return (
    <div className="wp">
      {/* The slide image fills the entire viewport — THIS IS the web page */}
      <div className={`wp-page ${animating ? (direction === "next" ? "enter-next" : "enter-prev") : ""}`} key={current}>
        {imageUrl ? (
          <img src={imageUrl} alt={`Page ${current + 1}`} className="wp-page-img" draggable={false} />
        ) : (
          <div className="wp-page-fallback">
            <p>Page {current + 1}</p>
          </div>
        )}
      </div>

      {/* Click zones — left half = prev, right half = next */}
      <div className="wp-click-left" onClick={prev} />
      <div className="wp-click-right" onClick={next} />

      {/* Minimal top-left: back button */}
      <Link to="/" className="wp-back" title="Back to home">
        <ArrowLeft size={18} />
      </Link>

      {/* Bottom navigation bar — always visible, minimal */}
      <div className="wp-bar">
        <div className="wp-bar-inner">
          <button className="wp-bar-arrow" onClick={prev} disabled={current === 0} title="Previous">
            <ChevronLeft size={20} />
          </button>

          {/* Page dots / progress */}
          <div className="wp-bar-center">
            <div className="wp-bar-progress">
              <div className="wp-bar-progress-fill" style={{ width: `${progress}%` }} />
            </div>
            <button className="wp-bar-counter" onClick={() => setShowNav(!showNav)}>
              <span className="wp-bar-current">{current + 1}</span>
              <span className="wp-bar-sep">/</span>
              <span className="wp-bar-total">{totalSlides}</span>
              <Layers size={13} style={{ marginLeft: 6, opacity: 0.5 }} />
            </button>
          </div>

          <button className="wp-bar-arrow" onClick={next} disabled={current === totalSlides - 1} title="Next">
            <ChevronRight size={20} />
          </button>
        </div>
      </div>

      {/* Page navigator overlay */}
      {showNav && (
        <>
          <div className="wp-nav-backdrop" onClick={() => setShowNav(false)} />
          <div className="wp-nav">
            <div className="wp-nav-header">
              <h3>Pages</h3>
              <button className="wp-nav-close" onClick={() => setShowNav(false)}><X size={18} /></button>
            </div>
            <div className="wp-nav-grid">
              {data.slides.map((s, idx) => {
                const thumbUrl = s.slide_image ? getMediaUrl(data.presentation_id, s.slide_image) : null;
                return (
                  <button
                    key={s.slide_index}
                    className={`wp-nav-item ${idx === current ? "active" : ""}`}
                    onClick={() => { goTo(idx); setShowNav(false); }}
                  >
                    {thumbUrl ? (
                      <img src={thumbUrl} alt={`Page ${idx + 1}`} className="wp-nav-thumb" />
                    ) : (
                      <div className="wp-nav-thumb-placeholder">{idx + 1}</div>
                    )}
                    <span className="wp-nav-label">{idx + 1}</span>
                  </button>
                );
              })}
            </div>
          </div>
        </>
      )}
    </div>
  );
}
