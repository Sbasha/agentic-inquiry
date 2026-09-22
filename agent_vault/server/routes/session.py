"""Session state endpoints.

Note: Session state is per-server-instance (one server per Claude Code session).
Each `agv server start` creates a fresh server with its own state. Multi-session
isolation is achieved at the process level, not within the state object.
"""

from fastapi import APIRouter, Request
from pydantic import BaseModel

router = APIRouter()


class SessionUpdateRequest(BaseModel):
    turn: int | None = None
    query: str | None = None
    topic: str | None = None


@router.get("/session/state")
async def get_session_state(request: Request) -> dict:
    """Get current session state."""
    return request.app.state.session_state.get_state()


@router.post("/session/state")
async def update_session_state(request: Request, body: SessionUpdateRequest) -> dict:
    """Update session state."""
    return request.app.state.session_state.update_state(
        turn=body.turn, query=body.query, topic=body.topic,
    )


@router.post("/session/increment")
async def increment_turn(request: Request) -> dict:
    """Increment turn counter."""
    return request.app.state.session_state.increment_turn()
