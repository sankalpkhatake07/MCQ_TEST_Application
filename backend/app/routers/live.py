import json

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlmodel import Session

from .. import events, security, services as svc
from ..db import get_session
from ..deps import get_current_user
from ..models import User

router = APIRouter(prefix="/api/live", tags=["live"])


@router.post("/ticket/{exam_id}")
def ticket(exam_id: int, kind: str = "proctor", user: User = Depends(get_current_user), session: Session = Depends(get_session)):
    """EventSource cannot send headers, so the browser first trades its login for a 2-minute stream ticket."""
    exam = svc.get_exam_or_404(session, exam_id)
    if kind == "proctor":
        if not svc.can_manage(user, exam):
            raise HTTPException(status_code=403, detail="Not allowed")
    elif kind == "rank":
        if not svc.can_manage(user, exam) and not (exam.published and exam.live_ranking):
            raise HTTPException(status_code=403, detail="Ranking is not enabled")
    else:
        raise HTTPException(status_code=422, detail="Unknown stream")
    return {"ticket": security.make_token({"typ": "stream", "exam": exam_id, "kind": kind}, 2)}


@router.get("/stream")
async def stream(t: str):
    try:
        data = security.read_token(t, "stream")
    except Exception:
        raise HTTPException(status_code=403, detail="Ticket expired")
    channel = f"exam:{data['exam']}:{data['kind']}"

    async def gen():
        yield "retry: 3000\n\n"
        async for msg in events.subscribe(channel):
            if msg.get("type") == "ping":
                yield ": ping\n\n"
            else:
                yield f"data: {json.dumps(msg)}\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"})
