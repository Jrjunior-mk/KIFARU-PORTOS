"""FastAPI dependencies: DB session, current user, role guards, audit helper, simple rate limiting."""
from __future__ import annotations

import time
from collections import defaultdict, deque
from collections.abc import Callable
from typing import Annotated

import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from .config import get_settings
from .db import get_db
from .models import AuditEvent, User, utcnow
from .security import decode_token

bearer = HTTPBearer(auto_error=False)

DbDep = Annotated[Session, Depends(get_db)]


class Principal:
    def __init__(self, user: User, claims: dict):
        self.user = user
        self.claims = claims
        self.roles: list[str] = claims.get("roles", [])
        self.org_id: str | None = claims.get("org")
        self.mfa: bool = bool(claims.get("mfa"))

    def has_role(self, *roles: str) -> bool:
        return any(r in self.roles for r in roles) or "platform_admin" in self.roles


def get_current_principal(
    db: DbDep, creds: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)]
) -> Principal:
    if creds is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated")
    try:
        claims = decode_token(creds.credentials)
    except jwt.ExpiredSignatureError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid token")
    if claims.get("type") != "access":
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Wrong token type")
    user = db.get(User, claims["sub"])
    if user is None or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "User inactive")
    return Principal(user, claims)


CurrentUser = Annotated[Principal, Depends(get_current_principal)]


def require_roles(*roles: str, mfa: bool | None = None) -> Callable:
    def _dep(p: CurrentUser) -> Principal:
        if not p.has_role(*roles):
            raise HTTPException(status.HTTP_403_FORBIDDEN, f"Requires one of roles: {roles}")
        s = get_settings()
        needs_mfa = mfa if mfa is not None else any(r in s.mfa_required_roles for r in p.roles)
        enforce_enrolment = s.mfa_enforce_enrolment if s.mfa_enforce_enrolment is not None else s.is_deployed
        if needs_mfa and not p.user.mfa_enabled and enforce_enrolment:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "MFA enrolment required for this role (POST /auth/mfa/setup)")
        if needs_mfa and p.user.mfa_enabled and not p.mfa:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "MFA verification required for this role")
        return p

    return _dep


def audit(db: Session, actor: Principal | None, action: str, entity: str, entity_id: str | None, before: dict | None = None, after: dict | None = None, ip: str | None = None) -> None:
    db.add(
        AuditEvent(
            actor_user_id=actor.user.id if actor else None,
            action=action,
            entity=entity,
            entity_id=entity_id,
            before=before,
            after=after,
            ip=ip,
            at=utcnow(),
        )
    )


# ----------------------------------------------------------------- rate limiting (per-process token window)
_windows: dict[str, deque] = defaultdict(deque)


def rate_limit(request: Request) -> None:
    s = get_settings()
    key = request.client.host if request.client else "anon"
    now = time.monotonic()
    dq = _windows[key]
    while dq and now - dq[0] > 60:
        dq.popleft()
    if len(dq) >= s.rate_limit_per_minute:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Rate limit exceeded")
    dq.append(now)


def org_scope(p: Principal) -> str | None:
    """Returns the org_id the principal is restricted to, or None for platform-wide roles."""
    if p.has_role("platform_admin", "port_controller", "weighbridge_operator", "auditor", "regulator_readonly"):
        return None
    return p.org_id
