from __future__ import annotations

from datetime import datetime

from sqlalchemy import CHAR, JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, Timestamped, ULIDPk


class WeighingEvent(ULIDPk, Timestamped, Base):
    """One pass of a vehicle over a lane. `source` is ALWAYS carried through to the UI so simulated data is never shown as live."""

    __tablename__ = "weighing_events"
    __table_args__ = {"schema": "core"}
    lane_id: Mapped[str] = mapped_column(CHAR(26), ForeignKey("core.lanes.id"), index=True)
    station_id: Mapped[str] = mapped_column(CHAR(26), ForeignKey("core.weighing_stations.id"), index=True)
    vehicle_id: Mapped[str | None] = mapped_column(CHAR(26), ForeignKey("core.vehicles.id"), index=True)
    trailer_id: Mapped[str | None] = mapped_column(CHAR(26), ForeignKey("core.trailers.id"))
    driver_id: Mapped[str | None] = mapped_column(CHAR(26), ForeignKey("core.drivers.id"))
    shipment_id: Mapped[str | None] = mapped_column(CHAR(26), ForeignKey("core.shipments.id"), index=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    speed_mps: Mapped[float] = mapped_column(Float)
    gvm_kg: Mapped[int] = mapped_column(Integer)
    gvm_uncertainty_kg: Mapped[int] = mapped_column(Integer)
    axle_count: Mapped[int] = mapped_column(Integer)
    detected_axle_config: Mapped[str | None] = mapped_column(String(16))
    class_code: Mapped[str | None] = mapped_column(String(8))
    quality_flags: Mapped[list] = mapped_column(JSON, default=list)
    sensor_health: Mapped[dict] = mapped_column(JSON, default=dict)
    pavement_temp_c: Mapped[float | None] = mapped_column(Float)
    ambient_temp_c: Mapped[float | None] = mapped_column(Float)
    raw_ref: Mapped[str | None] = mapped_column(String(255))  # object key of raw window
    source: Mapped[str] = mapped_column(String(12), default="simulated")  # live | simulated | replay | static
    kind: Mapped[str] = mapped_column(String(12), default="wim")  # wim | static
    edge_event_id: Mapped[str | None] = mapped_column(CHAR(26), unique=True)  # idempotency key from the gateway

    axles: Mapped[list[AxleMeasurement]] = relationship(back_populates="event", lazy="selectin", order_by="AxleMeasurement.axle_index")
    identity: Mapped[IdentityEvent | None] = relationship(back_populates="event", uselist=False, lazy="selectin")
    decision: Mapped[ClearanceDecision | None] = relationship(back_populates="event", uselist=False, lazy="selectin")


class AxleMeasurement(ULIDPk, Base):
    __tablename__ = "axle_measurements"
    __table_args__ = {"schema": "core"}
    weighing_event_id: Mapped[str] = mapped_column(CHAR(26), ForeignKey("core.weighing_events.id", ondelete="CASCADE"), index=True)
    axle_index: Mapped[int] = mapped_column(Integer)
    load_kg: Mapped[int] = mapped_column(Integer)
    uncertainty_kg: Mapped[int] = mapped_column(Integer)
    spacing_to_next_m: Mapped[float | None] = mapped_column(Float)
    group_no: Mapped[int] = mapped_column(Integer, default=1)
    left_kg: Mapped[int | None] = mapped_column(Integer)
    right_kg: Mapped[int | None] = mapped_column(Integer)

    event: Mapped[WeighingEvent] = relationship(back_populates="axles")


class IdentityEvent(ULIDPk, Timestamped, Base):
    __tablename__ = "identity_events"
    __table_args__ = {"schema": "core"}
    weighing_event_id: Mapped[str] = mapped_column(CHAR(26), ForeignKey("core.weighing_events.id", ondelete="CASCADE"), unique=True)
    anpr_plate: Mapped[str | None] = mapped_column(String(16))
    anpr_confidence: Mapped[float | None] = mapped_column(Float)
    rfid_epc: Mapped[str | None] = mapped_column(String(64))
    rfid_confidence: Mapped[float | None] = mapped_column(Float)
    fused_vehicle_id: Mapped[str | None] = mapped_column(CHAR(26), ForeignKey("core.vehicles.id"))
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    method: Mapped[str] = mapped_column(String(24), default="none")  # rfid+anpr, rfid, anpr, none, conflict
    evidence_keys: Mapped[list] = mapped_column(JSON, default=list)
    explanation: Mapped[str | None] = mapped_column(Text)

    event: Mapped[WeighingEvent] = relationship(back_populates="identity")


class ClearanceDecision(ULIDPk, Timestamped, Base):
    __tablename__ = "clearance_decisions"
    __table_args__ = {"schema": "core"}
    weighing_event_id: Mapped[str] = mapped_column(CHAR(26), ForeignKey("core.weighing_events.id", ondelete="CASCADE"), unique=True)
    decision: Mapped[str] = mapped_column(String(8), index=True)  # GREEN | AMBER | RED
    rules_fired: Mapped[list] = mapped_column(JSON, default=list)
    margins: Mapped[dict] = mapped_column(JSON, default=dict)
    limits_version: Mapped[str] = mapped_column(String(64))
    engine_version: Mapped[str] = mapped_column(String(16))
    audit_selected: Mapped[bool] = mapped_column(Boolean, default=False)
    evidence_hash: Mapped[str] = mapped_column(String(64))
    signature: Mapped[str | None] = mapped_column(String(128))
    decided_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    explanation: Mapped[str] = mapped_column(Text, default="")
    overridden_by: Mapped[str | None] = mapped_column(CHAR(26), ForeignKey("core.users.id"))
    override_reason: Mapped[str | None] = mapped_column(String(300))
    static_verified_gvm_kg: Mapped[int | None] = mapped_column(Integer)

    event: Mapped[WeighingEvent] = relationship(back_populates="decision")
    tickets: Mapped[list[DigitalTicket]] = relationship(back_populates="decision", lazy="selectin", order_by="DigitalTicket.created_at")

    @property
    def ticket(self) -> DigitalTicket | None:
        """The active ticket (static_certified supersedes prescreen); superseded tickets remain verifiable evidence."""
        active = [t for t in self.tickets if t.status == "active"]
        return active[-1] if active else (self.tickets[-1] if self.tickets else None)


class DigitalTicket(ULIDPk, Timestamped, Base):
    __tablename__ = "digital_tickets"
    __table_args__ = {"schema": "core"}
    decision_id: Mapped[str] = mapped_column(CHAR(26), ForeignKey("core.clearance_decisions.id"), index=True)
    type: Mapped[str] = mapped_column(String(20))  # prescreen | static_certified
    status: Mapped[str] = mapped_column(String(12), default="active")  # active | superseded (never deleted: evidence)
    payload: Mapped[dict] = mapped_column(JSON)
    signature: Mapped[str] = mapped_column(String(128))
    signer_key_id: Mapped[str] = mapped_column(String(64))
    qr_token: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    object_key: Mapped[str | None] = mapped_column(String(255))

    decision: Mapped[ClearanceDecision] = relationship(back_populates="tickets")
