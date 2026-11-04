"""ULID identifiers: lexicographically sortable, 26 chars, generated offline at the edge or in the cloud."""
from __future__ import annotations

from ulid import ULID


def new_id() -> str:
    return str(ULID())


def is_ulid(value: str) -> bool:
    try:
        ULID.from_str(value)
        return True
    except (ValueError, TypeError):
        return False
