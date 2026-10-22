"""Exam / attempt lifecycle. Kept separate from the routers so the rules live in one place."""
import hashlib
import hmac
import random
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

from fastapi import HTTPException
from sqlmodel import Session, select

from . import config, events
from .core import cheating, scoring, shuffle, timing
from .models import (Attempt, Exam, ExamQuestion, ExamSection, ProctorEvent, Question, Snapshot, User,
                     jdump, jload, utcnow)

iso = timing.iso
VIOLATION_TYPES = {"tab_switch", "fullscreen_exit"}
MAX_EVENTS_PER_ATTEMPT = 2000


# ------------------------------------------------------------------ exam helpers
def exam_status(e: Exam, n: Optional[datetime] = None) -> str:
    n = n or utcnow()
    if not e.published:
        return "draft"
    if e.closed_manual or (e.end_at and n > e.end_at):
        return "closed"
    if e.start_at and n < e.start_at:
        return "upcoming"
    return "open"


def can_manage(user: User, exam: Exam) -> bool:
    return user.role == "admin" or (user.role == "teacher" and exam.owner_id == user.id)


def get_exam_or_404(session: Session, exam_id: int) -> Exam:
    e = session.get(Exam, exam_id)
    if not e:
        raise HTTPException(status_code=404, detail="Exam not found")
    return e


def exam_dict(e: Exam, full: bool = False) -> dict:
    d = {"id": e.id, "title": e.title, "description": e.description, "instructions": e.instructions,
         "duration_min": e.duration_min, "status": exam_status(e), "published": e.published,
         "start_at": iso(e.start_at), "end_at": iso(e.end_at), "visible_from": iso(e.visible_from),
         "lockdown": e.lockdown, "fullscreen_required": e.fullscreen_required, "camera_required": e.camera_required,
         "mic_enabled": e.mic_enabled, "ai_proctoring": e.ai_proctoring, "negative_mark": e.negative_mark,
         "pass_percent": e.pass_percent, "practice_enabled": e.practice_enabled, "live_ranking": e.live_ranking,
         "certificate_enabled": e.certificate_enabled, "shuffle_questions": e.shuffle_questions,
         "shuffle_options": e.shuffle_options, "languages": jload(e.languages) or ["en", "hi", "mr"],
         "show_result": e.show_result, "show_answers": e.show_answers}
    if full:
        d.update({"closed_manual": e.closed_manual, "strict_end": e.strict_end, "max_violations": e.max_violations,
                  "snapshot_interval": e.snapshot_interval, "allowed_ips": jload(e.allowed_ips) or [],
                  "owner_id": e.owner_id, "created_at": iso(e.created_at)})
    return d


def parse_dt(s: Optional[str]) -> Optional[datetime]:
    """Accepts ISO strings (with or without Z / offset) and stores naive UTC. Empty string clears."""
    if s is None or s == "":
        return None
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        raise HTTPException(status_code=422, detail=f"Invalid date: {s}")
    if dt.tzinfo is not None:
        dt = (dt - dt.utcoffset()).replace(tzinfo=None)
    return dt


# ------------------------------------------------------------------ questions
def q_dict(q: Question, eq: Optional[ExamQuestion] = None) -> dict:
    return {"id": q.id, "section_id": eq.section_id if eq else None, "qtype": q.qtype, "text": q.text,
            "choices": jload(q.choices, []), "correct": jload(q.correct), "marks": eq.marks if eq and eq.marks is not None else q.marks,
            "difficulty": q.difficulty, "tags": jload(q.tags, []), "subject": q.subject, "explanation": q.explanation}


def sections_of(session: Session, exam_id: int) -> List[ExamSection]:
    return session.exec(select(ExamSection).where(ExamSection.exam_id == exam_id)
                        .order_by(ExamSection.position, ExamSection.id)).all()


def load_exam_content(session: Session, exam_id: int) -> Tuple[List[ExamSection], Dict[int, dict], Dict[int, List[int]]]:
    secs = sections_of(session, exam_id)
    eqs = session.exec(select(ExamQuestion).where(ExamQuestion.exam_id == exam_id)
                       .order_by(ExamQuestion.position, ExamQuestion.id)).all()
    ids = [eq.question_id for eq in eqs]
    qs = {q.id: q for q in session.exec(select(Question).where(Question.id.in_(ids))).all()} if ids else {}
    qmap, pools = {}, {s.id: [] for s in secs}
    for eq in eqs:
        q = qs.get(eq.question_id)
        if q is None or eq.section_id not in pools:
            continue
        qmap[q.id] = q_dict(q, eq)
        pools[eq.section_id].append(q.id)
    return secs, qmap, pools


