from __future__ import annotations

from datetime import datetime

from sqlalchemy import CHAR, JSON, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, Timestamped, ULIDPk


class Notification(ULIDPk, Timestamped, Base):
    __tablename__ = "notifications"
    __table_args__ = {"schema": "core"}
    user_id: Mapped[str | None] = mapped_column(CHAR(26), ForeignKey("core.users.id"), index=True)
    org_id: Mapped[str | None] = mapped_column(CHAR(26), ForeignKey("core.organizations.id"), index=True)
    channel: Mapped[str] = mapped_column(String(12))  # ws | sms | email | webhook | push
    template: Mapped[str] = mapped_column(String(40))
    title: Mapped[str] = mapped_column(String(160))
    body: Mapped[str] = mapped_column(Text)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(12), default="queued")  # queued, sent, failed, read
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    provider_ref: Mapped[str | None] = mapped_column(String(120))
    error: Mapped[str | None] = mapped_column(String(300))


class Incident(ULIDPk, Timestamped, Base):
    __tablename__ = "incidents"
    __table_args__ = {"schema": "core"}
    station_id: Mapped[str | None] = mapped_column(CHAR(26), ForeignKey("core.weighing_stations.id"), index=True)
    severity: Mapped[str] = mapped_column(String(8), default="medium")  # low, medium, high, critical
    category: Mapped[str] = mapped_column(String(32))  # station_failure, sensor_fault, security, traffic, cargo_anomaly
    title: Mapped[str] = mapped_column(String(160))
    details: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(12), default="open", index=True)
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    raised_by: Mapped[str] = mapped_column(String(32), default="system")


class ApiIntegration(ULIDPk, Timestamped, Base):
    """Adapter registry. `mode` is `mock` unless real credentials are configured; the UI shows the mode."""

    __tablename__ = "api_integrations"
    __table_args__ = {"schema": "core"}
    org_id: Mapped[str | None] = mapped_column(CHAR(26), ForeignKey("core.organizations.id"))
    name: Mapped[str] = mapped_column(String(32), unique=True)
    display_name: Mapped[str] = mapped_column(String(80))
    mode: Mapped[str] = mapped_column(String(8), default="mock")  # mock | real
    config: Mapped[dict] = mapped_column(JSON, default=dict)  # non-secret config; secrets live in Secrets Manager
    health_status: Mapped[str] = mapped_column(String(12), default="unknown")
    last_ok_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(String(300))


class AuditEvent(ULIDPk, Base):
    __tablename__ = "audit_events"
    __table_args__ = (Index("ix_audit_entity", "entity", "entity_id"), {"schema": "core"})
    actor_user_id: Mapped[str | None] = mapped_column(CHAR(26), ForeignKey("core.users.id"), index=True)
    action: Mapped[str] = mapped_column(String(48))
    entity: Mapped[str] = mapped_column(String(48))
    entity_id: Mapped[str | None] = mapped_column(String(64))
    before: Mapped[dict | None] = mapped_column(JSON)
    after: Mapped[dict | None] = mapped_column(JSON)
    ip: Mapped[str | None] = mapped_column(String(64))
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class LedgerEvent(Base):
    """Hash-chained, signed operational event log (the 'conventional cryptographically signed ledger')."""

    __tablename__ = "ledger_events"
    __table_args__ = (Index("ix_ledger_type_ts", "type", "occurred_at"), {"schema": "core"})
    event_id: Mapped[str] = mapped_column(CHAR(26), primary_key=True)
    seq: Mapped[int] = mapped_column(Integer, index=True)
    type: Mapped[str] = mapped_column(String(40))
    payload: Mapped[dict] = mapped_column(JSON)
    station_id: Mapped[str | None] = mapped_column(CHAR(26))
    producer: Mapped[str] = mapped_column(String(64), default="cloud-api")
    prev_hash: Mapped[str] = mapped_column(String(64))
    hash: Mapped[str] = mapped_column(String(64), unique=True)
    signature: Mapped[str] = mapped_column(String(128))
    signer_key_id: Mapped[str] = mapped_column(String(64))
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
