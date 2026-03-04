import { ChevronLeft, ChevronRight, SkipBack, SkipForward } from "lucide-react";

interface Props {
  currentSlide: number;
  totalSlides: number;
  onPrev: () => void;
  onNext: () => void;
  onGoTo: (index: number) => void;
}

export default function SlideNav({ currentSlide, totalSlides, onPrev, onNext, onGoTo }: Props) {
  const progress = totalSlides > 1 ? ((currentSlide) / (totalSlides - 1)) * 100 : 100;

  return (
    <div className="animate-fade-in">
      <div className="nav-progress">
        <div className="nav-progress-bar" style={{ width: `${progress}%` }} />
      </div>
      <div className="nav-controls">
        <button onClick={() => onGoTo(0)} disabled={currentSlide === 0} className="nav-btn small" title="First slide">
          <SkipBack size={16} />
        </button>
        <button onClick={onPrev} disabled={currentSlide === 0} className="nav-btn" title="Previous slide">
          <ChevronLeft size={20} />
        </button>
        <div className="nav-counter">
          <span className="current">{currentSlide + 1}</span>
          <span className="sep">/</span>
          <span className="total">{totalSlides}</span>
        </div>
        <button onClick={onNext} disabled={currentSlide === totalSlides - 1} className="nav-btn next" title="Next slide">
          <ChevronRight size={20} />
        </button>
        <button onClick={() => onGoTo(totalSlides - 1)} disabled={currentSlide === totalSlides - 1} className="nav-btn small" title="Last slide">
          <SkipForward size={16} />
        </button>
      </div>
    </div>
  );
}