def has_real_attempts(session: Session, exam_id: int) -> bool:
    return session.exec(select(Attempt.id).where(Attempt.exam_id == exam_id, Attempt.is_practice == False)).first() is not None  # noqa: E712


def assert_editable(session: Session, exam: Exam):
    if has_real_attempts(session, exam.id):
        raise HTTPException(status_code=409, detail="Students have already started this exam, so its questions and sections are locked.")


def correct_text(qd: dict) -> str:
    c = qd["correct"]
    if qd["qtype"] == "fill":
        return " | ".join(c) if isinstance(c, list) else str(c)
    try:
        return qd["choices"][int(c)]
    except (TypeError, ValueError, IndexError):
        return ""


def given_text(qd: dict, value) -> str:
    if not scoring.is_answered(value):
        return ""
    if qd["qtype"] == "fill":
        return str(value)
    try:
        return qd["choices"][int(value)]
    except (TypeError, ValueError, IndexError):
        return ""


# ------------------------------------------------------------------ attempts
def elapsed_seconds(a: Attempt) -> int:
    end = a.finished_at or utcnow()
    return max(0, int((end - a.started_at).total_seconds()) - (a.total_paused_seconds or 0))


def create_attempt(session: Session, exam: Exam, user: User, practice: bool, ip: str) -> Attempt:
    secs, qmap, pools = load_exam_content(session, exam.id)
    sec_inputs = [{"id": s.id, "pick_count": s.pick_count, "qids": pools[s.id]} for s in secs if pools[s.id]]
    if not sec_inputs:
        raise HTTPException(status_code=409, detail="This exam has no questions yet.")
    seed = random.SystemRandom().randrange(1, 2 ** 31)
    layout = shuffle.build_layout(sec_inputs, qmap, seed, exam.shuffle_questions, exam.shuffle_options)
    n = utcnow()
    expires = n + timedelta(minutes=exam.duration_min)
    if exam.strict_end and exam.end_at and not practice:
        expires = min(expires, exam.end_at)
    if expires <= n:
        raise HTTPException(status_code=409, detail="This exam has already ended.")
    state = timing.new_state([{"id": s["id"], "duration_min": next(x.duration_min for x in secs if x.id == s["id"])} for s in sec_inputs])
    a = Attempt(exam_id=exam.id, user_id=user.id, is_practice=practice, started_at=n, expires_at=expires, last_seen=n,
                seed=seed, layout=jdump(layout), section_state=jdump(state), answers="{}", marked="[]", times="{}", ip=ip)
    session.add(a)
    session.commit()
    session.refresh(a)
    return a


def attempt_questions(session: Session, a: Attempt) -> List[dict]:
    """Questions of this attempt in the order the student sees them (each carries its section_id)."""
    layout = jload(a.layout, {"sections": [], "perms": {}})
    _, qmap, _ = load_exam_content(session, a.exam_id)
    out = []
    for sec in layout["sections"]:
        for qid in sec["qids"]:
            if qid in qmap:
                qd = dict(qmap[qid])
                qd["section_id"] = sec["id"]
                out.append(qd)
    return out


def student_question(qd: dict, perm: List[int]) -> dict:
    return {"id": qd["id"], "section_id": qd["section_id"], "type": qd["qtype"], "text": qd["text"],
            "choices": [{"i": i, "t": qd["choices"][i]} for i in perm if i < len(qd["choices"])], "marks": qd["marks"]}


def apply_time_rules(session: Session, a: Attempt, exam: Exam) -> Attempt:
    """Server-authoritative clock: lazily close timed-out sections and auto-submit expired attempts."""
    if a.status == "submitted":
        return a
    n = utcnow()
    if a.status == "in_progress" and n > a.expires_at + timedelta(seconds=config.SUBMIT_GRACE_SECONDS):
        return finalize_attempt(session, a, exam, "timeout")
    state = jload(a.section_state)
    if state:
        before = jdump(state)
        timing.advance(state, n)
        if jdump(state) != before:
            a.section_state = jdump(state)
            session.add(a)
            session.commit()
    return a


