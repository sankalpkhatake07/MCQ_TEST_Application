from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from sqlmodel import Session

from ..core import analytics, cheating, reports
from ..db import get_session
from ..deps import get_current_user, teacher_or_admin
from ..models import Attempt, Exam, ProctorEvent, User, jload
from .. import services as svc
from .teacher import attempt_rows
from sqlmodel import select

router = APIRouter(prefix="/api", tags=["reports"])
PDF = "application/pdf"


def _dl(data: bytes, mime: str, name: str) -> Response:
    try:   # keep a copy of every generated report in the configured storage (local / S3 / Azure / GCS)
        from datetime import datetime as _dt
        from ..storage import get_storage
        get_storage().put(f"reports/{_dt.utcnow():%Y/%m/%d}/{name}", data, mime)
    except Exception:
        pass
    return Response(data, media_type=mime, headers={"Content-Disposition": f'attachment; filename="{name}"'})


def _slug(s: str) -> str:
    return "".join(c if c.isalnum() else "-" for c in s).strip("-")[:40] or "report"


def _access(session: Session, user: User, attempt_id: int):
    a = session.get(Attempt, attempt_id)
    if not a:
        raise HTTPException(status_code=404, detail="Attempt not found")
    exam = session.get(Exam, a.exam_id)
    staff = svc.can_manage(user, exam)
    if not staff and a.user_id != user.id:
        raise HTTPException(status_code=404, detail="Attempt not found")
    if a.status != "submitted":
        raise HTTPException(status_code=409, detail="Attempt not submitted yet")
    if not staff and not exam.show_result and not a.is_practice:
        raise HTTPException(status_code=403, detail="Results are not released for this exam yet")
    return a, exam, staff


@router.get("/attempts/{attempt_id}/report.pdf")
def student_report(attempt_id: int, user: User = Depends(get_current_user), session: Session = Depends(get_session)):
    a, exam, staff = _access(session, user, attempt_id)
    student = session.get(User, a.user_id)
    reveal = staff or exam.show_answers or a.is_practice
    items = svc.review_items(session, a, True)
    qs = [{"text": i["text"], "given": i["given_text"], "correct_text": i["correct_text"] if reveal else "(hidden)",
           "status": i["status"], "awarded": i["awarded"], "time": i["time"], "explanation": i.get("explanation") if reveal else None} for i in items]
    evs = session.exec(select(ProctorEvent).where(ProctorEvent.attempt_id == a.id).order_by(ProctorEvent.ts)).all()
    summ = svc.result_summary(a, exam)
    data = {"exam": {"title": exam.title, "pass_percent": exam.pass_percent},
            "student": {"name": student.name, "email": student.email, "roll_no": student.roll_no}, "result": summ,
            "topics": jload(a.result, {}).get("by_topic", {}), "questions": qs,
            "cheating": {"score": a.cheating_score or 0, "level": cheating.level(a.cheating_score or 0)} if (staff or not a.is_practice) else None,
            "events": [{"ts": svc.iso(e.ts), "type": e.type, "detail": e.detail} for e in evs]}
    return _dl(reports.student_report_pdf(data), PDF, f"report-{_slug(exam.title)}-{a.id}.pdf")


@router.get("/attempts/{attempt_id}/certificate.pdf")
def certificate(attempt_id: int, user: User = Depends(get_current_user), session: Session = Depends(get_session)):
    a, exam, staff = _access(session, user, attempt_id)
    if a.is_practice or not exam.certificate_enabled:
        raise HTTPException(status_code=403, detail="No certificate for this attempt")
    if (a.percent or 0) < exam.pass_percent:
        raise HTTPException(status_code=403, detail=f"A score of at least {exam.pass_percent:g}% is needed for a certificate")
    student = session.get(User, a.user_id)
    pdf = reports.certificate_pdf({"name": student.name or student.email, "exam_title": exam.title, "percent": a.percent, "score": a.score,
                                   "max_score": a.max_score, "date": (a.finished_at or datetime.utcnow()).strftime("%d %B %Y"),
                                   "code": svc.certificate_code(a)})
    return _dl(pdf, PDF, f"certificate-{_slug(exam.title)}-{a.id}.pdf")


@router.get("/certificates/verify/{code}")
def verify_certificate(code: str, session: Session = Depends(get_session)):
    """Public: confirm that a certificate code was issued by this system."""
    parts = code.split("-")
    if len(parts) != 4 or parts[0] != "CERT" or not parts[2].isdigit():
        raise HTTPException(status_code=404, detail="Invalid certificate code")
    a = session.get(Attempt, int(parts[2]))
    if not a or a.is_practice or a.status != "submitted" or svc.certificate_code(a) != code:
        raise HTTPException(status_code=404, detail="Certificate not found")
    exam, student = session.get(Exam, a.exam_id), session.get(User, a.user_id)
    return {"valid": True, "name": student.name or student.email, "exam": exam.title, "percent": a.percent, "date": svc.iso(a.finished_at)}


def _exam_report_data(session: Session, exam: Exam):
    rows = attempt_rows(session, exam, include_in_progress=False)
    _, qmap, _ = svc.load_exam_content(session, exam.id)
    qs = [{**q, "correct_text": svc.correct_text(q)} for q in qmap.values()]
    atts = []
    for r in rows:
        a = r.pop("_a")
        answers = jload(a.answers, {})
        r["answers_text"] = {str(q["id"]): svc.given_text(q, answers.get(str(q["id"]))) for q in qs}
        r["finished_at"] = svc.iso(a.finished_at)
        atts.append({"score": a.score or 0, "per_question": jload(a.result, {}).get("per_question", {}), "times": jload(a.times, {})})
    ins = analytics.insights([{"score": r["score"], "percent": r["percent"], "seconds": r["seconds"]} for r in rows], exam.pass_percent)
    items = analytics.item_analysis([{"id": q["id"], "text": q["text"], "difficulty": q["difficulty"]} for q in qs], atts)
    return {"exam": {"title": exam.title, "pass_percent": exam.pass_percent}, "attempts": rows, "insights": ins, "items": items, "questions": qs}


@router.get("/exams/{exam_id}/report.pdf")
def exam_report(exam_id: int, user: User = Depends(teacher_or_admin), session: Session = Depends(get_session)):
    exam = svc.get_exam_or_404(session, exam_id)
    if not svc.can_manage(user, exam):
        raise HTTPException(status_code=404, detail="Exam not found")
    return _dl(reports.exam_report_pdf(_exam_report_data(session, exam)), PDF, f"results-{_slug(exam.title)}.pdf")


@router.get("/exams/{exam_id}/export.xlsx")
def exam_export(exam_id: int, user: User = Depends(teacher_or_admin), session: Session = Depends(get_session)):
    exam = svc.get_exam_or_404(session, exam_id)
    if not svc.can_manage(user, exam):
        raise HTTPException(status_code=404, detail="Exam not found")
    return _dl(reports.exam_xlsx(_exam_report_data(session, exam)),
               "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", f"results-{_slug(exam.title)}.xlsx")
