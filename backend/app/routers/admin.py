import csv
import io
from typing import Optional

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import EmailStr, TypeAdapter, ValidationError
from sqlmodel import Session, select

from .. import config, security
from ..db import get_session
from ..deps import admin_only, teacher_or_admin, user_dict
from ..models import Attempt, Exam, Question, User
from ..schemas import UserIn, UserPatch
from .. import services as svc

router = APIRouter(prefix="/api", tags=["admin"])
ROLES = {"student", "teacher", "admin"}
_email = TypeAdapter(EmailStr)


@router.get("/admin/users")
def list_users(role: Optional[str] = None, q: Optional[str] = None, user: User = Depends(admin_only), session: Session = Depends(get_session)):
    rows = session.exec(select(User).order_by(User.id)).all()
    if role:
        rows = [u for u in rows if u.role == role]
    if q:
        rows = [u for u in rows if q.lower() in (u.email + " " + (u.name or "") + " " + (u.roll_no or "")).lower()]
    return [{**user_dict(u), "last_login": svc.iso(u.last_login), "created_at": svc.iso(u.created_at)} for u in rows]


@router.post("/admin/users")
def create_user(p: UserIn, user: User = Depends(admin_only), session: Session = Depends(get_session)):
    if p.role not in ROLES:
        raise HTTPException(status_code=422, detail="Role must be student, teacher or admin")
    if session.exec(select(User).where(User.email == p.email.lower())).first():
        raise HTTPException(status_code=409, detail="A user with this email already exists")
    u = User(email=p.email.lower(), name=p.name, roll_no=p.roll_no, role=p.role, mfa_enabled=p.mfa_enabled, active=p.active)
    if p.password:
        err = security.validate_password(p.password)
        if err:
            raise HTTPException(status_code=422, detail=err)
        u.password_hash = security.hash_secret(p.password)
    session.add(u)
    session.commit()
    session.refresh(u)
    return user_dict(u)


@router.patch("/admin/users/{uid}")
def patch_user(uid: int, p: UserPatch, user: User = Depends(admin_only), session: Session = Depends(get_session)):
    u = session.get(User, uid)
    if not u:
        raise HTTPException(status_code=404, detail="User not found")
    data = p.model_dump(exclude_unset=True)
    if u.id == user.id and (data.get("role", u.role) != "admin" or data.get("active") is False):
        raise HTTPException(status_code=409, detail="You cannot demote or disable your own account")
    if "role" in data and data["role"] not in ROLES:
        raise HTTPException(status_code=422, detail="Role must be student, teacher or admin")
    if data.get("password"):
        err = security.validate_password(data["password"])
        if err:
            raise HTTPException(status_code=422, detail=err)
        u.password_hash = security.hash_secret(data.pop("password"))
    else:
        data.pop("password", None)
    for k, v in data.items():
        setattr(u, k, v)
    if "role" in data or data.get("active") is False:
        u.session_id = security.new_session_id()       # sign them out everywhere
    session.add(u)
    session.commit()
    return user_dict(u)


@router.delete("/admin/users/{uid}")
def delete_user(uid: int, user: User = Depends(admin_only), session: Session = Depends(get_session)):
    u = session.get(User, uid)
    if not u:
        raise HTTPException(status_code=404, detail="User not found")
    if u.id == user.id:
        raise HTTPException(status_code=409, detail="You cannot delete your own account")
    if session.exec(select(Attempt.id).where(Attempt.user_id == u.id)).first() or session.exec(select(Exam.id).where(Exam.owner_id == u.id)).first():
        raise HTTPException(status_code=409, detail="This user has exams or attempts. Disable the account instead of deleting it.")
    session.delete(u)
    session.commit()
    return {"detail": "deleted"}


@router.get("/students")
def list_students(q: Optional[str] = None, user: User = Depends(teacher_or_admin), session: Session = Depends(get_session)):
    rows = session.exec(select(User).where(User.role == "student").order_by(User.name, User.email)).all()
    if q:
        rows = [u for u in rows if q.lower() in (u.email + " " + (u.name or "") + " " + (u.roll_no or "")).lower()]
    return [{"id": u.id, "name": u.name, "email": u.email, "roll_no": u.roll_no, "active": u.active} for u in rows[:500]]


@router.post("/students/bulk")
async def bulk_students(file: UploadFile = File(...), user: User = Depends(teacher_or_admin), session: Session = Depends(get_session)):
    """CSV with columns: name, email, roll_no. Existing emails are updated (name/roll_no), never downgraded or promoted."""
    data = await file.read()
    if len(data) > config.MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="File too large")
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = data.decode("latin-1")
    created = updated = 0
    errors = []
    seen = set()
    for n, row in enumerate(csv.DictReader(io.StringIO(text)), start=2):
        row = {(k or "").strip().lower().replace(" ", "_"): (v or "").strip() for k, v in row.items()}
        raw = row.get("email", "")
        try:
            email = str(_email.validate_python(raw)).lower()
        except ValidationError:
            errors.append(f"Row {n}: '{raw}' is not a valid email")
            continue
        if email in seen:
            errors.append(f"Row {n}: duplicate email {email} in this file")
            continue
        seen.add(email)
        name, roll = row.get("name") or None, row.get("roll_no") or row.get("roll") or row.get("rollno") or None
        u = session.exec(select(User).where(User.email == email)).first()
        if u:
            if u.role != "student":
                errors.append(f"Row {n}: {email} is a {u.role}; skipped")
                continue
            u.name, u.roll_no = name or u.name, roll or u.roll_no
            session.add(u)
            updated += 1
        else:
            session.add(User(email=email, name=name, roll_no=roll, role="student"))
            created += 1
    session.commit()
    return {"created": created, "updated": updated, "errors": errors[:50], "skipped": len(errors)}


@router.get("/admin/exams")
def all_exams(user: User = Depends(admin_only), session: Session = Depends(get_session)):
    owners = {u.id: u for u in session.exec(select(User)).all()}
    out = []
    for e in session.exec(select(Exam).order_by(Exam.id.desc())).all():
        d = svc.exam_dict(e, full=True)
        d["owner"] = (owners.get(e.owner_id).name or owners.get(e.owner_id).email) if owners.get(e.owner_id) else None
        d["attempt_count"] = len(session.exec(select(Attempt.id).where(Attempt.exam_id == e.id, Attempt.is_practice == False)).all())  # noqa: E712
        out.append(d)
    return out


@router.get("/admin/stats")
def stats(user: User = Depends(admin_only), session: Session = Depends(get_session)):
    users = session.exec(select(User)).all()
    return {"users": len(users), "students": sum(u.role == "student" for u in users), "teachers": sum(u.role == "teacher" for u in users),
            "admins": sum(u.role == "admin" for u in users), "exams": len(session.exec(select(Exam.id)).all()),
            "questions": len(session.exec(select(Question.id)).all()), "attempts": len(session.exec(select(Attempt.id)).all()),
            "storage_backend": config.STORAGE_BACKEND, "redis": bool(config.REDIS_URL), "mongo_mirror": bool(config.MONGO_URL),
            "database": config.DATABASE_URL.split(":", 1)[0]}