def credit_time(session: Session, a: Attempt, seconds: int):
    if seconds <= 0:
        return
    a.expires_at = a.expires_at + timedelta(seconds=seconds)
    a.total_paused_seconds = (a.total_paused_seconds or 0) + seconds
    a.offline_credit_seconds = (a.offline_credit_seconds or 0) + seconds
    state = jload(a.section_state)
    if state:
        a.section_state = jdump(timing.shift_deadlines(state, seconds))
    session.add(a)


def cap_remaining(a: Attempt) -> int:
    return max(0, config.OFFLINE_CREDIT_CAP_SECONDS - (a.offline_credit_seconds or 0))


def resume_attempt(session: Session, a: Attempt) -> int:
    """Leave 'paused'. The pause is credited only up to the per-attempt cap. Returns seconds credited."""
    if a.status != "paused" or not a.paused_at:
        return 0
    paused = int((utcnow() - a.paused_at).total_seconds())
    credit = min(paused, cap_remaining(a))
    credit_time(session, a, credit)
    a.paused_at = None
    a.status = "in_progress"
    session.add(a)
    session.commit()
    return credit


def current_section_info(a: Attempt) -> dict:
    state = jload(a.section_state) or {"timed": False, "order": [], "sections": {}}
    return state


def attempt_state(session: Session, a: Attempt, exam: Exam, user: User) -> dict:
    layout = jload(a.layout, {"sections": [], "perms": {}})
    state = current_section_info(a)
    secs = {s.id: s for s in sections_of(session, exam.id)}
    qlist = {q["id"]: q for q in attempt_questions(session, a)}
    sections, questions = [], []
    timed = state.get("timed")
    active = timing.active_section(state) if timed else None
    for sec in layout["sections"]:
        sid = str(sec["id"])
        meta = secs.get(sec["id"])
        st = state["sections"].get(sid, {"status": "active", "deadline": None})
        sections.append({"id": sec["id"], "name": meta.name if meta else "Section", "qtype": meta.qtype if meta else "mixed",
                         "duration_min": meta.duration_min if meta else None, "count": len(sec["qids"]),
                         "status": st["status"] if timed else "active", "deadline": st.get("deadline")})
        if timed and active != sid:
            continue
        for qid in sec["qids"]:
            if qid in qlist:
                questions.append(student_question(qlist[qid], layout["perms"].get(str(qid), [])))
    return {
        "attempt": {"id": a.id, "status": a.status, "is_practice": a.is_practice, "expires_at": iso(a.expires_at),
                    "started_at": iso(a.started_at), "server_time": iso(utcnow()), "timed_sections": bool(timed),
                    "offline_credit_seconds": a.offline_credit_seconds or 0,
                    "offline_credit_cap": config.OFFLINE_CREDIT_CAP_SECONDS},
        "exam": {**exam_dict(exam), "snapshot_interval": exam.snapshot_interval, "max_violations": exam.max_violations,
                 "total_questions": sum(len(s["qids"]) for s in layout["sections"])},
        "sections": sections, "questions": questions,
        "answers": jload(a.answers, {}), "marked": jload(a.marked, []), "times": jload(a.times, {}),
        "violations": a.violations,
    }


def merge_progress(a: Attempt, marked: Optional[List[int]], times: Optional[Dict[str, float]]):
    if marked is not None:
        a.marked = jdump(sorted({int(x) for x in marked}))
    if times:
        cur = jload(a.times, {})
        for k, v in times.items():
            cur[str(k)] = max(float(cur.get(str(k), 0)), min(float(v), 36000))   # time only ever grows
        a.times = jdump(cur)


def save_answer(session: Session, a: Attempt, qd: dict, value) -> None:
    """Validate and store one answer. Raises HTTPException on invalid input. Caller commits."""
    answers = jload(a.answers, {})
    if value is None or (isinstance(value, str) and value.strip() == ""):
        answers.pop(str(qd["id"]), None)
    elif qd["qtype"] in ("mcq", "tf"):
        try:
            idx = int(value)
        except (TypeError, ValueError):
            raise HTTPException(status_code=422, detail="Answer must be an option number")
        if not 0 <= idx < len(qd["choices"]):
            raise HTTPException(status_code=422, detail="Option out of range")
        answers[str(qd["id"])] = idx
    else:
        text = str(value).strip()
        if len(text) > 500:
            raise HTTPException(status_code=422, detail="Answer too long")
        answers[str(qd["id"])] = text
    a.answers = jdump(answers)
    session.add(a)


