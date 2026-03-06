import { useEffect, useRef, useState, useCallback } from "react";

/**
 * Syncs with the presentation iframe via postMessage.
 * The injected JS in webpage.html sends { type: 'slideChange', slideIndex, totalSlides }
 * whenever the active slide changes.
 */
export function useSlideSync() {
  const [currentSlideIndex, setCurrentSlideIndex] = useState(0);
  const [totalSlides, setTotalSlides] = useState(0);
  const iframeRef = useRef<HTMLIFrameElement>(null);

  useEffect(() => {
    function handleMessage(event: MessageEvent) {
      if (event.data && event.data.type === "slideChange") {
        setCurrentSlideIndex(event.data.slideIndex ?? 0);
        if (event.data.totalSlides) {
          setTotalSlides(event.data.totalSlides);
        }
      }
    }

    window.addEventListener("message", handleMessage);
    return () => window.removeEventListener("message", handleMessage);
  }, []);

  const refreshIframe = useCallback(() => {
    if (iframeRef.current) {
      const src = iframeRef.current.src;
      // Preserve token param, update/add cache-buster
      const url = new URL(src);
      url.searchParams.set("t", String(Date.now()));
      iframeRef.current.src = url.toString();
    }
  }, []);

  return { currentSlideIndex, totalSlides, iframeRef, refreshIframe };
}
