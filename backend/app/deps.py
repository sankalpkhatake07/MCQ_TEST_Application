from typing import Optional

from fastapi import Depends, Header, HTTPException, Request
from sqlmodel import Session

from . import config, security
from .core.netutil import client_ip
from .db import get_session
from .models import User


def get_ip(request: Request) -> str:
    peer = request.client.host if request.client else ""
    return client_ip(peer, request.headers.get("x-forwarded-for"), config.TRUST_PROXY)


def get_current_user(authorization: Optional[str] = Header(None), session: Session = Depends(get_session)) -> User:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing token")
    try:
        data = security.read_token(authorization.split(" ", 1)[1], "access")
        uid = int(data["sub"])
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    user = session.get(User, uid)
    if not user or not user.active:
        raise HTTPException(status_code=401, detail="User not found or disabled")
    if user.role in config.SINGLE_SESSION_ROLES and data.get("sid") != user.session_id:
        # someone signed in on another device: this session is locked out
        raise HTTPException(status_code=401, detail="session_replaced")
    return user


def require_roles(*roles: str):
    def dep(user: User = Depends(get_current_user)) -> User:
        if user.role not in roles:
            raise HTTPException(status_code=403, detail="You do not have permission for this action")
        return user
    return dep


teacher_or_admin = require_roles("teacher", "admin")
admin_only = require_roles("admin")


def user_dict(u: User) -> dict:
    return {"id": u.id, "email": u.email, "name": u.name, "roll_no": u.roll_no, "role": u.role,
            "mfa_enabled": u.mfa_enabled, "has_password": bool(u.password_hash), "active": u.active,
            "provider": u.provider}