def answerable_question(session: Session, a: Attempt, qid: int) -> dict:
    """The question must belong to this attempt's layout and its section must currently accept answers."""
    for q in attempt_questions(session, a):
        if q["id"] == qid:
            state = jload(a.section_state) or {"timed": False, "sections": {}}
            if not timing.answerable(state, q["section_id"]):
                raise HTTPException(status_code=409, detail="This section is not open")
            return q
    raise HTTPException(status_code=404, detail="Question not in this attempt")


# ------------------------------------------------------------------ finishing
def cheating_for(session: Session, attempt_id: int) -> int:
    types = session.exec(select(ProctorEvent.type).where(ProctorEvent.attempt_id == attempt_id)).all()
    return cheating.cheating_score(types)


def finalize_attempt(session: Session, a: Attempt, exam: Exam, reason: str) -> Attempt:
    if a.status == "submitted":
        return a
    n = utcnow()
    qlist = attempt_questions(session, a)
    answers = jload(a.answers, {})
    res = scoring.score_attempt(qlist, answers, exam.negative_mark)
    a.finished_at = min(n, a.expires_at) if reason == "timeout" else n
    a.status = "submitted"
    a.paused_at = None
    a.submit_reason = reason
    a.score, a.max_score, a.percent = res["score"], res["max_score"], res["percent"]
    a.correct_count, a.wrong_count, a.unanswered_count = res["correct"], res["wrong"], res["unanswered"]
    a.result = jdump({"per_question": res["per_question"], "by_topic": res["by_topic"], "by_section": res["by_section"]})
    state = jload(a.section_state)
    if state:
        for s in state["sections"].values():
            s["status"] = "finished"
        a.section_state = jdump(state)
    a.cheating_score = cheating_for(session, a.id)
    session.add(a)
    session.commit()
    session.refresh(a)
    if not a.is_practice:
        events.publish(f"exam:{a.exam_id}:rank", {"type": "rank"})
        events.publish(f"exam:{a.exam_id}:proctor", {"type": "submitted", "attempt_id": a.id, "score": a.score, "reason": reason})
    return a


def record_event(session: Session, a: Attempt, exam: Exam, etype: str, detail: Optional[str] = None, ts: Optional[datetime] = None) -> bool:
    """Store a proctoring event. Returns True when this event caused an automatic submit."""
    if etype not in cheating.ALLOWED_EVENT_TYPES:
        raise HTTPException(status_code=422, detail=f"Unknown event type '{etype}'")
    if a.is_practice or a.status == "submitted":
        return False
    count = session.exec(select(ProctorEvent.id).where(ProctorEvent.attempt_id == a.id)).all()
    if len(count) >= MAX_EVENTS_PER_ATTEMPT:
        return False
    ev = ProctorEvent(attempt_id=a.id, exam_id=a.exam_id, type=etype, detail=(detail or "")[:300] or None, ts=ts or utcnow())
    session.add(ev)
    session.flush()
    a.cheating_score = cheating_for(session, a.id)
    if etype in VIOLATION_TYPES:
        a.violations = (a.violations or 0) + 1
    session.add(a)
    session.commit()
    doc = {"type": "event", "attempt_id": a.id, "exam_id": a.exam_id, "event": etype, "detail": ev.detail,
           "ts": iso(ev.ts), "cheating_score": a.cheating_score, "violations": a.violations}
    events.publish(f"exam:{a.exam_id}:proctor", doc)
    events.mirror_event(doc)
    if exam.max_violations and a.violations >= exam.max_violations:
        finalize_attempt(session, a, exam, "violations")
        return True
    return False


