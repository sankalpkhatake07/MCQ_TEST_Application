from datetime import timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from .. import config, security
from ..db import get_session
from ..deps import get_current_user, user_dict
from ..mailer import send_otp_email
from ..models import OTP, User, utcnow
from ..schemas import MFAIn, OIDCIn, OTPRequestIn, OTPVerifyIn, PasswordLoginIn, SetPasswordIn

router = APIRouter(prefix="/api/auth", tags=["auth"])


def _find_or_create(session: Session, email: str, name: Optional[str] = None, provider: Optional[str] = None) -> Optional[User]:
    email = email.lower().strip()
    user = session.exec(select(User).where(User.email == email)).first()
    if user is None:
        if not config.ALLOW_SELF_REGISTRATION:
            return None
        user = User(email=email, name=name, role="student", provider=provider)
        session.add(user)
        session.commit()
        session.refresh(user)
    elif name and not user.name:
        user.name = name
        session.add(user)
        session.commit()
    if not user.active:
        raise HTTPException(status_code=403, detail="This account is disabled. Contact your administrator.")
    return user


def _issue_session(session: Session, user: User) -> dict:
    if user.role in config.SINGLE_SESSION_ROLES or not user.session_id:
        user.session_id = security.new_session_id()    # signing in elsewhere locks the old session
    user.last_login = utcnow()
    session.add(user)
    session.commit()
    token = security.make_token({"sub": str(user.id), "sid": user.session_id, "typ": "access"}, config.TOKEN_HOURS * 60)
    return {"access": token, "token_type": "bearer", "user": user_dict(user)}


def _send_otp(session: Session, email: str, purpose: str) -> dict:
    last = session.exec(select(OTP).where(OTP.email == email).order_by(OTP.id.desc())).first()
    if last and (utcnow() - last.created_at).total_seconds() < config.OTP_RESEND_SECONDS:
        wait = config.OTP_RESEND_SECONDS - int((utcnow() - last.created_at).total_seconds())
        raise HTTPException(status_code=429, detail=f"Please wait {wait}s before requesting another code")
    code = security.new_otp()
    session.add(OTP(email=email, code_hash=security.hash_secret(code), purpose=purpose,
                    expires_at=utcnow() + timedelta(minutes=config.OTP_TTL_MIN)))
    session.commit()
    try:
        send_otp_email(email, code)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Could not send the email: {e}")
    out = {"detail": "otp_sent"}
    if config.DEV_SHOW_OTP and not config.ALLOW_SEND_EMAIL:
        out["dev_otp"] = code
    return out


def _after_first_factor(session: Session, user: User) -> dict:
    """Password / Google / Microsoft succeeded. MFA users still owe an OTP."""
    if user.mfa_enabled:
        out = _send_otp(session, user.email, "mfa")
        out.update({"mfa_required": True, "challenge": security.make_token({"sub": user.email, "typ": "mfa"}, 10)})
        return out
    return _issue_session(session, user)


@router.get("/config")
def public_config():
    return {"google_client_id": config.GOOGLE_CLIENT_ID or None, "microsoft_client_id": config.MICROSOFT_CLIENT_ID or None,
            "microsoft_tenant": config.MICROSOFT_TENANT, "allow_otp_only": config.ALLOW_OTP_ONLY_LOGIN,
            "languages": config.LANGUAGES, "dev_otp": config.DEV_SHOW_OTP and not config.ALLOW_SEND_EMAIL}


@router.post("/request-otp")
def request_otp(payload: OTPRequestIn, session: Session = Depends(get_session)):
    if not config.ALLOW_OTP_ONLY_LOGIN:
        raise HTTPException(status_code=403, detail="Sign in with your password instead.")
    email = payload.email.lower()
    user = session.exec(select(User).where(User.email == email)).first()
    if user is None and not config.ALLOW_SELF_REGISTRATION:
        return {"detail": "otp_sent"}               # do not reveal which emails are registered
    if user is not None and (user.mfa_enabled or not user.active):
        raise HTTPException(status_code=403, detail="This account needs password + OTP sign-in.")
    return _send_otp(session, email, "login")


