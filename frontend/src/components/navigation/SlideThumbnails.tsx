import type { SlideData } from "../../types/slide";

interface Props {
  slides: SlideData[];
  currentSlide: number;
  onSelect: (index: number) => void;
}

export default function SlideThumbnails({ slides, currentSlide, onSelect }: Props) {
  return (
    <div className="thumb-list stagger-children">
      {slides.map((slide, idx) => {
        const isActive = idx === currentSlide;
        return (
          <button key={slide.slide_index} onClick={() => onSelect(idx)} className={`thumb-item ${isActive ? "active" : ""}`}>
            <div className="thumb-number">{idx + 1}</div>
            <p className="thumb-text">{getSlidePreviewText(slide)}</p>
            {isActive && <div style={{ width: 6, height: 6, borderRadius: "50%", background: "white", flexShrink: 0 }} />}
          </button>
        );
      })}
    </div>
  );
}

function getSlidePreviewText(slide: SlideData): string {
  for (const shape of slide.shapes) {
    if ("text_body" in shape && shape.text_body?.paragraphs) {
      for (const para of shape.text_body.paragraphs) {
        const text = para.runs.map((r) => r.text).join("").trim();
        if (text) return text;
      }
    }
  }
  return `Slide ${slide.slide_number}`;
}
