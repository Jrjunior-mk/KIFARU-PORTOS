from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from ..config import get_settings
from ..deps import CurrentUser, DbDep, audit, rate_limit
from ..events import EventType, publish
from ..models import Organization, RefreshSession, Role, User, UserPII, utcnow
from ..pii import encrypt
from ..schemas.common import Email
from ..security import (
    create_access_token,
    hash_password,
    hash_refresh_token,
    new_refresh_token,
    new_totp_secret,
    totp_uri,
    verify_password,
    verify_totp,
)

router = APIRouter(prefix="/auth", tags=["auth"], dependencies=[Depends(rate_limit)])


class RegisterIn(BaseModel):
    email: Email
    password: str = Field(min_length=10, max_length=128)
    full_name: str = Field(min_length=2, max_length=200)
    phone: str | None = None
    org_name: str | None = None
    org_type: str = Field(default="cargo_owner", pattern="^(transporter|cargo_owner|warehouse)$")
    role: str = Field(default="cargo_owner", pattern="^(transporter_admin|cargo_owner|warehouse_manager|driver|dispatcher)$")


class LoginIn(BaseModel):
    email: Email
    password: str
    totp_code: str | None = None


class TokenOut(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int
    mfa_required: bool = False
    roles: list[str]
    org_id: str | None
    user_id: str
    full_name: str


class RefreshIn(BaseModel):
    refresh_token: str


def _aware(dt):
    return dt if dt.tzinfo else dt.replace(tzinfo=utcnow().tzinfo)


def _issue(db, user: User, mfa_ok: bool, request: Request) -> TokenOut:
    s = get_settings()
    raw, h = new_refresh_token()
    db.add(
        RefreshSession(
            user_id=user.id,
            token_hash=h,
            expires_at=utcnow() + timedelta(days=s.refresh_token_days),
            ip=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent", "")[:255],
            mfa_verified=mfa_ok,
        )
    )
    user.last_login_at = utcnow()
    user.failed_logins = 0
    db.commit()
    return TokenOut(
        access_token=create_access_token(user.id, user.role_names, user.org_id, mfa_ok),
        refresh_token=raw,
        expires_in=s.access_token_minutes * 60,
        mfa_required=user.mfa_enabled and not mfa_ok,
        roles=user.role_names,
        org_id=user.org_id,
        user_id=user.id,
        full_name=user.pii.full_name if user.pii else user.email,
    )


@router.post("/register", response_model=TokenOut, status_code=201)
def register(body: RegisterIn, db: DbDep, request: Request):
    if db.execute(select(User).where(User.email == body.email.lower())).scalar_one_or_none():
        raise HTTPException(status.HTTP_409_CONFLICT, "Email already registered")
    org = Organization(name=body.org_name or body.full_name, type=body.org_type)
    db.add(org)
    db.flush()
    role = db.execute(select(Role).where(Role.name == body.role)).scalar_one_or_none()
    if role is None:
        raise HTTPException(500, "Roles not seeded")
    user = User(email=body.email.lower(), password_hash=hash_password(body.password), org_id=org.id)
    user.roles.append(role)
    db.add(user)
    db.flush()
    db.add(UserPII(user_id=user.id, full_name=body.full_name, phone_enc=encrypt(body.phone)))
    audit(db, None, "register", "user", user.id, after={"email": user.email, "org": org.id})
    return _issue(db, user, mfa_ok=False, request=request)


@router.post("/login", response_model=TokenOut)
def login(body: LoginIn, db: DbDep, request: Request):
    user = db.execute(select(User).where(User.email == body.email.lower())).scalar_one_or_none()
    generic = HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid credentials")
    if user is None or not user.is_active:
        raise generic
    if user.locked_until and _aware(user.locked_until) > utcnow():
        raise HTTPException(status.HTTP_423_LOCKED, "Account temporarily locked")
    if not verify_password(body.password, user.password_hash):
        user.failed_logins += 1
        if user.failed_logins >= 5:
            user.locked_until = utcnow() + timedelta(minutes=15)
        ip = request.client.host if request.client else None
        audit(db, None, "login_failed", "user", user.id, after={"attempt": user.failed_logins}, ip=ip)
        db.commit()
        publish(EventType.LOGIN_FAILED, {"user_id": user.id, "ip": ip, "attempt": user.failed_logins}, org_id="platform")
        raise generic
    mfa_ok = False
    if user.mfa_enabled:
        if body.totp_code and user.mfa_secret and verify_totp(user.mfa_secret, body.totp_code):
            mfa_ok = True
        elif body.totp_code:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid MFA code")
    audit(db, None, "login", "user", user.id, after={"mfa": mfa_ok})
    return _issue(db, user, mfa_ok, request)


@router.post("/refresh", response_model=TokenOut)
def refresh(body: RefreshIn, db: DbDep, request: Request):
    h = hash_refresh_token(body.refresh_token)
    sess = db.execute(select(RefreshSession).where(RefreshSession.token_hash == h)).scalar_one_or_none()
    if sess is None or sess.revoked_at is not None or _aware(sess.expires_at) < utcnow():
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid refresh token")
    sess.revoked_at = utcnow()  # rotation
    user = db.get(User, sess.user_id)
    if user is None or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "User inactive")
    return _issue(db, user, sess.mfa_verified, request)


@router.post("/logout", status_code=204)
def logout(body: RefreshIn, db: DbDep):
    sess = db.execute(select(RefreshSession).where(RefreshSession.token_hash == hash_refresh_token(body.refresh_token))).scalar_one_or_none()
    if sess:
        sess.revoked_at = utcnow()
        db.commit()


class MeOut(BaseModel):
    user_id: str
    email: str
    full_name: str
    roles: list[str]
    org_id: str | None
    org_name: str | None
    org_type: str | None
    mfa_enabled: bool
    mfa_verified: bool


@router.get("/me", response_model=MeOut)
def me(p: CurrentUser, db: DbDep):
    u = p.user
    org = db.get(Organization, u.org_id) if u.org_id else None
    return MeOut(
        user_id=u.id,
        email=u.email,
        full_name=u.pii.full_name if u.pii else u.email,
        roles=u.role_names,
        org_id=u.org_id,
        org_name=org.name if org else None,
        org_type=org.type if org else None,
        mfa_enabled=u.mfa_enabled,
        mfa_verified=p.mfa,
    )


class MfaSetupOut(BaseModel):
    secret: str
    otpauth_uri: str


@router.post("/mfa/setup", response_model=MfaSetupOut)
def mfa_setup(p: CurrentUser, db: DbDep):
    secret = new_totp_secret()
    p.user.mfa_secret = secret
    db.commit()
    return MfaSetupOut(secret=secret, otpauth_uri=totp_uri(secret, p.user.email))


class MfaCodeIn(BaseModel):
    code: str = Field(min_length=6, max_length=8)


@router.post("/mfa/enable", status_code=204)
def mfa_enable(body: MfaCodeIn, p: CurrentUser, db: DbDep):
    if not p.user.mfa_secret or not verify_totp(p.user.mfa_secret, body.code):
        raise HTTPException(400, "Invalid code")
    p.user.mfa_enabled = True
    audit(db, p, "mfa_enable", "user", p.user.id)
    db.commit()


@router.post("/mfa/verify", response_model=TokenOut)
def mfa_verify(body: MfaCodeIn, p: CurrentUser, db: DbDep, request: Request):
    if not p.user.mfa_enabled or not p.user.mfa_secret or not verify_totp(p.user.mfa_secret, body.code):
        raise HTTPException(400, "Invalid code")
    return _issue(db, p.user, True, request)
