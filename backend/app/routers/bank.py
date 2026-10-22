import secrets
from typing import List, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import Response
from sqlmodel import Session, select

from .. import config
from ..core import importers
from ..core.sanitize import to_rich
from ..db import get_session
from ..deps import teacher_or_admin
from ..models import Exam, ExamQuestion, ExamSection, Question, User, jdump, jload
from ..schemas import QuestionIn
from ..services import assert_editable, can_manage, q_dict
from ..storage import get_storage

router = APIRouter(prefix="/api", tags=["bank"])
IMAGE_TYPES = {b"\x89PNG\r\n\x1a\n": "png", b"\xff\xd8\xff": "jpg", b"GIF8": "gif"}


def _owned(session: Session, user: User, qid: int) -> Question:
    q = session.get(Question, qid)
    if not q or (user.role != "admin" and q.owner_id != user.id):
        raise HTTPException(status_code=404, detail="Question not found")
    return q


def _in_started_exam(session: Session, qid: int) -> bool:
    from ..models import Attempt
    exam_ids = [e for e in session.exec(select(ExamQuestion.exam_id).where(ExamQuestion.question_id == qid)).all()]
    if not exam_ids:
        return False
    return session.exec(select(Attempt.id).where(Attempt.exam_id.in_(exam_ids), Attempt.is_practice == False)).first() is not None  # noqa: E712


def _apply(q: Question, item: dict):
    q.text, q.qtype = to_rich(item["text"]), item["qtype"]
    q.choices, q.correct = jdump(item["choices"]), jdump(item["correct"])
    q.difficulty, q.subject = item["difficulty"], item["subject"] or None
    q.tags, q.marks = jdump(item["tags"]), item["marks"]
    q.explanation = to_rich(item["explanation"]) if item["explanation"] else None


def _validated(payload: QuestionIn) -> dict:
    item, err = importers.normalise_item(
        {"text": payload.text, "choices": payload.choices, "correct": payload.correct, "qtype": payload.qtype,
         "difficulty": payload.difficulty, "subject": payload.subject, "tags": payload.tags, "marks": payload.marks,
         "explanation": payload.explanation}, {}, "Question")
    if err:
        raise HTTPException(status_code=422, detail=err)
    return item


@router.get("/bank")
def list_bank(subject: Optional[str] = None, tag: Optional[str] = None, difficulty: Optional[str] = None,
              qtype: Optional[str] = None, q: Optional[str] = None, page: int = Query(1, ge=1), size: int = Query(25, ge=1, le=100),
              user: User = Depends(teacher_or_admin), session: Session = Depends(get_session)):
    stmt = select(Question)
    if user.role != "admin":
        stmt = stmt.where(Question.owner_id == user.id)
    if subject:
        stmt = stmt.where(Question.subject == subject)
    if difficulty:
        stmt = stmt.where(Question.difficulty == difficulty)
    if qtype:
        stmt = stmt.where(Question.qtype == qtype)
    rows = session.exec(stmt.order_by(Question.id.desc())).all()
    if tag:
        rows = [r for r in rows if tag in jload(r.tags, [])]
    if q:
        rows = [r for r in rows if q.lower() in r.text.lower()]
    total = len(rows)
    rows = rows[(page - 1) * size: page * size]
    return {"total": total, "page": page, "size": size, "items": [q_dict(r) for r in rows]}


@router.get("/bank/meta")
def bank_meta(user: User = Depends(teacher_or_admin), session: Session = Depends(get_session)):
    stmt = select(Question)
    if user.role != "admin":
        stmt = stmt.where(Question.owner_id == user.id)
    rows = session.exec(stmt).all()
    subjects = sorted({r.subject for r in rows if r.subject})
    tags = sorted({t for r in rows for t in jload(r.tags, [])})
    counts = {"easy": 0, "medium": 0, "hard": 0}
    for r in rows:
        counts[r.difficulty] = counts.get(r.difficulty, 0) + 1
    return {"subjects": subjects, "tags": tags, "total": len(rows), "by_difficulty": counts}


@router.post("/bank")
def create_question(payload: QuestionIn, user: User = Depends(teacher_or_admin), session: Session = Depends(get_session)):
    q = Question(owner_id=user.id, text="")
    _apply(q, _validated(payload))
    session.add(q)
    session.commit()
    session.refresh(q)
    return q_dict(q)


