import asyncio
import logging
import os
from contextlib import asynccontextmanager
from datetime import timedelta

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from sqlmodel import Session, select

from . import config, events, security, services as svc
from .db import engine, init_db, startup_lock
from .models import Attempt, Exam, ExamQuestion, ExamSection, Question, User, jdump, utcnow
from .routers import admin, attempts, auth, bank, exams, live, reports, teacher

log = logging.getLogger("mcq")


def seed():
    with Session(engine) as s:
        if not s.exec(select(User).where(User.email == config.ADMIN_EMAIL.lower())).first():
            s.add(User(email=config.ADMIN_EMAIL.lower(), name="Administrator", role="admin", password_hash=security.hash_secret(config.ADMIN_PASSWORD)))
            s.commit()
            log.warning("Created admin %s (change the password!)", config.ADMIN_EMAIL)
        if not config.SEED_DEV_USERS:
            return
        teacher = s.exec(select(User).where(User.email == "teacher@example.com")).first()
        if not teacher:
            teacher = User(email="teacher@example.com", name="Dev Teacher", role="teacher")
            s.add(teacher)
        if not s.exec(select(User).where(User.email == "student@example.com")).first():
            s.add(User(email="student@example.com", name="Demo Student", roll_no="DEMO-001", role="student"))
        s.commit()
        s.refresh(teacher)
        if s.exec(select(Exam.id)).first() is None:
            _seed_demo(s, teacher)


def _seed_demo(s: Session, teacher: User):
    """A small, ready-to-run demo exam so every feature can be tried straight away."""
    def mcq(text, ch, ans, diff, tags, expl=""):
        return Question(owner_id=teacher.id, subject="Python", tags=jdump(tags), difficulty=diff, qtype="mcq",
                        text=f"<p>{text}</p>", choices=jdump(ch), correct=jdump(ans), explanation=f"<p>{expl}</p>" if expl else None)
    qs = [
        mcq("What is the output of <code>print(1 + 1)</code>?", ["1", "2", "11", "Error"], 1, "easy", ["Basics"], "Integer addition."),
        mcq("Which keyword defines a function?", ["fn", "function", "def", "func"], 2, "easy", ["Functions"]),
        mcq("Which of these is immutable?", ["list", "dict", "set", "tuple"], 3, "medium", ["Data types"]),
        mcq("What does <code>len([1, 2, 3])</code> return?", ["2", "3", "4", "None"], 1, "easy", ["Lists"]),
        mcq("Which loop is best when the number of iterations is known?", ["while", "for", "do-while", "repeat"], 1, "medium", ["Loops"]),
        mcq("What is <code>2 ** 3</code>?", ["6", "8", "9", "5"], 1, "easy", ["Basics"]),
        mcq("Which method adds an item to the end of a list?", ["add", "insert_end", "append", "push"], 2, "medium", ["Lists"]),
        mcq("What is the time complexity of dict lookup on average?", ["O(1)", "O(n)", "O(log n)", "O(n log n)"], 0, "hard", ["Data types"]),
        Question(owner_id=teacher.id, subject="Python", tags=jdump(["Basics"]), difficulty="easy", qtype="tf", text="<p>Python is case-sensitive.</p>",
                 choices=jdump(["True", "False"]), correct=jdump(0)),
        Question(owner_id=teacher.id, subject="Python", tags=jdump(["Functions"]), difficulty="medium", qtype="tf",
                 text="<p>A function must always return a value.</p>", choices=jdump(["True", "False"]), correct=jdump(1),
                 explanation="<p>Functions return <code>None</code> when there is no return statement.</p>"),
        Question(owner_id=teacher.id, subject="Python", tags=jdump(["Basics"]), difficulty="easy", qtype="fill",
                 text="<p>The built-in function to print output is ____ .</p>", choices=jdump([]), correct=jdump(["print", "print()"])),
        Question(owner_id=teacher.id, subject="Python", tags=jdump(["Loops"]), difficulty="medium", qtype="fill",
                 text="<p>The keyword that skips to the next loop iteration is ____ .</p>", choices=jdump([]), correct=jdump(["continue"])),
    ]
    for q in qs:
        s.add(q)
    s.commit()
    exam = Exam(title="Python Basics (demo)", description="Sample exam created on first run.", owner_id=teacher.id, duration_min=15, published=True,
                negative_mark=0.25, shuffle_questions=True, shuffle_options=True, show_answers=True, practice_enabled=True,
                live_ranking=True, certificate_enabled=True, pass_percent=40, languages=jdump(["en", "hi", "mr"]),
                instructions="Each correct answer earns the question's marks. A wrong answer loses a quarter of them. Unanswered questions score zero.")
    s.add(exam)
    s.commit()
    s.refresh(exam)
    sec_a = ExamSection(exam_id=exam.id, name="Section A - MCQ", qtype="mcq", position=0)
    sec_b = ExamSection(exam_id=exam.id, name="Section B - True / False", qtype="tf", position=1)
    sec_c = ExamSection(exam_id=exam.id, name="Section C - Fill in the blank", qtype="fill", position=2)
    for sec in (sec_a, sec_b, sec_c):
        s.add(sec)
    s.commit()
    for pos, q in enumerate(qs):
        s.refresh(q)
        sec = {"mcq": sec_a, "tf": sec_b, "fill": sec_c}[q.qtype]
        s.add(ExamQuestion(exam_id=exam.id, section_id=sec.id, question_id=q.id, position=pos))
    s.commit()
    log.warning("Seeded demo exam #%s", exam.id)


