from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlmodel import Session, select

from ..core import cheating, timing
from ..core.netutil import ip_allowed
from ..db import get_session
from ..deps import get_current_user, get_ip
from ..models import Attempt, Exam, ProctorEvent, User, jdump, jload, utcnow
from ..schemas import AnswerIn, EventIn, HeartbeatIn, SnapshotIn, SyncIn
from .. import services as svc

router = APIRouter(prefix="/api", tags=["attempts"])


def load_live(session: Session, attempt_id: int, user: User, request: Request, touch: bool = True, rules: bool = True):
    """Fetch the caller's attempt, enforce IP rules and the server clock. Returns (attempt, exam, previous last_seen)."""
    a = session.get(Attempt, attempt_id)
    if not a or a.user_id != user.id:
        raise HTTPException(status_code=404, detail="Attempt not found")
    exam = session.get(Exam, a.exam_id)
    if not a.is_practice and not ip_allowed(get_ip(request), jload(exam.allowed_ips, [])):
        raise HTTPException(status_code=403, detail="ip_not_allowed: this exam can only be taken from the approved network.")
    prev = a.last_seen
    if rules:
        svc.apply_time_rules(session, a, exam)
    if touch and a.status != "submitted":
        a.last_seen = utcnow()
        session.add(a)
        session.commit()
    return a, exam, prev


def _live_info(a: Attempt) -> dict:
    state = jload(a.section_state) or {"timed": False, "sections": {}}
    return {"status": a.status, "server_time": svc.iso(utcnow()), "expires_at": svc.iso(a.expires_at), "violations": a.violations,
            "sections": {sid: {"status": s["status"], "deadline": s["deadline"]} for sid, s in state["sections"].items()} if state.get("timed") else {}}


@router.get("/attempts/{attempt_id}/state")
def get_state(attempt_id: int, request: Request, user: User = Depends(get_current_user), session: Session = Depends(get_session)):
    a, exam, _ = load_live(session, attempt_id, user, request)
    if a.status == "submitted":
        return {"submitted": True, "attempt_id": a.id}
    if a.status == "paused":
        svc.resume_attempt(session, a)
    return svc.attempt_state(session, a, exam, user)


@router.post("/attempts/{attempt_id}/answer")
def post_answer(attempt_id: int, payload: AnswerIn, request: Request, user: User = Depends(get_current_user),
                session: Session = Depends(get_session)):
    a, exam, _ = load_live(session, attempt_id, user, request)
    if a.status == "submitted":
        raise HTTPException(status_code=409, detail="submitted")
    if a.status == "paused":
        raise HTTPException(status_code=409, detail="paused")
    qd = svc.answerable_question(session, a, payload.question_id)
    svc.save_answer(session, a, qd, payload.value)
    marked = None
    if payload.marked is not None:
        cur = set(jload(a.marked, []))
        (cur.add if payload.marked else cur.discard)(payload.question_id)
        marked = list(cur)
    times = {str(payload.question_id): payload.time_spent} if payload.time_spent is not None else None
    svc.merge_progress(a, marked, times)
    session.add(a)
    session.commit()
    return {"saved": True, **_live_info(a)}


@router.post("/attempts/{attempt_id}/heartbeat")
def heartbeat(attempt_id: int, payload: HeartbeatIn, request: Request, user: User = Depends(get_current_user),
              session: Session = Depends(get_session)):
    a, exam, _ = load_live(session, attempt_id, user, request)
    if a.status == "paused":
        svc.resume_attempt(session, a)
    if a.status != "submitted":
        svc.merge_progress(a, payload.marked, payload.times)
        session.add(a)
        session.commit()
    return _live_info(a)


