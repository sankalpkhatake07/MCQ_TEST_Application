import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")


def _bool(name: str, default: bool) -> bool:
    return os.getenv(name, str(default)).strip().lower() in ("1", "true", "yes", "on")


def _int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, default))
    except ValueError:
        return default


def _list(name: str, default: str = "") -> list:
    return [x.strip() for x in os.getenv(name, default).split(",") if x.strip()]


BASE_DIR = Path(__file__).resolve().parent.parent
SECRET_KEY = os.getenv("SECRET_KEY", "change-me")
ALGORITHM = "HS256"
TOKEN_HOURS = _int("TOKEN_HOURS", 8)
DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{BASE_DIR / 'data' / 'mcq.db'}")
CORS_ORIGINS = _list("CORS_ORIGINS", "http://localhost:8000,http://127.0.0.1:8000,http://localhost:3000,http://127.0.0.1:3000")
FRONTEND_DIR = os.getenv("FRONTEND_DIR", str(BASE_DIR.parent / "frontend"))
ENV = os.getenv("ENV", "development")

# --- auth
ALLOW_SEND_EMAIL = _bool("ALLOW_SEND_EMAIL", False)
DEV_SHOW_OTP = _bool("DEV_SHOW_OTP", False)      # development only: return the OTP in the API response
SMTP_HOST, SMTP_PORT = os.getenv("SMTP_HOST"), _int("SMTP_PORT", 587)
SMTP_USER, SMTP_PASS = os.getenv("SMTP_USER"), os.getenv("SMTP_PASS")
FROM_EMAIL = os.getenv("FROM_EMAIL", SMTP_USER or "no-reply@example.com")
OTP_TTL_MIN = _int("OTP_TTL_MIN", 10)
OTP_MAX_ATTEMPTS = _int("OTP_MAX_ATTEMPTS", 5)
OTP_RESEND_SECONDS = _int("OTP_RESEND_SECONDS", 30)
ALLOW_SELF_REGISTRATION = _bool("ALLOW_SELF_REGISTRATION", True)   # new emails become students on first login
ALLOW_OTP_ONLY_LOGIN = _bool("ALLOW_OTP_ONLY_LOGIN", True)
SINGLE_SESSION_ROLES = set(_list("SINGLE_SESSION_ROLES", "student"))
GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "")
MICROSOFT_CLIENT_ID = os.getenv("MICROSOFT_CLIENT_ID", "")
MICROSOFT_TENANT = os.getenv("MICROSOFT_TENANT", "common")
ADMIN_EMAIL = os.getenv("ADMIN_EMAIL", "admin@example.com")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "admin123")
SEED_DEV_USERS = _bool("SEED_DEV_USERS", True)

# --- exam behaviour
TRUST_PROXY = _bool("TRUST_PROXY", False)          # honour X-Forwarded-For (set true behind nginx)
OFFLINE_CREDIT_CAP_SECONDS = _int("OFFLINE_CREDIT_CAP_SECONDS", 600)
SUBMIT_GRACE_SECONDS = _int("SUBMIT_GRACE_SECONDS", 5)
SWEEP_INTERVAL_SECONDS = _int("SWEEP_INTERVAL_SECONDS", 30)
MAX_SNAPSHOT_BYTES = _int("MAX_SNAPSHOT_BYTES", 400_000)
MAX_UPLOAD_BYTES = _int("MAX_UPLOAD_BYTES", 8_000_000)
MAX_SNAPSHOTS_PER_ATTEMPT = _int("MAX_SNAPSHOTS_PER_ATTEMPT", 400)

# --- storage (local | s3 | azure | gcs)
STORAGE_BACKEND = os.getenv("STORAGE_BACKEND", "local").lower()
STORAGE_DIR = os.getenv("STORAGE_DIR", str(BASE_DIR / "storage"))
S3_BUCKET, S3_REGION, S3_ENDPOINT = os.getenv("S3_BUCKET"), os.getenv("S3_REGION"), os.getenv("S3_ENDPOINT_URL")
AZURE_CONNECTION_STRING, AZURE_CONTAINER = os.getenv("AZURE_STORAGE_CONNECTION_STRING"), os.getenv("AZURE_CONTAINER", "mcq")
GCS_BUCKET = os.getenv("GCS_BUCKET")

# --- scale-out
REDIS_URL = os.getenv("REDIS_URL", "")
MONGO_URL = os.getenv("MONGO_URL", "")
MONGO_DB = os.getenv("MONGO_DB", "mcq")

LANGUAGES = {"en": "English", "hi": "हिन्दी", "mr": "मराठी"}