@router.post("/verify-otp")
def verify_otp(payload: OTPVerifyIn, session: Session = Depends(get_session)):
    email = payload.email.lower()
    second_factor = False
    if payload.challenge:
        try:
            data = security.read_token(payload.challenge, "mfa")
        except Exception:
            raise HTTPException(status_code=400, detail="Sign-in step expired. Start again.")
        if data.get("sub") != email:
            raise HTTPException(status_code=400, detail="Sign-in step does not match this email")
        second_factor = True
    elif not config.ALLOW_OTP_ONLY_LOGIN:
        raise HTTPException(status_code=403, detail="Sign in with your password instead.")
    otp = session.exec(select(OTP).where(OTP.email == email, OTP.used == False).order_by(OTP.id.desc())).first()  # noqa: E712
    if not otp or otp.expires_at < utcnow() or otp.attempts >= config.OTP_MAX_ATTEMPTS:
        raise HTTPException(status_code=400, detail="Code missing, expired or too many attempts. Request a new one.")
    if not security.check_secret(payload.code.strip(), otp.code_hash):
        otp.attempts += 1
        session.add(otp)
        session.commit()
        raise HTTPException(status_code=400, detail="Incorrect code")
    otp.used = True
    session.add(otp)
    session.commit()
    user = session.exec(select(User).where(User.email == email)).first()
    if not second_factor:
        if user is not None and user.mfa_enabled:
            raise HTTPException(status_code=403, detail="This account needs password + OTP sign-in.")
        user = _find_or_create(session, email)
    if user is None or not user.active:
        raise HTTPException(status_code=403, detail="This email is not registered for any exam. Ask your teacher.")
    return _issue_session(session, user)


@router.post("/login")
def password_login(payload: PasswordLoginIn, session: Session = Depends(get_session)):
    user = session.exec(select(User).where(User.email == payload.email.lower())).first()
    ok = security.check_secret(payload.password, user.password_hash if user else security.hash_secret("dummy-timing-equaliser"))
    if not user or not ok or not user.active:
        raise HTTPException(status_code=401, detail="Wrong email or password")
    return _after_first_factor(session, user)


@router.post("/google")
def google_login(payload: OIDCIn, session: Session = Depends(get_session)):
    try:
        info = security.verify_google(payload.id_token)
    except Exception as e:
        raise HTTPException(status_code=401, detail=f"Google sign-in failed: {e}")
    user = _find_or_create(session, info["email"], info.get("name"), "google")
    if user is None:
        raise HTTPException(status_code=403, detail="This Google account is not registered for any exam.")
    return _after_first_factor(session, user)


@router.post("/microsoft")
def microsoft_login(payload: OIDCIn, session: Session = Depends(get_session)):
    try:
        info = security.verify_microsoft(payload.id_token, payload.nonce)
    except Exception as e:
        raise HTTPException(status_code=401, detail=f"Microsoft sign-in failed: {e}")
    user = _find_or_create(session, info["email"], info.get("name"), "microsoft")
    if user is None:
        raise HTTPException(status_code=403, detail="This Microsoft account is not registered for any exam.")
    return _after_first_factor(session, user)


@router.get("/me")
def me(user: User = Depends(get_current_user)):
    return user_dict(user)


@router.post("/logout")
def logout(user: User = Depends(get_current_user), session: Session = Depends(get_session)):
    if user.role in config.SINGLE_SESSION_ROLES:
        user.session_id = security.new_session_id()
        session.add(user)
        session.commit()
    return {"detail": "logged_out"}


@router.post("/set-password")
def set_password(payload: SetPasswordIn, user: User = Depends(get_current_user), session: Session = Depends(get_session)):
    if user.password_hash and not security.check_secret(payload.current_password or "", user.password_hash):
        raise HTTPException(status_code=400, detail="Current password is incorrect")
    err = security.validate_password(payload.password)
    if err:
        raise HTTPException(status_code=422, detail=err)
    user.password_hash = security.hash_secret(payload.password)
    session.add(user)
    session.commit()
    return {"detail": "password_set"}


@router.post("/mfa")
def set_mfa(payload: MFAIn, user: User = Depends(get_current_user), session: Session = Depends(get_session)):
    if payload.enabled and not user.password_hash and not user.provider:
        raise HTTPException(status_code=400, detail="Set a password (or sign in with Google/Microsoft) before enabling MFA")
    user.mfa_enabled = payload.enabled
    session.add(user)
    session.commit()
    return user_dict(user)
