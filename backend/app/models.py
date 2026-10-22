"""Database tables. JSON-ish columns are stored as TEXT (portable across SQLite/PostgreSQL/MySQL)."""
import json
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import Column, Index, Text
from sqlmodel import Field, SQLModel


def utcnow() -> datetime:
    """Naive UTC datetime (all stored times are UTC; the API serialises them with a trailing Z)."""
    return datetime.utcnow()


def jload(s: Optional[str], default: Any = None):
    if not s:
        return default
    try:
        return json.loads(s)
    except (TypeError, ValueError):
        return default


def jdump(v: Any) -> str:
    return json.dumps(v, ensure_ascii=False)


class User(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    email: str = Field(index=True, unique=True)
    name: Optional[str] = None
    roll_no: Optional[str] = Field(default=None, index=True)
    role: str = "student"                       # student | teacher | admin
    password_hash: Optional[str] = None
    mfa_enabled: bool = False
    active: bool = True
    session_id: Optional[str] = None            # rotated on each login (single-session enforcement)
    provider: Optional[str] = None
    created_at: datetime = Field(default_factory=utcnow)
    last_login: Optional[datetime] = None


class OTP(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    email: str = Field(index=True)
    code_hash: str
    purpose: str = "login"
    expires_at: datetime
    attempts: int = 0
    used: bool = False
    created_at: datetime = Field(default_factory=utcnow)


class Exam(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    title: str
    description: Optional[str] = None
    instructions: Optional[str] = None
    owner_id: Optional[int] = Field(default=None, index=True)
    duration_min: int = 20
    published: bool = False
    closed_manual: bool = False
    start_at: Optional[datetime] = None
    end_at: Optional[datetime] = None
    visible_from: Optional[datetime] = None
    strict_end: bool = True                      # cap each attempt at end_at
    negative_mark: float = 0.0                   # fraction of marks lost on a wrong answer
    pass_percent: float = 40.0
    shuffle_questions: bool = False
    shuffle_options: bool = False
    show_result: bool = True                     # show score straight after submit
    show_answers: bool = False                   # reveal answers/explanations after submit
    lockdown: bool = False
    fullscreen_required: bool = False
    max_violations: int = 0                      # 0 = never auto-submit
    camera_required: bool = False
    mic_enabled: bool = False
    ai_proctoring: bool = False
    snapshot_interval: int = 30
    allowed_ips: Optional[str] = None            # JSON list
    practice_enabled: bool = False
    live_ranking: bool = False
    certificate_enabled: bool = False
    languages: Optional[str] = None              # JSON list of allowed UI languages
    created_at: datetime = Field(default_factory=utcnow)


class ExamSection(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    exam_id: int = Field(index=True)
    name: str = "Section A"
    qtype: str = "mixed"                         # informational: mcq | tf | fill | mixed
    duration_min: Optional[int] = None           # per-section timer (sections become sequential)
    pick_count: Optional[int] = None             # "pick N random questions from the pool"
    position: int = 0


class Question(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    owner_id: Optional[int] = Field(default=None, index=True)
    subject: Optional[str] = Field(default=None, index=True)
    tags: Optional[str] = None                   # JSON list
    difficulty: str = Field(default="medium", index=True)
    qtype: str = "mcq"                           # mcq | tf | fill
    text: str = Field(sa_column=Column(Text))    # sanitised HTML
    choices: Optional[str] = None                # JSON list[str]
    correct: Optional[str] = None                # JSON: int (mcq/tf) or list[str] (fill)
    explanation: Optional[str] = None
    marks: float = 1.0
    created_at: datetime = Field(default_factory=utcnow)


class ExamQuestion(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    exam_id: int = Field(index=True)
    section_id: int = Field(index=True)
    question_id: int = Field(index=True)
    position: int = 0
    marks: Optional[float] = None                # per-exam override


class Attempt(SQLModel, table=True):
    __table_args__ = (Index("ix_attempt_exam_user", "exam_id", "user_id"),)
    id: Optional[int] = Field(default=None, primary_key=True)
    exam_id: int = Field(index=True)
    user_id: int = Field(index=True)
    is_practice: bool = False
    started_at: datetime = Field(default_factory=utcnow)
    expires_at: datetime
    finished_at: Optional[datetime] = None
    status: str = "in_progress"                  # in_progress | paused | submitted
    paused_at: Optional[datetime] = None
    total_paused_seconds: int = 0
    offline_credit_seconds: int = 0
    last_seen: datetime = Field(default_factory=utcnow)
    seed: int = 0
    layout: Optional[str] = None                 # JSON from core.shuffle.build_layout
    section_state: Optional[str] = None          # JSON from core.timing
    answers: Optional[str] = None                # JSON {qid: original option index | text}
    marked: Optional[str] = None                 # JSON [qid]
    times: Optional[str] = None                  # JSON {qid: seconds}
    score: Optional[float] = None
    max_score: Optional[float] = None
    percent: Optional[float] = None
    correct_count: Optional[int] = None
    wrong_count: Optional[int] = None
    unanswered_count: Optional[int] = None
    result: Optional[str] = None                 # JSON per-question + topic breakdown
    cheating_score: int = 0
    violations: int = 0
    ip: Optional[str] = None
    submit_reason: Optional[str] = None          # manual | timeout | violations


class ProctorEvent(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    attempt_id: int = Field(index=True)
    exam_id: int = Field(index=True)
    type: str = Field(index=True)
    detail: Optional[str] = None
    ts: datetime = Field(default_factory=utcnow)


class Snapshot(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    attempt_id: int = Field(index=True)
    key: str
    label: Optional[str] = None                  # e.g. the event that triggered it
    created_at: datetime = Field(default_factory=utcnow)
