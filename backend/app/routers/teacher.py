import statistics

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from sqlmodel import Session, select

from ..core import analytics, cheating
from ..db import get_session
from ..deps import teacher_or_admin
from ..models import Attempt, Exam, ProctorEvent, Snapshot, User, jload
from .. import security, services as svc
from ..storage import get_storage

router = APIRouter(prefix="/api", tags=["teacher"])


def _exam_for(session: Session, user: User, exam_id: int) -> Exam:
    exam = svc.get_exam_or_404(session, exam_id)
    if not svc.can_manage(user, exam):
        raise HTTPException(status_code=404, detail="Exam not found")
    return exam


def attempt_rows(session: Session, exam: Exam, include_in_progress: bool = True):
    q = select(Attempt, User).where(Attempt.exam_id == exam.id, Attempt.is_practice == False, Attempt.user_id == User.id)  # noqa: E712
    rows = session.exec(q).all()
    out = []
    for a, u in rows:
        if a.status != "submitted" and not include_in_progress:
            continue
        out.append({"attempt_id": a.id, "user_id": u.id, "name": u.name or u.email.split("@")[0], "email": u.email, "roll_no": u.roll_no,
                    "status": a.status, "score": a.score or 0, "max_score": a.max_score or 0, "percent": a.percent or 0,
                    "correct": a.correct_count or 0, "wrong": a.wrong_count or 0, "unanswered": a.unanswered_count or 0,
                    "seconds": svc.elapsed_seconds(a), "cheating_score": a.cheating_score or 0,
                    "cheating_level": cheating.level(a.cheating_score or 0), "violations": a.violations,
                    "started_at": svc.iso(a.started_at), "finished_at": svc.iso(a.finished_at), "submit_reason": a.submit_reason,
                    "_a": a})
    out.sort(key=lambda r: (r["status"] != "submitted", -r["score"], r["seconds"]))
    return out


@router.get("/exams/{exam_id}/attempts")
def list_attempts(exam_id: int, user: User = Depends(teacher_or_admin), session: Session = Depends(get_session)):
    exam = _exam_for(session, user, exam_id)
    rows = attempt_rows(session, exam)
    for r in rows:
        r.pop("_a")
    return rows


@router.get("/exams/{exam_id}/analytics")
def exam_analytics(exam_id: int, user: User = Depends(teacher_or_admin), session: Session = Depends(get_session)):
    exam = _exam_for(session, user, exam_id)
    rows = attempt_rows(session, exam, include_in_progress=False)
    ins = analytics.insights([{"score": r["score"], "percent": r["percent"], "seconds": r["seconds"]} for r in rows], exam.pass_percent)
    _, qmap, _ = svc.load_exam_content(session, exam.id)
    atts = [{"score": r["score"], "per_question": (jload(r["_a"].result, {}).get("per_question", {})), "times": jload(r["_a"].times, {})} for r in rows]
    items = analytics.item_analysis([{"id": q["id"], "text": q["text"], "difficulty": q["difficulty"]} for q in qmap.values()], atts)
    topics = {}
    for r in rows:
        for t, v in jload(r["_a"].result, {}).get("by_topic", {}).items():
            b = topics.setdefault(t, {"total": 0, "correct": 0})
            b["total"] += v["total"]
            b["correct"] += v["correct"]
    for b in topics.values():
        b["percent"] = round(100 * b["correct"] / b["total"], 1) if b["total"] else 0
    risk = {"low": 0, "medium": 0, "high": 0}
    for r in rows:
        risk[r["cheating_level"]] += 1
    in_progress = sum(1 for r in attempt_rows(session, exam) if r["status"] != "submitted")
    return {"exam": svc.exam_dict(exam), "insights": ins, "items": items, "topics": topics, "risk": risk, "in_progress": in_progress}


@router.get("/attempts/{attempt_id}/proctor")
def proctor_view(attempt_id: int, user: User = Depends(teacher_or_admin), session: Session = Depends(get_session)):
    a = session.get(Attempt, attempt_id)
    if not a:
        raise HTTPException(status_code=404, detail="Attempt not found")
    exam = _exam_for(session, user, a.exam_id)
    student = session.get(User, a.user_id)
    evs = session.exec(select(ProctorEvent).where(ProctorEvent.attempt_id == a.id).order_by(ProctorEvent.ts)).all()
    snaps = session.exec(select(Snapshot).where(Snapshot.attempt_id == a.id).order_by(Snapshot.created_at)).all()
    return {"attempt_id": a.id, "exam": {"id": exam.id, "title": exam.title}, "status": a.status,
            "student": {"name": student.name, "email": student.email, "roll_no": student.roll_no},
            "cheating_score": a.cheating_score, "level": cheating.level(a.cheating_score or 0), "violations": a.violations,
            "events": [{"id": e.id, "type": e.type, "detail": e.detail, "ts": svc.iso(e.ts)} for e in evs],
            "snapshots": [{"id": s.id, "label": s.label, "ts": svc.iso(s.created_at),
                           "url": f"/api/snapshots/{s.id}?t={security.make_token({'typ': 'media', 'sid': s.id}, 30)}"} for s in snaps]}


@router.get("/snapshots/{snap_id}")
def get_snapshot(snap_id: int, t: str, session: Session = Depends(get_session)):
    """<img> tags cannot send an Authorization header, so the teacher UI uses a 30-minute signed link."""
    try:
        data = security.read_token(t, "media")
    except Exception:
        raise HTTPException(status_code=403, detail="Link expired")
    if data.get("sid") != snap_id:
        raise HTTPException(status_code=403, detail="Link does not match")
    snap = session.get(Snapshot, snap_id)
    if not snap:
        raise HTTPException(status_code=404, detail="Not found")
    try:
        body = get_storage().get(snap.key)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Snapshot file missing")
    return Response(body, media_type="image/png" if snap.key.endswith(".png") else "image/jpeg",
                    headers={"Cache-Control": "private, max-age=600", "X-Content-Type-Options": "nosniff"})


@router.delete("/attempts/{attempt_id}")
def reset_attempt(attempt_id: int, user: User = Depends(teacher_or_admin), session: Session = Depends(get_session)):
    """Delete a student's attempt so they can take the exam again (e.g. after a technical failure)."""
    a = session.get(Attempt, attempt_id)
    if not a:
        raise HTTPException(status_code=404, detail="Attempt not found")
    _exam_for(session, user, a.exam_id)
    store = get_storage()
    for s in session.exec(select(Snapshot).where(Snapshot.attempt_id == a.id)).all():
        try:
            store.delete(s.key)
        except Exception:
            pass
        session.delete(s)
    for e in session.exec(select(ProctorEvent).where(ProctorEvent.attempt_id == a.id)).all():
        session.delete(e)
    session.delete(a)
    session.commit()
    return {"detail": "attempt_deleted"}
