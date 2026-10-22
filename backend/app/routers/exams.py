import random
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from sqlmodel import Session, select

from .. import config
from ..core.netutil import invalid_rules, ip_allowed
from ..db import get_session
from ..deps import get_current_user, get_ip, teacher_or_admin
from ..models import (Attempt, Exam, ExamQuestion, ExamSection, ProctorEvent, Question, Snapshot, User, jdump, jload, utcnow)
from ..schemas import AddQuestionsIn, AutoGenIn, ExamIn, ExamQuestionPatch, SectionsIn
from .. import services as svc
from ..storage import get_storage
from .bank import import_into

router = APIRouter(prefix="/api/exams", tags=["exams"])
DT_FIELDS = {"start_at", "end_at", "visible_from"}


def _mine(session: Session, user: User, exam_id: int) -> Exam:
    exam = svc.get_exam_or_404(session, exam_id)
    if not svc.can_manage(user, exam):
        raise HTTPException(status_code=404, detail="Exam not found")
    return exam


def _apply_exam(exam: Exam, payload: ExamIn):
    data = payload.model_dump(exclude_unset=True)
    for k, v in data.items():
        if k in DT_FIELDS:
            setattr(exam, k, svc.parse_dt(v))
        elif k == "allowed_ips":
            rules = [x.strip() for x in (v or []) if x.strip()]
            bad = invalid_rules(rules)
            if bad:
                raise HTTPException(status_code=422, detail=f"Invalid IP/CIDR: {', '.join(bad)}")
            exam.allowed_ips = jdump(rules) if rules else None
        elif k == "languages":
            langs = [x for x in (v or []) if x in config.LANGUAGES] or ["en"]
            exam.languages = jdump(langs)
        elif k == "title":
            if not (v or "").strip():
                raise HTTPException(status_code=422, detail="Title cannot be empty")
            exam.title = v.strip()
        elif v is not None:
            setattr(exam, k, v)
    if exam.start_at and exam.end_at and exam.end_at <= exam.start_at:
        raise HTTPException(status_code=422, detail="End time must be after the start time")


def _exam_full(session: Session, exam: Exam) -> dict:
    secs, qmap, pools = svc.load_exam_content(session, exam.id)
    d = svc.exam_dict(exam, full=True)
    d["sections"] = [{"id": s.id, "name": s.name, "qtype": s.qtype, "duration_min": s.duration_min, "pick_count": s.pick_count,
                      "position": s.position, "question_ids": pools[s.id]} for s in secs]
    d["questions"] = [qmap[qid] for s in secs for qid in pools[s.id]]
    d["locked"] = svc.has_real_attempts(session, exam.id)
    d["attempt_count"] = len(session.exec(select(Attempt.id).where(Attempt.exam_id == exam.id, Attempt.is_practice == False)).all())  # noqa: E712
    return d


@router.post("")
def create_exam(payload: ExamIn, user: User = Depends(teacher_or_admin), session: Session = Depends(get_session)):
    if not (payload.title or "").strip():
        raise HTTPException(status_code=422, detail="Title is required")
    exam = Exam(title=payload.title.strip(), owner_id=user.id, duration_min=payload.duration_min or 20)
    _apply_exam(exam, payload)
    session.add(exam)
    session.commit()
    session.refresh(exam)
    session.add(ExamSection(exam_id=exam.id, name="Section A", position=0))
    session.commit()
    return _exam_full(session, exam)


@router.get("")
def list_exams(user: User = Depends(get_current_user), session: Session = Depends(get_session)):
    n = utcnow()
    if user.role == "student":
        exams = [e for e in session.exec(select(Exam).where(Exam.published == True).order_by(Exam.id.desc())).all()  # noqa: E712
                 if not e.visible_from or e.visible_from <= n]
        mine = {}
        for a in session.exec(select(Attempt).where(Attempt.user_id == user.id, Attempt.is_practice == False)).all():  # noqa: E712
            mine[a.exam_id] = a
        out = []
        for e in exams:
            d = svc.exam_dict(e)
            a = mine.get(e.id)
            d["my_attempt"] = {"id": a.id, "status": a.status, "percent": a.percent if e.show_result else None} if a else None
            d["can_practice"] = bool(e.practice_enabled and (d["status"] == "closed" or (a and a.status == "submitted")))
            out.append(d)
        return out
    stmt = select(Exam).order_by(Exam.id.desc())
    if user.role != "admin":
        stmt = stmt.where(Exam.owner_id == user.id)
    out = []
    for e in session.exec(stmt).all():
        d = svc.exam_dict(e, full=True)
        d["question_count"] = len(session.exec(select(ExamQuestion.id).where(ExamQuestion.exam_id == e.id)).all())
        atts = session.exec(select(Attempt).where(Attempt.exam_id == e.id, Attempt.is_practice == False)).all()  # noqa: E712
        d["attempt_count"] = len(atts)
        d["submitted_count"] = sum(1 for a in atts if a.status == "submitted")
        out.append(d)
    return out


