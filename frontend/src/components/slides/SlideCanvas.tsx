import { useRef, useEffect, useState, type CSSProperties } from "react";
import type { SlideData } from "../../types/slide";
import { emuToPx, getMediaUrl } from "../../lib/slideUtils";
import ShapeRenderer from "./ShapeRenderer";
import SlideBackground from "./SlideBackground";

interface Props {
  slide: SlideData;
  slideWidthEmu: number;
  slideHeightEmu: number;
  presentationId: number;
}

export default function SlideCanvas({ slide, slideWidthEmu, slideHeightEmu, presentationId }: Props) {
  const outerRef = useRef<HTMLDivElement>(null);
  const [scale, setScale] = useState(0);

  const slideWidthPx = emuToPx(slideWidthEmu);
  const slideHeightPx = emuToPx(slideHeightEmu);

  const slideImageUrl = slide.slide_image ? getMediaUrl(presentationId, slide.slide_image) : null;

  useEffect(() => {
    const calculateScale = () => {
      if (!outerRef.current) return;
      const rect = outerRef.current.getBoundingClientRect();
      const availW = rect.width;
      const availH = rect.height;

      if (availW <= 0 || availH <= 0) return;

      const sx = availW / slideWidthPx;
      const sy = availH / slideHeightPx;
      setScale(Math.min(sx, sy, 1.5));
    };

    const raf = requestAnimationFrame(calculateScale);
    const observer = new ResizeObserver(calculateScale);
    if (outerRef.current) observer.observe(outerRef.current);

    return () => {
      cancelAnimationFrame(raf);
      observer.disconnect();
    };
  }, [slideWidthPx, slideHeightPx]);

  const sortedShapes = [...slide.shapes].sort((a, b) => a.z_order - b.z_order);

  const canvasStyle: CSSProperties = {
    width: slideWidthPx,
    height: slideHeightPx,
    transform: `scale(${scale})`,
    transformOrigin: "top left",
    position: "relative",
    overflow: "hidden",
    boxShadow: "0 25px 60px -15px rgba(0, 0, 0, 0.2), 0 10px 20px -5px rgba(0, 0, 0, 0.08)",
    borderRadius: 8,
    backgroundColor: "#fff",
  };

  const sizedWrapperStyle: CSSProperties = {
    width: slideWidthPx * scale,
    height: slideHeightPx * scale,
    flexShrink: 0,
  };

  return (
    <div
      ref={outerRef}
      style={{
        width: "100%",
        height: "100%",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        overflow: "hidden",
      }}
    >
      {scale > 0 && (
        <div style={sizedWrapperStyle} className="animate-fade-in-scale">
          <div style={canvasStyle}>
            {/* Layer 1: If we have a rendered slide image, use it as the visual base */}
            {slideImageUrl ? (
              <img
                src={slideImageUrl}
                alt={`Slide ${slide.slide_number}`}
                style={{
                  position: "absolute",
                  top: 0,
                  left: 0,
                  width: "100%",
                  height: "100%",
                  objectFit: "fill",
                  zIndex: 0,
                  pointerEvents: "none",
                }}
                draggable={false}
              />
            ) : (
              /* Fallback: use extracted background + shape rendering */
              <>
                <SlideBackground background={slide.background} presentationId={presentationId} />
                {sortedShapes.map((shape) => (
                  <ShapeRenderer
                    key={shape.shape_id}
                    shape={shape}
                    presentationId={presentationId}
                  />
                ))}
              </>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