def sweep_once() -> int:
    """Auto-submit attempts whose time ran out while the student was away; end over-long pauses."""
    n, done = utcnow(), 0
    with Session(engine) as s:
        rows = s.exec(select(Attempt).where(Attempt.status != "submitted")).all()
        for a in rows:
            exam = s.get(Exam, a.exam_id)
            if exam is None:
                continue
            if a.status == "paused" and a.paused_at and (n - a.paused_at).total_seconds() > svc.cap_remaining(a) + 1:
                svc.resume_attempt(s, a)
            if a.status == "in_progress" and n > a.expires_at + timedelta(seconds=config.SUBMIT_GRACE_SECONDS):
                svc.finalize_attempt(s, a, exam, "timeout")
                done += 1
    return done


async def _sweeper():
    while True:
        await asyncio.sleep(config.SWEEP_INTERVAL_SECONDS)
        try:
            await asyncio.to_thread(sweep_once)
        except Exception:
            log.exception("sweep failed")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logging.basicConfig(level=logging.INFO)
    if config.ENV == "production" and config.SECRET_KEY in ("change-me", "change-me-please"):
        raise RuntimeError("Set a strong SECRET_KEY before running in production")
    with startup_lock():
        init_db()
        seed()
    events.bind_loop(asyncio.get_running_loop())
    task = asyncio.create_task(_sweeper())
    yield
    task.cancel()


app = FastAPI(title="ExamHub - MCQ Evaluator", version="2.0.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=config.CORS_ORIGINS, allow_credentials=False, allow_methods=["*"], allow_headers=["*"])


@app.middleware("http")
async def headers(request: Request, call_next):
    resp = await call_next(request)
    resp.headers.setdefault("X-Content-Type-Options", "nosniff")
    resp.headers.setdefault("Referrer-Policy", "same-origin")
    resp.headers.setdefault("Permissions-Policy", "camera=(self), microphone=(self), fullscreen=(self)")
    if request.url.path.startswith("/api/") and "cache-control" not in resp.headers:
        resp.headers["Cache-Control"] = "no-store"
    return resp


for r in (auth.router, exams.router, bank.router, attempts.router, teacher.router, reports.router, admin.router, live.router):
    app.include_router(r)


@app.get("/api/health")
def health():
    return {"status": "ok", "time": svc.iso(utcnow())}


FRONT = config.FRONTEND_DIR
if os.path.isdir(FRONT):
    for sub in ("css", "js", "i18n"):
        if os.path.isdir(os.path.join(FRONT, sub)):
            app.mount(f"/{sub}", StaticFiles(directory=os.path.join(FRONT, sub)), name=sub)
    LEGACY = {"/combined-login.html", "/host-dashboard.html", "/student-start.html", "/test.html"}

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        if path.startswith("api/"):
            return JSONResponse({"detail": "Not found"}, status_code=404)
        f = os.path.join(FRONT, path)
        if path and os.path.isfile(f) and os.path.abspath(f).startswith(os.path.abspath(FRONT)):
            return FileResponse(f)
        if "/" + path in LEGACY:
            return RedirectResponse("/")
        return FileResponse(os.path.join(FRONT, "index.html"))