@router.get("/{exam_id}")
def get_exam(exam_id: int, user: User = Depends(get_current_user), session: Session = Depends(get_session)):
    exam = svc.get_exam_or_404(session, exam_id)
    if svc.can_manage(user, exam):
        return _exam_full(session, exam)
    if not exam.published or (exam.visible_from and exam.visible_from > utcnow()):
        raise HTTPException(status_code=404, detail="Exam not found")
    d = svc.exam_dict(exam)
    _, qmap, _ = svc.load_exam_content(session, exam.id)
    d["question_count"] = len(qmap)
    a = session.exec(select(Attempt).where(Attempt.exam_id == exam.id, Attempt.user_id == user.id, Attempt.is_practice == False)).first()  # noqa: E712
    d["my_attempt"] = {"id": a.id, "status": a.status} if a else None
    d["can_practice"] = bool(exam.practice_enabled and (d["status"] == "closed" or (a and a.status == "submitted")))
    return d


@router.patch("/{exam_id}")
def update_exam(exam_id: int, payload: ExamIn, user: User = Depends(teacher_or_admin), session: Session = Depends(get_session)):
    exam = _mine(session, user, exam_id)
    locked_fields = {"negative_mark", "shuffle_questions", "shuffle_options"}
    if svc.has_real_attempts(session, exam.id) and locked_fields & set(payload.model_dump(exclude_unset=True)):
        raise HTTPException(status_code=409, detail="Scoring and shuffle rules are locked once students have started.")
    _apply_exam(exam, payload)
    session.add(exam)
    session.commit()
    return _exam_full(session, exam)


@router.post("/{exam_id}/publish")
def publish(exam_id: int, body: dict, user: User = Depends(teacher_or_admin), session: Session = Depends(get_session)):
    exam = _mine(session, user, exam_id)
    want = bool(body.get("published", True))
    if want:
        _, qmap, _ = svc.load_exam_content(session, exam.id)
        if not qmap:
            raise HTTPException(status_code=409, detail="Add at least one question before publishing")
    exam.published = want
    if want:
        exam.closed_manual = False
    session.add(exam)
    session.commit()
    return _exam_full(session, exam)


@router.post("/{exam_id}/close")
def close(exam_id: int, body: dict, user: User = Depends(teacher_or_admin), session: Session = Depends(get_session)):
    exam = _mine(session, user, exam_id)
    exam.closed_manual = bool(body.get("closed", True))
    session.add(exam)
    session.commit()
    return _exam_full(session, exam)


@router.delete("/{exam_id}")
def delete_exam(exam_id: int, user: User = Depends(teacher_or_admin), session: Session = Depends(get_session)):
    exam = _mine(session, user, exam_id)
    store = get_storage()
    for a in session.exec(select(Attempt).where(Attempt.exam_id == exam.id)).all():
        for s in session.exec(select(Snapshot).where(Snapshot.attempt_id == a.id)).all():
            try:
                store.delete(s.key)
            except Exception:
                pass
            session.delete(s)
        for ev in session.exec(select(ProctorEvent).where(ProctorEvent.attempt_id == a.id)).all():
            session.delete(ev)
        session.delete(a)
    for model in (ExamQuestion, ExamSection):
        for row in session.exec(select(model).where(model.exam_id == exam.id)).all():
            session.delete(row)
    session.delete(exam)
    session.commit()
    return {"detail": "deleted"}


# ---------------------------------------------------------------- sections & questions
@router.put("/{exam_id}/sections")
def put_sections(exam_id: int, payload: SectionsIn, user: User = Depends(teacher_or_admin), session: Session = Depends(get_session)):
    exam = _mine(session, user, exam_id)
    svc.assert_editable(session, exam)
    if not payload.sections:
        raise HTTPException(status_code=422, detail="An exam needs at least one section")
    existing = {s.id: s for s in svc.sections_of(session, exam.id)}
    keep, kept_ids = [], set()
    for pos, s in enumerate(payload.sections):
        row = existing.get(s.id) if s.id else None
        if row is None:
            row = ExamSection(exam_id=exam.id)
        row.name, row.qtype, row.duration_min, row.pick_count, row.position = s.name.strip() or "Section", s.qtype, s.duration_min, s.pick_count, pos
        session.add(row)
        session.flush()
        keep.append(row)
        kept_ids.add(row.id)
    target = keep[0].id
    for sid, row in existing.items():
        if sid not in kept_ids:
            for eq in session.exec(select(ExamQuestion).where(ExamQuestion.section_id == sid)).all():
                eq.section_id = target     # questions of a removed section move to the first section
                session.add(eq)
            session.delete(row)
    session.commit()
    return _exam_full(session, exam)