@router.put("/bank/{qid}")
def update_question(qid: int, payload: QuestionIn, user: User = Depends(teacher_or_admin), session: Session = Depends(get_session)):
    q = _owned(session, user, qid)
    if _in_started_exam(session, qid):
        raise HTTPException(status_code=409, detail="This question is part of an exam students have started. Duplicate it instead of editing.")
    _apply(q, _validated(payload))
    session.add(q)
    session.commit()
    return q_dict(q)


@router.delete("/bank/{qid}")
def delete_question(qid: int, user: User = Depends(teacher_or_admin), session: Session = Depends(get_session)):
    q = _owned(session, user, qid)
    if _in_started_exam(session, qid):
        raise HTTPException(status_code=409, detail="This question is part of an exam students have started and cannot be deleted.")
    for eq in session.exec(select(ExamQuestion).where(ExamQuestion.question_id == qid)).all():
        session.delete(eq)
    session.delete(q)
    session.commit()
    return {"detail": "deleted"}


async def import_into(session: Session, user: User, file: UploadFile, subject: Optional[str], tags: Optional[str],
                      difficulty: Optional[str], exam: Optional[Exam], section_id: Optional[int]) -> dict:
    data = await file.read()
    if len(data) > config.MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="File too large")
    defaults = {"subject": subject, "tags": tags, "difficulty": difficulty}
    try:
        items, errors = importers.parse_upload(file.filename or "", data, defaults)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Could not read the file: {e}")
    section = None
    if exam is not None:
        assert_editable(session, exam)
        secs = session.exec(select(ExamSection).where(ExamSection.exam_id == exam.id).order_by(ExamSection.position, ExamSection.id)).all()
        section = next((s for s in secs if s.id == section_id), secs[0] if secs else None)
        if section is None:
            raise HTTPException(status_code=409, detail="Exam has no section")
    pos = 0
    if exam is not None:
        pos = len(session.exec(select(ExamQuestion.id).where(ExamQuestion.exam_id == exam.id)).all())
    created = []
    for it in items:
        q = Question(owner_id=user.id, text="")
        _apply(q, it)
        session.add(q)
        session.flush()
        created.append(q.id)
        if exam is not None:
            session.add(ExamQuestion(exam_id=exam.id, section_id=section.id, question_id=q.id, position=pos))
            pos += 1
    session.commit()
    return {"created": len(created), "skipped": len(errors), "errors": errors[:50], "question_ids": created}


@router.post("/bank/import")
async def import_bank(file: UploadFile = File(...), subject: Optional[str] = Form(None), tags: Optional[str] = Form(None),
                      difficulty: Optional[str] = Form(None), exam_id: Optional[int] = Form(None), section_id: Optional[int] = Form(None),
                      user: User = Depends(teacher_or_admin), session: Session = Depends(get_session)):
    exam = None
    if exam_id:
        exam = session.get(Exam, exam_id)
        if not exam or not can_manage(user, exam):
            raise HTTPException(status_code=404, detail="Exam not found")
    return await import_into(session, user, file, subject, tags, difficulty, exam, section_id)


@router.post("/bank/images")
async def upload_image(file: UploadFile = File(...), user: User = Depends(teacher_or_admin)):
    data = await file.read()
    if len(data) > 2_000_000:
        raise HTTPException(status_code=413, detail="Image must be under 2 MB")
    ext = next((e for magic, e in IMAGE_TYPES.items() if data.startswith(magic)), None)
    if ext is None and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        ext = "webp"
    if ext is None:
        raise HTTPException(status_code=400, detail="Only PNG, JPEG, GIF or WebP images are allowed")
    name = f"{secrets.token_hex(16)}.{ext}"
    get_storage().put(f"media/{name}", data, f"image/{'jpeg' if ext == 'jpg' else ext}")
    return {"url": f"/api/media/{name}"}


@router.get("/media/{name}")
def get_media(name: str):
    import re
    if not re.fullmatch(r"[a-f0-9]{32}\.(png|jpg|gif|webp)", name):
        raise HTTPException(status_code=404, detail="Not found")
    try:
        data = get_storage().get(f"media/{name}")
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Not found")
    ext = name.rsplit(".", 1)[1]
    return Response(data, media_type=f"image/{'jpeg' if ext == 'jpg' else ext}",
                    headers={"Cache-Control": "public, max-age=86400", "X-Content-Type-Options": "nosniff"})
