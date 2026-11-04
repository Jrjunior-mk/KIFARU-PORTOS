"""Store-and-forward: enqueue during an outage, ordered replay on reconnect, no duplicates, idempotent re-enqueue,
exponential backoff, poison parking, persistence across process restart."""
import random

from kifaru_gateway.outbox import Outbox, new_event_id
from kifaru_gateway.uplink import MemoryUplink


def test_outbox_survives_outage_and_replays_in_order(tmp_path):
    ob = Outbox(tmp_path / "outbox.sqlite3", rng=random.Random(0))
    up = MemoryUplink()
    up.down = True
    ids = []
    now = 1_000_000.0
    for i in range(50):
        eid = new_event_id()
        ids.append(eid)
        assert ob.enqueue(eid, "kifaru/stations/T/lanes/L1/events", {"n": i, "event_id": eid}, now=now + i * 0.01)
        res = ob.drain(up.publish, now=now + i * 0.01)
        assert res.sent == 0
    assert ob.pending_count() == 50
    assert up.published == []

    # the head is retried with exponential backoff while the link is down
    head = ob.conn.execute("SELECT attempts, next_attempt_at FROM outbox ORDER BY seq LIMIT 1").fetchone()
    assert head[0] >= 1 and head[1] > now
    r = ob.drain(up.publish, now=now + 0.2)  # before next_attempt_at: nothing attempted, blocked on head
    assert r.sent == 0 and r.failed == 0 and r.blocked_on == ids[0]

    # link comes back: replay everything in order over a few drain cycles
    up.down = False
    t = now + 3600
    for _ in range(10):
        ob.drain(up.publish, now=t)
        t += 61
        if ob.pending_count() == 0:
            break
    assert ob.pending_count() == 0
    assert [e for _, _, e in up.published] == ids
    assert len({e for _, _, e in up.published}) == 50

    # idempotency: re-enqueueing sent or pending ids is a no-op and nothing is re-published
    for eid in ids[:10]:
        assert ob.enqueue(eid, "x", {"dup": True}) is False
    ob.drain(up.publish, now=t)
    assert len(up.published) == 50
    ob.close()


def test_outbox_persists_across_restart(tmp_path):
    path = tmp_path / "ob.sqlite3"
    ob = Outbox(path)
    ids = [new_event_id() for _ in range(5)]
    for i, e in enumerate(ids):
        ob.enqueue(e, "t", {"i": i})
    ob.close()
    ob2 = Outbox(path)  # simulated process restart / power cycle
    assert ob2.pending_count() == 5
    up = MemoryUplink()
    ob2.drain(up.publish)
    assert [e for _, _, e in up.published] == ids
    ob2.close()


def test_backoff_grows_exponentially_and_caps():
    ob = Outbox(":memory:", rng=random.Random(1), jitter=0.0)
    assert ob.backoff_s(1) == 1.0
    assert ob.backoff_s(2) == 2.0
    assert ob.backoff_s(4) == 8.0
    assert ob.backoff_s(10) == 60.0
    ob.close()


def test_partial_failure_blocks_later_events_until_head_sent():
    ob = Outbox(":memory:", rng=random.Random(2))
    up = MemoryUplink()
    a, b, c = new_event_id(), new_event_id(), new_event_id()
    ob.enqueue(a, "t", {"k": "a"}, now=1.0)
    ob.enqueue(b, "t", {"k": "b"}, now=2.0)
    ob.enqueue(c, "t", {"k": "c"}, now=3.0)
    up.down = True
    r = ob.drain(up.publish, now=10.0)
    assert r.failed == 1 and r.blocked_on == a and ob.pending_count() == 3
    up.down = False
    r = ob.drain(up.publish, now=10.5)  # head still in backoff -> nothing sent (order preserved)
    assert r.sent == 0
    r = ob.drain(up.publish, now=100.0)
    assert r.sent == 3 and [e for _, _, e in up.published] == [a, b, c]
    ob.close()


def test_poison_message_is_parked_not_blocking():
    ob = Outbox(":memory:")
    up = MemoryUplink()
    bad, good = new_event_id(), new_event_id()
    up.poison_ids.add(bad)
    ob.enqueue(bad, "t", {"k": "bad"})
    ob.enqueue(good, "t", {"k": "good"})
    r = ob.drain(up.publish)
    assert r.parked == 1 and r.sent == 1
    assert [e for e, _ in ob.parked()] == [bad]
    assert ob.pending_count() == 0
    ob.close()