def _section_or_first(session: Session, exam: Exam, section_id: Optional[int]) -> ExamSection:
    secs = svc.sections_of(session, exam.id)
    sec = next((s for s in secs if s.id == section_id), None) if section_id else (secs[0] if secs else None)
    if sec is None:
        raise HTTPException(status_code=404, detail="Section not found")
    return sec


@router.get("/{exam_id}/questions")
def exam_questions(exam_id: int, user: User = Depends(get_current_user), session: Session = Depends(get_session)):
    exam = svc.get_exam_or_404(session, exam_id)
    if not svc.can_manage(user, exam):
        raise HTTPException(status_code=403, detail="Questions are delivered through an exam attempt")
    return _exam_full(session, exam)["questions"]


@router.post("/{exam_id}/questions")
async def upload_questions(exam_id: int, file: UploadFile = File(...), section_id: Optional[int] = Form(None),
                           subject: Optional[str] = Form(None), tags: Optional[str] = Form(None), difficulty: Optional[str] = Form(None),
                           user: User = Depends(teacher_or_admin), session: Session = Depends(get_session)):
    """Upload CSV / JSON / PDF / DOCX. Questions are saved to your bank and attached to this exam."""
    exam = _mine(session, user, exam_id)
    return await import_into(session, user, file, subject, tags, difficulty, exam, section_id)


@router.post("/{exam_id}/questions/add")
def add_questions(exam_id: int, payload: AddQuestionsIn, user: User = Depends(teacher_or_admin), session: Session = Depends(get_session)):
    exam = _mine(session, user, exam_id)
    svc.assert_editable(session, exam)
    sec = _section_or_first(session, exam, payload.section_id)
    have = {eq.question_id for eq in session.exec(select(ExamQuestion).where(ExamQuestion.exam_id == exam.id)).all()}
    pos = len(have)
    added = 0
    for qid in payload.question_ids:
        q = session.get(Question, qid)
        if not q or (user.role != "admin" and q.owner_id != user.id) or qid in have:
            continue
        session.add(ExamQuestion(exam_id=exam.id, section_id=sec.id, question_id=qid, position=pos))
        have.add(qid)
        pos += 1
        added += 1
    session.commit()
    return {"added": added}


@router.patch("/{exam_id}/questions/{qid}")
def patch_exam_question(exam_id: int, qid: int, payload: ExamQuestionPatch, user: User = Depends(teacher_or_admin),
                        session: Session = Depends(get_session)):
    exam = _mine(session, user, exam_id)
    svc.assert_editable(session, exam)
    eq = session.exec(select(ExamQuestion).where(ExamQuestion.exam_id == exam.id, ExamQuestion.question_id == qid)).first()
    if not eq:
        raise HTTPException(status_code=404, detail="Question not in this exam")
    if payload.section_id is not None:
        eq.section_id = _section_or_first(session, exam, payload.section_id).id
    if payload.marks is not None:
        eq.marks = payload.marks
    session.add(eq)
    session.commit()
    return {"detail": "updated"}


@router.delete("/{exam_id}/questions/{qid}")
def remove_question(exam_id: int, qid: int, user: User = Depends(teacher_or_admin), session: Session = Depends(get_session)):
    exam = _mine(session, user, exam_id)
    svc.assert_editable(session, exam)
    for eq in session.exec(select(ExamQuestion).where(ExamQuestion.exam_id == exam.id, ExamQuestion.question_id == qid)).all():
        session.delete(eq)
    session.commit()
    return {"detail": "removed"}


