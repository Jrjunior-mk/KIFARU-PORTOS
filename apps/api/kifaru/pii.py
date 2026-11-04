"""Application-level encryption for personal data columns (pii schema).

Values are stored as ``enc1:<base64 nonce+ciphertext>`` using XSalsa20-Poly1305 (NaCl SecretBox) with a dedicated key
(KIFARU_PII_KEY_B64, 32 bytes). In dev/test the key is derived from the JWT secret so the database stays readable
across restarts; in staging/prod the key MUST be provided (from Secrets Manager) and should be rotated with a
re-encryption job. Legacy plaintext values (no prefix) are returned as-is by ``decrypt`` so a migration can run lazily.
"""
from __future__ import annotations

import base64
import hashlib

from nacl.secret import SecretBox

from .config import get_settings

PREFIX = "enc1:"
_box: SecretBox | None = None


def _get_box() -> SecretBox:
    global _box
    if _box is None:
        s = get_settings()
        if s.pii_key_b64:
            key = base64.b64decode(s.pii_key_b64)
        else:
            if s.env in ("staging", "prod"):
                raise RuntimeError("KIFARU_PII_KEY_B64 must be set outside dev/test")
            key = hashlib.sha256(("kifaru-dev-pii:" + s.jwt_secret).encode()).digest()
        if len(key) != SecretBox.KEY_SIZE:
            raise RuntimeError("PII key must be 32 bytes")
        _box = SecretBox(key)
    return _box


def encrypt(value: str | None) -> str | None:
    if value is None or value == "":
        return value
    ct = _get_box().encrypt(value.encode("utf-8"))  # nonce is generated and prepended
    return PREFIX + base64.b64encode(ct).decode()


def decrypt(value: str | None) -> str | None:
    if value is None or not value.startswith(PREFIX):
        return value  # legacy plaintext (pre-encryption rows) — to be migrated
    raw = base64.b64decode(value[len(PREFIX) :])
    return _get_box().decrypt(raw).decode("utf-8")


def is_encrypted(value: str | None) -> bool:
    return bool(value) and value.startswith(PREFIX)