@router.post("/attempts/{attempt_id}/sync")
def sync(attempt_id: int, payload: SyncIn, request: Request, user: User = Depends(get_current_user), session: Session = Depends(get_session)):
    """Called when the connection returns. Applies everything buffered offline, then credits the outage (capped)."""
    a, exam, prev_seen = load_live(session, attempt_id, user, request, touch=False, rules=False)
    if a.status == "submitted":
        return {"status": "submitted", "attempt_id": a.id}
    if a.status == "paused":
        svc.resume_attempt(session, a)
    now = utcnow()
    gap = (now - prev_seen).total_seconds()
    credit = timing.offline_credit(payload.offline_seconds, gap, svc.cap_remaining(a))
    if credit:
        svc.credit_time(session, a, credit)
    a.last_seen = now
    session.add(a)
    session.commit()
    svc.apply_time_rules(session, a, exam)
    rejected, auto = [], False
    if a.status != "submitted":
        for item in sorted(payload.answers, key=lambda x: x.ts or 0):
            try:
                qd = svc.answerable_question(session, a, item.question_id)
                svc.save_answer(session, a, qd, item.value)
            except HTTPException as e:
                rejected.append({"question_id": item.question_id, "reason": e.detail})
        svc.merge_progress(a, payload.marked, payload.times)
        session.add(a)
        session.commit()
        for ev in payload.events:
            if ev.type in cheating.ALLOWED_EVENT_TYPES and a.status != "submitted":
                auto = svc.record_event(session, a, exam, ev.type, ev.detail) or auto
        for snap in payload.snapshots:
            try:
                svc.save_snapshot(session, a, snap.image, snap.label)
            except HTTPException:
                pass
    return {**_live_info(a), "credit_seconds": credit, "rejected": rejected, "auto_submitted": auto or a.status == "submitted"}


@router.post("/attempts/{attempt_id}/pause")
def pause(attempt_id: int, request: Request, user: User = Depends(get_current_user), session: Session = Depends(get_session)):
    a, exam, _ = load_live(session, attempt_id, user, request)
    if a.status != "in_progress":
        return {"detail": "not in progress", **_live_info(a)}
    a.status, a.paused_at = "paused", utcnow()
    session.add(a)
    session.commit()
    return {"detail": "paused", **_live_info(a)}


@router.post("/attempts/{attempt_id}/resume")
def resume(attempt_id: int, request: Request, user: User = Depends(get_current_user), session: Session = Depends(get_session)):
    a, exam, _ = load_live(session, attempt_id, user, request)
    credit = svc.resume_attempt(session, a)
    return {"detail": "resumed" if credit or a.status == "in_progress" else "not paused", "credit_seconds": credit, **_live_info(a)}


@router.post("/attempts/{attempt_id}/sections/{section_id}/start")
def start_section(attempt_id: int, section_id: int, request: Request, user: User = Depends(get_current_user), session: Session = Depends(get_session)):
    a, exam, _ = load_live(session, attempt_id, user, request)
    if a.status != "in_progress":
        raise HTTPException(status_code=409, detail="Attempt is not running")
    state = jload(a.section_state)
    if not state or not state.get("timed"):
        raise HTTPException(status_code=409, detail="This exam has no timed sections")
    reason = timing.can_start(state, str(section_id))
    if reason:
        raise HTTPException(status_code=409, detail=reason)
    timing.start(state, str(section_id), utcnow(), a.expires_at)
    a.section_state = jdump(state)
    session.add(a)
    session.commit()
    return svc.attempt_state(session, a, exam, user)


@router.post("/attempts/{attempt_id}/sections/{section_id}/finish")
def finish_section(attempt_id: int, section_id: int, request: Request, user: User = Depends(get_current_user), session: Session = Depends(get_session)):
    a, exam, _ = load_live(session, attempt_id, user, request)
    state = jload(a.section_state)
    if a.status != "in_progress" or not state or state["sections"].get(str(section_id), {}).get("status") != "active":
        raise HTTPException(status_code=409, detail="That section is not running")
    timing.finish(state, str(section_id))
    a.section_state = jdump(state)
    session.add(a)
    session.commit()
    return svc.attempt_state(session, a, exam, user)


@router.post("/attempts/{attempt_id}/submit")
def submit(attempt_id: int, request: Request, user: User = Depends(get_current_user), session: Session = Depends(get_session)):
    a, exam, _ = load_live(session, attempt_id, user, request)
    if a.status != "submitted":
        svc.finalize_attempt(session, a, exam, "manual")
    return _owner_result(session, a, exam)


@router.post("/attempts/{attempt_id}/snapshot")
def snapshot(attempt_id: int, payload: SnapshotIn, request: Request, user: User = Depends(get_current_user), session: Session = Depends(get_session)):
    a, exam, _ = load_live(session, attempt_id, user, request)
    if a.status == "submitted":
        raise HTTPException(status_code=409, detail="submitted")
    snap = svc.save_snapshot(session, a, payload.image, payload.label)
    return {"saved": bool(snap)}


