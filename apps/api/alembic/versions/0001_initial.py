"""initial schema — core, pii, ts schemas and all Phase-2 tables

Revision ID: 0001
Revises:
Create Date: 2026-11-04
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

from kifaru.models import Base

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        for schema in ("core", "pii", "ts"):
            op.execute(sa.text(f"CREATE SCHEMA IF NOT EXISTS {schema}"))
        op.execute(sa.text("CREATE EXTENSION IF NOT EXISTS pgcrypto"))
    Base.metadata.create_all(bind=bind)
    if bind.dialect.name == "postgresql":
        # Slot capacity guard: at most capacity_per_hour/4 bookings per 15-min window is enforced in the service layer;
        # this constraint prevents duplicate active bookings for one vehicle in one window.
        op.execute(sa.text(
            "CREATE UNIQUE INDEX IF NOT EXISTS ux_appt_vehicle_slot_active ON core.appointments (vehicle_id, slot_start) "
            "WHERE status IN ('booked','arrived')"
        ))
        # Monthly range partitioning for ts.sensor_readings is applied by pg_partman in a later revision once the
        # extension is available on the target RDS instance (documented in docs/02-architecture/database-erd.md).
        op.execute(sa.text("REVOKE ALL ON SCHEMA pii FROM PUBLIC"))


def downgrade() -> None:
    bind = op.get_bind()
    Base.metadata.drop_all(bind=bind)
    if bind.dialect.name == "postgresql":
        for schema in ("ts", "pii", "core"):
            op.execute(sa.text(f"DROP SCHEMA IF EXISTS {schema} CASCADE"))
