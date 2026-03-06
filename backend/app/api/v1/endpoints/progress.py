"""SSE endpoint for extraction progress."""
import asyncio
import json
from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from app.services.extraction.progress import get_progress

router = APIRouter(tags=["progress"])

@router.get("/progress/{presentation_id}")
async def stream_progress(presentation_id: int):
    """Stream extraction progress via Server-Sent Events."""
    async def event_generator():
        while True:
            progress = get_progress(presentation_id)
            if progress:
                data = json.dumps(progress)
                yield f"data: {data}\n\n"
                if progress["status"] in ("complete", "failed", "cancelled"):
                    break
            else:
                yield f"data: {json.dumps({'status': 'waiting', 'message': 'Waiting for extraction to start...'})}\n\n"
            await asyncio.sleep(0.5)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