def save_snapshot(session: Session, a: Attempt, image_b64: str, label: Optional[str] = None):
    import base64
    from .storage import get_storage
    if a.is_practice:
        return None
    if "," in image_b64:
        image_b64 = image_b64.split(",", 1)[1]
    try:
        data = base64.b64decode(image_b64, validate=False)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid base64 image")
    if len(data) > config.MAX_SNAPSHOT_BYTES:
        raise HTTPException(status_code=413, detail="Snapshot too large")
    if not (data[:3] == b"\xff\xd8\xff" or data[:8] == b"\x89PNG\r\n\x1a\n"):
        raise HTTPException(status_code=400, detail="Snapshot must be a JPEG or PNG")
    n_existing = len(session.exec(select(Snapshot.id).where(Snapshot.attempt_id == a.id)).all())
    if n_existing >= config.MAX_SNAPSHOTS_PER_ATTEMPT:
        return None
    ext = "jpg" if data[:3] == b"\xff\xd8\xff" else "png"
    key = f"snapshots/{a.exam_id}/{a.id}/{int(utcnow().timestamp() * 1000)}_{random.SystemRandom().randrange(16 ** 6):06x}.{ext}"
    get_storage().put(key, data, "image/jpeg" if ext == "jpg" else "image/png")
    snap = Snapshot(attempt_id=a.id, key=key, label=(label or None))
    session.add(snap)
    session.commit()
    return snap


# ------------------------------------------------------------------ results
def result_summary(a: Attempt, exam: Exam) -> dict:
    return {"attempt_id": a.id, "exam_id": exam.id, "exam_title": exam.title, "status": a.status, "is_practice": a.is_practice,
            "score": a.score, "max_score": a.max_score, "percent": a.percent, "correct": a.correct_count,
            "wrong": a.wrong_count, "unanswered": a.unanswered_count, "passed": (a.percent or 0) >= exam.pass_percent,
            "pass_percent": exam.pass_percent, "started_at": iso(a.started_at), "finished_at": iso(a.finished_at),
            "seconds": elapsed_seconds(a), "submit_reason": a.submit_reason, "cheating_score": a.cheating_score,
            "cheating_level": cheating.level(a.cheating_score or 0), "violations": a.violations,
            "offline_credit_seconds": a.offline_credit_seconds or 0}


def review_items(session: Session, a: Attempt, reveal_answers: bool) -> List[dict]:
    layout = jload(a.layout, {"perms": {}})
    res = (jload(a.result) or {}).get("per_question", {})
    answers, times = jload(a.answers, {}), jload(a.times, {})
    out = []
    for qd in attempt_questions(session, a):
        qid = str(qd["id"])
        perm = layout["perms"].get(qid, [])
        item = {"id": qd["id"], "text": qd["text"], "type": qd["qtype"], "section_id": qd["section_id"], "marks": qd["marks"],
                "choices": [{"i": i, "t": qd["choices"][i]} for i in perm if i < len(qd["choices"])],
                "given": answers.get(qid), "given_text": given_text(qd, answers.get(qid)),
                "status": res.get(qid, {}).get("status", "unanswered"), "awarded": res.get(qid, {}).get("awarded", 0),
                "time": round(times.get(qid, 0)), "tags": qd["tags"], "subject": qd["subject"], "difficulty": qd["difficulty"]}
        if reveal_answers:
            item.update({"correct": qd["correct"], "correct_text": correct_text(qd), "explanation": qd["explanation"]})
        out.append(item)
    return out


def leaderboard(session: Session, exam: Exam, limit: int = 50) -> List[dict]:
    rows = session.exec(select(Attempt, User).where(Attempt.exam_id == exam.id, Attempt.is_practice == False,  # noqa: E712
                                                    Attempt.status == "submitted", Attempt.user_id == User.id)).all()
    rows = sorted(rows, key=lambda r: (-(r[0].score or 0), elapsed_seconds(r[0])))[:limit]
    return [{"rank": i + 1, "user_id": u.id, "name": u.name or u.email.split("@")[0], "score": a.score, "max_score": a.max_score,
             "percent": a.percent, "seconds": elapsed_seconds(a)} for i, (a, u) in enumerate(rows)]


def certificate_code(a: Attempt) -> str:
    sig = hmac.new(config.SECRET_KEY.encode(), f"{a.id}:{a.exam_id}:{a.user_id}:{a.score}".encode(), hashlib.sha256).hexdigest()[:8].upper()
    return f"CERT-{a.exam_id}-{a.id}-{sig}"
