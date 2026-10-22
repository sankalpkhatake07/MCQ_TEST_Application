import json
import secrets
import time
import urllib.request
from datetime import datetime, timedelta
from typing import Dict, Optional

import bcrypt
from jose import jwt

from . import config


def hash_secret(s: str) -> str:
    return bcrypt.hashpw(s.encode(), bcrypt.gensalt()).decode()


def check_secret(s: str, hashed: Optional[str]) -> bool:
    if not hashed:
        return False
    try:
        return bcrypt.checkpw(s.encode(), hashed.encode())
    except ValueError:
        return False


def make_token(claims: Dict, minutes: int) -> str:
    exp = datetime.utcnow() + timedelta(minutes=minutes)
    return jwt.encode({**claims, "exp": int(exp.timestamp())}, config.SECRET_KEY, algorithm=config.ALGORITHM)


def read_token(token: str, typ: str) -> Dict:
    data = jwt.decode(token, config.SECRET_KEY, algorithms=[config.ALGORITHM])
    if data.get("typ", "access") != typ:
        raise ValueError("wrong token type")
    return data


def new_session_id() -> str:
    return secrets.token_hex(16)


def new_otp() -> str:
    return f"{secrets.randbelow(10 ** 6):06d}"


def validate_password(pw: str) -> Optional[str]:
    if len(pw or "") < 8:
        return "Password must be at least 8 characters"
    if pw.lower() == pw or not any(c.isdigit() for c in pw):
        return "Password needs an uppercase letter and a digit"
    return None


# ---- OpenID Connect ID-token verification (Google / Microsoft) -------------------------------------------
_JWKS_CACHE: Dict[str, tuple] = {}
GOOGLE_JWKS = "https://www.googleapis.com/oauth2/v3/certs"


def _jwks(url: str) -> Dict:
    hit = _JWKS_CACHE.get(url)
    if hit and time.time() - hit[0] < 3600:
        return hit[1]
    with urllib.request.urlopen(url, timeout=8) as r:  # noqa: S310 (fixed https URLs)
        keys = json.loads(r.read())
    _JWKS_CACHE[url] = (time.time(), keys)
    return keys


def verify_google(id_token: str) -> Dict:
    if not config.GOOGLE_CLIENT_ID:
        raise ValueError("Google login is not configured")
    claims = jwt.decode(id_token, _jwks(GOOGLE_JWKS), algorithms=["RS256"], audience=config.GOOGLE_CLIENT_ID,
                        options={"verify_at_hash": False})
    if claims.get("iss") not in ("https://accounts.google.com", "accounts.google.com"):
        raise ValueError("bad issuer")
    if not claims.get("email_verified"):
        raise ValueError("Google email is not verified")
    return {"email": claims["email"].lower(), "name": claims.get("name")}


def verify_microsoft(id_token: str, nonce: Optional[str]) -> Dict:
    if not config.MICROSOFT_CLIENT_ID:
        raise ValueError("Microsoft login is not configured")
    keys = _jwks(f"https://login.microsoftonline.com/{config.MICROSOFT_TENANT}/discovery/v2.0/keys")
    claims = jwt.decode(id_token, keys, algorithms=["RS256"], audience=config.MICROSOFT_CLIENT_ID,
                        options={"verify_at_hash": False, "verify_iss": False})
    if not str(claims.get("iss", "")).startswith("https://login.microsoftonline.com/"):
        raise ValueError("bad issuer")
    if config.MICROSOFT_TENANT not in ("common", "organizations", "consumers") and claims.get("tid") != config.MICROSOFT_TENANT:
        raise ValueError("wrong tenant")
    if nonce and claims.get("nonce") != nonce:
        raise ValueError("bad nonce")
    email = (claims.get("email") or claims.get("preferred_username") or "").lower()
    if "@" not in email:
        raise ValueError("No email in Microsoft token")
    return {"email": email, "name": claims.get("name")}
