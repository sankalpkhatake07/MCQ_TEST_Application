"""Request bodies (responses are plain dicts so datetimes are always serialised as UTC ISO strings with 'Z')."""
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, EmailStr, Field


class OTPRequestIn(BaseModel):
    email: EmailStr


class OTPVerifyIn(BaseModel):
    email: EmailStr
    code: str = Field(min_length=4, max_length=10)
    challenge: Optional[str] = None


class PasswordLoginIn(BaseModel):
    email: EmailStr
    password: str


class OIDCIn(BaseModel):
    id_token: str
    nonce: Optional[str] = None


class SetPasswordIn(BaseModel):
    password: str
    current_password: Optional[str] = None


class MFAIn(BaseModel):
    enabled: bool


class ExamIn(BaseModel):
    title: Optional[str] = Field(default=None, max_length=200)
    description: Optional[str] = None
    instructions: Optional[str] = None
    duration_min: Optional[int] = Field(default=None, ge=1, le=600)
    start_at: Optional[str] = None
    end_at: Optional[str] = None
    visible_from: Optional[str] = None
    strict_end: Optional[bool] = None
    negative_mark: Optional[float] = Field(default=None, ge=0, le=1)
    pass_percent: Optional[float] = Field(default=None, ge=0, le=100)
    shuffle_questions: Optional[bool] = None
    shuffle_options: Optional[bool] = None
    show_result: Optional[bool] = None
    show_answers: Optional[bool] = None
    lockdown: Optional[bool] = None
    fullscreen_required: Optional[bool] = None
    max_violations: Optional[int] = Field(default=None, ge=0, le=100)
    camera_required: Optional[bool] = None
    mic_enabled: Optional[bool] = None
    ai_proctoring: Optional[bool] = None
    snapshot_interval: Optional[int] = Field(default=None, ge=10, le=600)
    allowed_ips: Optional[List[str]] = None
    practice_enabled: Optional[bool] = None
    live_ranking: Optional[bool] = None
    certificate_enabled: Optional[bool] = None
    languages: Optional[List[str]] = None


class SectionIn(BaseModel):
    id: Optional[int] = None
    name: str = Field(max_length=80)
    qtype: str = "mixed"
    duration_min: Optional[int] = Field(default=None, ge=1, le=600)
    pick_count: Optional[int] = Field(default=None, ge=1, le=1000)


class SectionsIn(BaseModel):
    sections: List[SectionIn]


class AddQuestionsIn(BaseModel):
    question_ids: List[int]
    section_id: Optional[int] = None


class ExamQuestionPatch(BaseModel):
    section_id: Optional[int] = None
    marks: Optional[float] = Field(default=None, gt=0, le=100)


class AutoGenIn(BaseModel):
    section_id: Optional[int] = None
    easy: int = Field(default=0, ge=0, le=500)
    medium: int = Field(default=0, ge=0, le=500)
    hard: int = Field(default=0, ge=0, le=500)
    subject: Optional[str] = None
    tags: Optional[List[str]] = None
    qtype: Optional[str] = None
    replace: bool = False


class QuestionIn(BaseModel):
    text: str = Field(min_length=1, max_length=20000)
    qtype: str = "mcq"
    choices: List[str] = []
    correct: Any = None
    difficulty: str = "medium"
    subject: Optional[str] = None
    tags: List[str] = []
    marks: float = Field(default=1.0, gt=0, le=100)
    explanation: Optional[str] = None


class AnswerIn(BaseModel):
    question_id: int
    value: Any = None                      # option index (original) or text; null clears the answer
    time_spent: Optional[float] = Field(default=None, ge=0, le=36000)
    marked: Optional[bool] = None


class SyncAnswer(BaseModel):
    question_id: int
    value: Any = None
    ts: Optional[float] = None


class SyncEvent(BaseModel):
    type: str
    detail: Optional[str] = None
    ts: Optional[float] = None


class SyncSnapshot(BaseModel):
    image: str
    label: Optional[str] = None
    ts: Optional[float] = None


class SyncIn(BaseModel):
    answers: List[SyncAnswer] = []
    marked: Optional[List[int]] = None
    times: Optional[Dict[str, float]] = None
    events: List[SyncEvent] = []
    snapshots: List[SyncSnapshot] = []
    offline_seconds: float = 0


class HeartbeatIn(BaseModel):
    times: Optional[Dict[str, float]] = None
    marked: Optional[List[int]] = None


class EventIn(BaseModel):
    type: str
    detail: Optional[str] = Field(default=None, max_length=300)


class SnapshotIn(BaseModel):
    image: str
    label: Optional[str] = Field(default=None, max_length=60)


class UserIn(BaseModel):
    email: EmailStr
    name: Optional[str] = None
    roll_no: Optional[str] = None
    role: str = "student"
    password: Optional[str] = None
    mfa_enabled: bool = False
    active: bool = True


class UserPatch(BaseModel):
    name: Optional[str] = None
    roll_no: Optional[str] = None
    role: Optional[str] = None
    password: Optional[str] = None
    mfa_enabled: Optional[bool] = None
    active: Optional[bool] = None
