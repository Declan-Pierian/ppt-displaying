import { useState, useEffect, useCallback } from "react";

export function useSlideNavigation(totalSlides: number) {
  const [currentSlide, setCurrentSlide] = useState(0);

  const goTo = useCallback(
    (index: number) => {
      setCurrentSlide((prev) => {
        const target = Math.max(0, Math.min(index, totalSlides - 1));
        return target;
      });
    },
    [totalSlides]
  );

  const next = useCallback(() => {
    setCurrentSlide((prev) => Math.min(prev + 1, totalSlides - 1));
  }, [totalSlides]);

  const prev = useCallback(() => {
    setCurrentSlide((prev) => Math.max(prev - 1, 0));
  }, []);

  const goFirst = useCallback(() => setCurrentSlide(0), []);
  const goLast = useCallback(() => setCurrentSlide(Math.max(0, totalSlides - 1)), [totalSlides]);

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      // Don't intercept keyboard events from inputs
      if (e.target instanceof HTMLInputElement || e.target instanceof HTMLTextAreaElement) return;
      // Don't intercept if the target is a button (Space/Enter on buttons already trigger click)
      if (e.target instanceof HTMLButtonElement) return;

      switch (e.key) {
        case "ArrowRight":
        case "PageDown":
          e.preventDefault();
          next();
          break;
        case "ArrowLeft":
        case "PageUp":
          e.preventDefault();
          prev();
          break;
        case "Home":
          e.preventDefault();
          goFirst();
          break;
        case "End":
          e.preventDefault();
          goLast();
          break;
      }
    };

    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [next, prev, goFirst, goLast]);

  // Reset when total changes
  useEffect(() => {
    if (currentSlide >= totalSlides && totalSlides > 0) {
      setCurrentSlide(totalSlides - 1);
    }
  }, [totalSlides, currentSlide]);

  return { currentSlide, goTo, next, prev, goFirst, goLast };
}
