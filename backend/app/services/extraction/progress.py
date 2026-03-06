"""Track extraction progress per presentation using an in-memory store."""
import time
from typing import Optional

# In-memory store for active extraction progress
_progress: dict[int, dict] = {}

def init_progress(presentation_id: int, total_slides: int):
    """Initialize progress tracking for a presentation."""
    _progress[presentation_id] = {
        "status": "starting",
        "current_slide": 0,
        "total_slides": total_slides,
        "phase": "extraction",
        "message": "Starting extraction...",
        "started_at": time.time(),
        "cancelled": False,
        "token_usage": None,
    }

def update_progress(presentation_id: int, current_slide: int, phase: str = "extraction", message: str = ""):
    """Update progress for a presentation."""
    if presentation_id in _progress:
        _progress[presentation_id].update({
            "status": "processing",
            "current_slide": current_slide,
            "phase": phase,
            "message": message,
        })

def complete_progress(presentation_id: int, message: str = "Complete!", token_usage: dict | None = None):
    """Mark extraction as complete."""
    if presentation_id in _progress:
        _progress[presentation_id].update({
            "status": "complete",
            "message": message,
            "token_usage": token_usage,
        })

def fail_progress(presentation_id: int, error: str):
    """Mark extraction as failed."""
    if presentation_id in _progress:
        _progress[presentation_id].update({
            "status": "failed",
            "message": error,
        })

def cancel_progress(presentation_id: int):
    """Mark a presentation as cancelled."""
    if presentation_id in _progress:
        _progress[presentation_id]["cancelled"] = True
        _progress[presentation_id]["status"] = "cancelled"
        _progress[presentation_id]["message"] = "Generation cancelled by user."

def is_cancelled(presentation_id: int) -> bool:
    """Check if a presentation has been cancelled."""
    prog = _progress.get(presentation_id)
    return bool(prog and prog.get("cancelled"))

def get_progress(presentation_id: int) -> Optional[dict]:
    """Get current progress for a presentation."""
    return _progress.get(presentation_id)

def cleanup_progress(presentation_id: int):
    """Remove progress data after consumption."""
    _progress.pop(presentation_id, None)
