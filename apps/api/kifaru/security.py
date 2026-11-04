"""Password hashing (Argon2id), JWT access/refresh tokens, TOTP MFA, Ed25519 signing."""
from __future__ import annotations

import base64
import hashlib
import json
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
import pyotp
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from nacl.encoding import RawEncoder
from nacl.signing import SigningKey, VerifyKey

from .config import get_settings

_ph = PasswordHasher(time_cost=3, memory_cost=64 * 1024, parallelism=2)


# ---------- passwords ----------
def hash_password(password: str) -> str:
    return _ph.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return _ph.verify(password_hash, password)
    except VerifyMismatchError:
        return False


# ---------- JWT ----------
def create_access_token(sub: str, roles: list[str], org_id: str | None, mfa: bool) -> str:
    s = get_settings()
    now = datetime.now(UTC)
    payload = {
        "sub": sub,
        "roles": roles,
        "org": org_id,
        "mfa": mfa,
        "type": "access",
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=s.access_token_minutes)).timestamp()),
    }
    return jwt.encode(payload, s.jwt_secret, algorithm=s.jwt_algorithm)


def decode_token(token: str) -> dict[str, Any]:
    s = get_settings()
    return jwt.decode(token, s.jwt_secret, algorithms=[s.jwt_algorithm])


def new_refresh_token() -> tuple[str, str]:
    """Returns (raw_token, sha256_hash). Only the hash is stored."""
    raw = secrets.token_urlsafe(48)
    return raw, hashlib.sha256(raw.encode()).hexdigest()


def hash_refresh_token(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


# ---------- TOTP ----------
def new_totp_secret() -> str:
    return pyotp.random_base32()


def totp_uri(secret: str, email: str) -> str:
    return pyotp.TOTP(secret).provisioning_uri(name=email, issuer_name=get_settings().mfa_issuer)


def verify_totp(secret: str, code: str) -> bool:
    return pyotp.TOTP(secret).verify(code, valid_window=1)


# ---------- Ed25519 signing (tickets, ledger) ----------
_signing_key: SigningKey | None = None


def get_signing_key() -> SigningKey:
    global _signing_key
    if _signing_key is None:
        s = get_settings()
        if s.signing_seed_b64:
            seed = base64.b64decode(s.signing_seed_b64)
        else:
            if s.env in ("staging", "prod"):
                raise RuntimeError("KIFARU_SIGNING_SEED_B64 must be set outside dev/test")
            # Deterministic dev key derived from the JWT secret so restarts verify the same tickets.
            seed = hashlib.sha256(("kifaru-dev-signing:" + s.jwt_secret).encode()).digest()
        _signing_key = SigningKey(seed)
    return _signing_key


def public_key_b64() -> str:
    return base64.b64encode(get_signing_key().verify_key.encode(RawEncoder)).decode()


def canonical_json(obj: Any) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str).encode()


def sign_payload(payload: dict[str, Any]) -> str:
    sig = get_signing_key().sign(canonical_json(payload)).signature
    return base64.b64encode(sig).decode()


def verify_signature(payload: dict[str, Any], signature_b64: str, public_key_b64_: str | None = None) -> bool:
    try:
        vk = VerifyKey(base64.b64decode(public_key_b64_)) if public_key_b64_ else get_signing_key().verify_key
        vk.verify(canonical_json(payload), base64.b64decode(signature_b64))
        return True
    except Exception:
        return False


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()