@router.post("/{exam_id}/auto-generate")
def auto_generate(exam_id: int, payload: AutoGenIn, user: User = Depends(teacher_or_admin), session: Session = Depends(get_session)):
    """Balanced exam: pick N easy / M medium / K hard questions at random from your bank."""
    exam = _mine(session, user, exam_id)
    svc.assert_editable(session, exam)
    sec = _section_or_first(session, exam, payload.section_id)
    if payload.replace:
        for eq in session.exec(select(ExamQuestion).where(ExamQuestion.section_id == sec.id)).all():
            session.delete(eq)
        session.flush()
    have = {eq.question_id for eq in session.exec(select(ExamQuestion).where(ExamQuestion.exam_id == exam.id)).all()}
    stmt = select(Question)
    if user.role != "admin":
        stmt = stmt.where(Question.owner_id == user.id)
    if payload.subject:
        stmt = stmt.where(Question.subject == payload.subject)
    if payload.qtype:
        stmt = stmt.where(Question.qtype == payload.qtype)
    pool = [q for q in session.exec(stmt).all() if q.id not in have and (not payload.tags or set(payload.tags) & set(jload(q.tags, [])))]
    picked, shortfall = [], {}
    pos = len(have)
    for diff, want in (("easy", payload.easy), ("medium", payload.medium), ("hard", payload.hard)):
        cands = [q for q in pool if q.difficulty == diff]
        take = random.sample(cands, min(want, len(cands)))
        if len(take) < want:
            shortfall[diff] = want - len(take)
        picked += take
    for q in picked:
        session.add(ExamQuestion(exam_id=exam.id, section_id=sec.id, question_id=q.id, position=pos))
        pos += 1
    session.commit()
    return {"added": len(picked), "shortfall": shortfall}


# ---------------------------------------------------------------- starting an attempt
@router.post("/{exam_id}/start")
def start_attempt(exam_id: int, request: Request, practice: bool = False, user: User = Depends(get_current_user),
                  session: Session = Depends(get_session)):
    exam = svc.get_exam_or_404(session, exam_id)
    ip = get_ip(request)
    staff = svc.can_manage(user, exam)
    if user.role != "student" and not staff:
        raise HTTPException(status_code=403, detail="Only students can start this exam")
    if not staff:
        if not exam.published or (exam.visible_from and exam.visible_from > utcnow()):
            raise HTTPException(status_code=404, detail="Exam not found")
    status = svc.exam_status(exam)
    if staff:
        practice = True                     # teachers preview exams as a practice attempt
    resp = lambda a: {"attempt_id": a.id, "status": a.status, "is_practice": a.is_practice,  # noqa: E731
                      "expires_at": svc.iso(a.expires_at), "server_time": svc.iso(utcnow())}
    if practice:
        if not staff:
            mine = session.exec(select(Attempt).where(Attempt.exam_id == exam.id, Attempt.user_id == user.id,
                                                      Attempt.is_practice == False)).first()  # noqa: E712
            if not exam.practice_enabled or not (status == "closed" or (mine and mine.status == "submitted")):
                raise HTTPException(status_code=403, detail="Practice opens after the exam ends or after you submit it.")
        live = session.exec(select(Attempt).where(Attempt.exam_id == exam.id, Attempt.user_id == user.id, Attempt.is_practice == True,  # noqa: E712
                                                  Attempt.status != "submitted")).first()
        if live:
            svc.apply_time_rules(session, live, exam)
            if live.status != "submitted":
                return resp(live)
        return resp(svc.create_attempt(session, exam, user, True, ip))
    if status == "draft":
        raise HTTPException(status_code=404, detail="Exam not found")
    if not ip_allowed(ip, jload(exam.allowed_ips, [])):
        raise HTTPException(status_code=403, detail="ip_not_allowed: this exam can only be taken from the approved network.")
    existing = session.exec(select(Attempt).where(Attempt.exam_id == exam.id, Attempt.user_id == user.id, Attempt.is_practice == False)).first()  # noqa: E712
    if existing:
        svc.apply_time_rules(session, existing, exam)
        if existing.status == "submitted":
            raise HTTPException(status_code=409, detail=f"already_submitted:{existing.id}")
        if existing.ip and ip and existing.ip != ip:
            svc.record_event(session, existing, exam, "ip_change", f"{existing.ip} -> {ip}")
        return resp(existing)
    if status == "upcoming":
        raise HTTPException(status_code=409, detail=f"not_started:{svc.iso(exam.start_at)}")
    if status == "closed":
        raise HTTPException(status_code=409, detail="This exam is closed.")
    return resp(svc.create_attempt(session, exam, user, False, ip))


@router.get("/{exam_id}/leaderboard")
def get_leaderboard(exam_id: int, user: User = Depends(get_current_user), session: Session = Depends(get_session)):
    exam = svc.get_exam_or_404(session, exam_id)
    if not svc.can_manage(user, exam) and not (exam.published and exam.live_ranking):
        raise HTTPException(status_code=403, detail="Ranking is not enabled for this exam")
    rows = svc.leaderboard(session, exam)
    return {"exam_id": exam.id, "title": exam.title, "rows": rows, "me": next((r for r in rows if r["user_id"] == user.id), None)}
