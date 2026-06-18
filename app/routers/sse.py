"""
SSE Router — Server-Sent Events for real-time progress updates.

WHY SSE NOT WEBSOCKETS:
  Communication during agent execution is ONE-WAY only.
  Server pushes progress to client. Client NEVER sends back.
  SSE is designed exactly for this:
    - Regular HTTP (no protocol upgrade needed)
    - Auto-reconnects on connection drop
    - Visible in browser network tab for debugging
    - No extra libraries needed on frontend (native EventSource API)
    - No extra libraries needed on backend (FastAPI StreamingResponse)

FLOW:
  1. Frontend calls POST /analyze → receives session_id
  2. Frontend opens EventSource to GET /analysis/stream/{session_id}
  3. This router polls Redis every 1 second for progress updates
  4. Sends events to frontend as they happen:
       data: {"current_agent": "gap_analysis", "status": "running"}
  5. When status is "complete", sends final event with analysis_id:
       data: {"current_agent": "report_generator", "status": "complete",
              "analysis_id": "uuid-here"}
  6. Frontend closes EventSource and fetches results

MESSAGE FORMAT (SSE standard):
  Each message is a line starting with "data: " followed by JSON.
  Messages are separated by double newlines.
  This is the SSE spec — browsers parse this natively.
"""

import json
import asyncio
from fastapi import APIRouter, HTTPException, status
from fastapi.responses import StreamingResponse
from app.redis_client import get_session

router = APIRouter(prefix="/analysis", tags=["sse"])


@router.get("/stream/{session_id}")
async def stream_progress(session_id: str):
    """
    SSE endpoint for real-time agent progress streaming.

    The frontend connects to this endpoint using the native
    browser EventSource API:

        const es = new EventSource(
            "http://localhost:8000/analysis/stream/sess-abc123"
        );
        es.onmessage = (event) => {
            const data = JSON.parse(event.data);
            console.log(data.current_agent, data.status);
        };

    The connection stays open until:
      - Status becomes "complete" (normal completion)
      - Status becomes "failed" (pipeline error)
      - Client disconnects (closes EventSource)
      - 5 minutes timeout (prevents zombie connections)

    NOTE: This endpoint does NOT require JWT authentication.
    The session_id itself is the auth token — it's a random
    string that's only known to the user who started the analysis.
    This is intentional to keep EventSource simple (EventSource
    doesn't support custom headers for JWT).
    """

    # Verify the session exists in Redis
    session = get_session(session_id)
    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Session not found. Analysis may not have started."
        )

    # Return a StreamingResponse with SSE media type
    return StreamingResponse(
        _event_generator(session_id),
        media_type="text/event-stream",
        headers={
            # Disable response buffering so events stream immediately
            "Cache-Control": "no-cache",
            # Keep connection alive
            "Connection": "keep-alive",
            # Required by some proxies for SSE
            "X-Accel-Buffering": "no",
        }
    )


async def _event_generator(session_id: str):
    """
    Async generator that yields SSE events.

    Polls Redis every 1 second for the session's current state.
    Yields each update as a properly formatted SSE message.

    Terminates when:
      - status is "complete" → sends final message with analysis_id
      - status is "failed" → sends error message
      - 300 iterations (5 minutes) → timeout safety net
    """

    # Track the last state to avoid sending duplicate events
    last_agent = None
    last_status = None

    # Maximum iterations to prevent zombie connections.
    # 300 iterations × 1 second = 5 minutes max.
    # Normal analysis takes 30-120 seconds.
    max_iterations = 300

    for _ in range(max_iterations):
        # ── Read current state from Redis ────────────────────
        session = get_session(session_id)

        if not session:
            # Session expired or deleted — close the stream
            yield _format_sse({"status": "error", "message": "Session expired"})
            return

        current_agent = session.get("current_agent", "")
        agent_status = session.get("agent_status", "")
        overall_status = session.get("status", "running")

        # ── Check for completion ─────────────────────────────
        if overall_status == "complete":
            # Send final event with analysis_id
            yield _format_sse({
                "current_agent": current_agent,
                "status": "complete",
                "analysis_id": session.get("analysis_id", "")
            })
            return  # Close the stream

        if overall_status == "failed":
            # Send error event
            yield _format_sse({
                "current_agent": current_agent,
                "status": "failed",
                "error": session.get("error", "Pipeline failed")
            })
            return  # Close the stream

        # ── Send progress update (if changed) ────────────────
        if current_agent != last_agent or agent_status != last_status:
            yield _format_sse({
                "current_agent": current_agent,
                "status": agent_status
            })
            last_agent = current_agent
            last_status = agent_status

        # ── Wait 1 second before next poll ───────────────────
        await asyncio.sleep(1)

    # If we reach here, we hit the timeout
    yield _format_sse({
        "status": "error",
        "message": "Stream timeout after 5 minutes"
    })


def _format_sse(data: dict) -> str:
    """
    Format a dict as an SSE message.

    SSE format:
      data: {"key": "value"}\n\n

    The "data: " prefix and double newline are required by the SSE spec.
    The browser's EventSource API parses this automatically.
    """
    return f"data: {json.dumps(data)}\n\n"
