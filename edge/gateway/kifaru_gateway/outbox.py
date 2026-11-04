"""SQLite (WAL) store-and-forward outbox (CLD-04).

Guarantees:
  * durability: every event is committed before the caller continues; WAL mode survives power loss of the IPC;
  * idempotency: `event_id` (ULID) is UNIQUE; re-enqueueing a known id (pending or already sent) is a no-op;
  * ordering: replay is strictly in enqueue order (autoincrement seq); a failing head blocks the queue so the cloud
    never sees event N+1 before event N;
  * backoff: exponential 1 s -> 60 s with ±20 % jitter per failed attempt; poison messages (4xx from the API) are parked
    out of the way and alarmed instead of blocking.
"""
from __future__ import annotations

import json
import random
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from ulid import ULID

PublishFn = Callable[[str, dict, str], bool]  # (topic, payload, event_id) -> ok


class PoisonMessage(Exception):
    """Raised by a publisher when the message can never be delivered (schema rejected by the API)."""


@dataclass
class DrainResult:
    sent: int = 0
    failed: int = 0
    parked: int = 0
    blocked_on: str | None = None


def new_event_id() -> str:
    return str(ULID())


class Outbox:
    SCHEMA = """
    CREATE TABLE IF NOT EXISTS outbox (
        seq INTEGER PRIMARY KEY AUTOINCREMENT,
        event_id TEXT NOT NULL UNIQUE,
        topic TEXT NOT NULL,
        payload TEXT NOT NULL,
        created_at REAL NOT NULL,
        attempts INTEGER NOT NULL DEFAULT 0,
        next_attempt_at REAL NOT NULL DEFAULT 0,
        state TEXT NOT NULL DEFAULT 'pending',
        last_error TEXT,
        sent_at REAL
    );
    CREATE INDEX IF NOT EXISTS ix_outbox_state_seq ON outbox(state, seq);
    """

    def __init__(self, path: str | Path, base_backoff_s: float = 1.0, max_backoff_s: float = 60.0, jitter: float = 0.2, rng: random.Random | None = None):
        self.path = Path(path)
        if str(self.path) != ":memory:":
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.path), isolation_level=None, check_same_thread=False)
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA synchronous=FULL")
        self.conn.executescript(self.SCHEMA)
        self.base_backoff_s, self.max_backoff_s, self.jitter = base_backoff_s, max_backoff_s, jitter
        self.rng = rng or random.Random()

    # ------------------------------------------------------------------ write side
    def enqueue(self, event_id: str, topic: str, payload: dict, now: float | None = None) -> bool:
        now = time.time() if now is None else now
        cur = self.conn.execute(
            "INSERT OR IGNORE INTO outbox(event_id, topic, payload, created_at) VALUES (?, ?, ?, ?)",
            (event_id, topic, json.dumps(payload, default=str, separators=(",", ":")), now),
        )
        return cur.rowcount == 1

    # ------------------------------------------------------------------ read side
    def pending_count(self) -> int:
        return self.conn.execute("SELECT COUNT(*) FROM outbox WHERE state='pending'").fetchone()[0]

    def sent_count(self) -> int:
        return self.conn.execute("SELECT COUNT(*) FROM outbox WHERE state='sent'").fetchone()[0]

    def parked(self) -> list[tuple[str, str]]:
        return self.conn.execute("SELECT event_id, last_error FROM outbox WHERE state='parked' ORDER BY seq").fetchall()

    def stats(self) -> dict:
        rows = self.conn.execute("SELECT state, COUNT(*) FROM outbox GROUP BY state").fetchall()
        d = {"pending": 0, "sent": 0, "parked": 0}
        d.update({s: n for s, n in rows})
        oldest = self.conn.execute("SELECT MIN(created_at) FROM outbox WHERE state='pending'").fetchone()[0]
        d["oldest_pending_age_s"] = 0.0 if oldest is None else round(time.time() - oldest, 1)
        return d

    def backoff_s(self, attempts: int) -> float:
        base = min(self.max_backoff_s, self.base_backoff_s * (2 ** max(0, attempts - 1)))
        return base * (1.0 + self.rng.uniform(-self.jitter, self.jitter))

    def drain(self, publish: PublishFn, now: float | None = None, limit: int = 200) -> DrainResult:
        """Replay pending events in order. Stops at the first failure (head-of-line) to preserve ordering."""
        now = time.time() if now is None else now
        res = DrainResult()
        rows = self.conn.execute(
            "SELECT seq, event_id, topic, payload, attempts, next_attempt_at FROM outbox WHERE state='pending' ORDER BY seq LIMIT ?", (limit,)
        ).fetchall()
        for seq, event_id, topic, payload, attempts, next_at in rows:
            if next_at > now:
                res.blocked_on = event_id
                break
            try:
                ok = publish(topic, json.loads(payload), event_id)
            except PoisonMessage as e:
                self.conn.execute("UPDATE outbox SET state='parked', last_error=?, attempts=attempts+1 WHERE seq=?", (str(e)[:500], seq))
                res.parked += 1
                continue
            except Exception as e:  # transport error: treat as failure
                ok = False
                err = f"{type(e).__name__}: {e}"[:500]
            else:
                err = None if ok else "publish returned False"
            if ok:
                self.conn.execute("UPDATE outbox SET state='sent', sent_at=?, attempts=attempts+1, last_error=NULL WHERE seq=?", (now, seq))
                res.sent += 1
            else:
                attempts += 1
                self.conn.execute("UPDATE outbox SET attempts=?, next_attempt_at=?, last_error=? WHERE seq=?", (attempts, now + self.backoff_s(attempts), err, seq))
                res.failed += 1
                res.blocked_on = event_id
                break
        return res

    def prune_sent(self, older_than_s: float = 7 * 86400, now: float | None = None) -> int:
        now = time.time() if now is None else now
        cur = self.conn.execute("DELETE FROM outbox WHERE state='sent' AND sent_at < ?", (now - older_than_s,))
        return cur.rowcount

    def close(self) -> None:
        self.conn.close()