@router.post("/attempts/{attempt_id}/events")
def post_event(attempt_id: int, payload: EventIn, request: Request, user: User = Depends(get_current_user), session: Session = Depends(get_session)):
    a, exam, _ = load_live(session, attempt_id, user, request)
    if a.status == "submitted":
        return {"auto_submitted": True, "violations": a.violations}
    auto = svc.record_event(session, a, exam, payload.type, payload.detail)
    return {"auto_submitted": auto or a.status == "submitted", "violations": a.violations, "max_violations": exam.max_violations}


# ------------------------------------------------------------------ results
def _owner_result(session: Session, a: Attempt, exam: Exam) -> dict:
    out = svc.result_summary(a, exam)
    if a.status != "submitted":
        return out
    if not exam.show_result and not a.is_practice:
        return {"attempt_id": a.id, "exam_id": exam.id, "exam_title": exam.title, "status": a.status, "hidden": True,
                "submit_reason": a.submit_reason, "is_practice": False}
    res = jload(a.result, {})
    names = {str(s.id): s.name for s in svc.sections_of(session, exam.id)}
    out["by_topic"] = res.get("by_topic", {})
    out["by_section"] = [{"id": k, "name": names.get(k, "Section"), **v} for k, v in res.get("by_section", {}).items()]
    reveal = exam.show_answers or a.is_practice
    out["review"] = svc.review_items(session, a, reveal)
    out["answers_revealed"] = reveal
    out["certificate_available"] = bool(exam.certificate_enabled and out["passed"] and not a.is_practice)
    out["rank"] = None
    if exam.live_ranking and not a.is_practice:
        board = svc.leaderboard(session, exam, limit=10000)
        mine = next((r for r in board if r["user_id"] == a.user_id), None)
        out["rank"] = {"position": mine["rank"], "of": len(board)} if mine else None
    return out


@router.get("/attempts/{attempt_id}/result")
def get_result(attempt_id: int, user: User = Depends(get_current_user), session: Session = Depends(get_session)):
    a = session.get(Attempt, attempt_id)
    if not a:
        raise HTTPException(status_code=404, detail="Attempt not found")
    exam = session.get(Exam, a.exam_id)
    if a.user_id == user.id:
        if a.status != "submitted":
            raise HTTPException(status_code=409, detail="Attempt not submitted yet")
        return _owner_result(session, a, exam)
    if svc.can_manage(user, exam):
        out = svc.result_summary(a, exam)
        student = session.get(User, a.user_id)
        res = jload(a.result, {})
        out["student"] = {"id": student.id, "name": student.name, "email": student.email, "roll_no": student.roll_no}
        out["by_topic"] = res.get("by_topic", {})
        out["review"] = svc.review_items(session, a, True) if a.status == "submitted" else []
        return out
    raise HTTPException(status_code=404, detail="Attempt not found")


@router.get("/me/analytics")
def my_analytics(user: User = Depends(get_current_user), session: Session = Depends(get_session)):
    """Student analytics: score trend, topic strengths and time per question across all submitted attempts."""
    rows = session.exec(select(Attempt, Exam).where(Attempt.user_id == user.id, Attempt.status == "submitted",
                                                    Attempt.exam_id == Exam.id).order_by(Attempt.finished_at)).all()
    trend, topics, total_time, total_q = [], {}, 0.0, 0
    for a, e in rows:
        if not e.show_result and not a.is_practice:
            continue
        trend.append({"attempt_id": a.id, "exam": e.title, "percent": a.percent, "practice": a.is_practice, "date": svc.iso(a.finished_at)})
        for t, v in (jload(a.result, {}).get("by_topic", {})).items():
            b = topics.setdefault(t, {"total": 0, "correct": 0})
            b["total"] += v["total"]
            b["correct"] += v["correct"]
        times = jload(a.times, {})
        total_time += sum(times.values())
        total_q += len(times)
    for b in topics.values():
        b["percent"] = round(100 * b["correct"] / b["total"], 1) if b["total"] else 0
    return {"attempts": len(trend), "trend": trend, "topics": topics,
            "avg_time_per_question": round(total_time / total_q, 1) if total_q else 0,
            "average_percent": round(sum(t["percent"] for t in trend) / len(trend), 1) if trend else 0}
