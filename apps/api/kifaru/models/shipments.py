from __future__ import annotations

from datetime import datetime

from sqlalchemy import CHAR, JSON, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, Timestamped, ULIDPk

SHIPMENT_STAGES = [
    "registered",
    "declared",
    "at_port",
    "customs_processing",
    "weighing_verification",
    "gate_processing",
    "released",
    "in_transit",
    "delivered",
    "closed",
]


class Warehouse(ULIDPk, Timestamped, Base):
    __tablename__ = "warehouses"
    __table_args__ = {"schema": "core"}
    org_id: Mapped[str] = mapped_column(CHAR(26), ForeignKey("core.organizations.id"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    lat: Mapped[float] = mapped_column(Float)
    lon: Mapped[float] = mapped_column(Float)
    dock_count: Mapped[int] = mapped_column(Integer, default=2)
    readiness_status: Mapped[str] = mapped_column(String(16), default="ready")  # ready, busy, closed


class Shipment(ULIDPk, Timestamped, Base):
    """Root of the Digital Cargo Passport."""

    __tablename__ = "shipments"
    __table_args__ = {"schema": "core"}
    reference: Mapped[str] = mapped_column(String(24), unique=True, index=True)
    owner_org_id: Mapped[str] = mapped_column(CHAR(26), ForeignKey("core.organizations.id"), index=True)
    transporter_org_id: Mapped[str | None] = mapped_column(CHAR(26), ForeignKey("core.organizations.id"))
    vehicle_id: Mapped[str | None] = mapped_column(CHAR(26), ForeignKey("core.vehicles.id"))
    trailer_id: Mapped[str | None] = mapped_column(CHAR(26), ForeignKey("core.trailers.id"))
    driver_id: Mapped[str | None] = mapped_column(CHAR(26), ForeignKey("core.drivers.id"))
    warehouse_id: Mapped[str | None] = mapped_column(CHAR(26), ForeignKey("core.warehouses.id"))
    description: Mapped[str] = mapped_column(String(300))
    cargo_type: Mapped[str] = mapped_column(String(24), default="general")  # general, container, bulk, liquid, reefer, hazardous
    origin: Mapped[str] = mapped_column(String(120))
    destination: Mapped[str] = mapped_column(String(120))
    origin_lat: Mapped[float | None] = mapped_column(Float)
    origin_lon: Mapped[float | None] = mapped_column(Float)
    dest_lat: Mapped[float | None] = mapped_column(Float)
    dest_lon: Mapped[float | None] = mapped_column(Float)
    declared_mass_kg: Mapped[int] = mapped_column(Integer, default=0)
    vgm_kg: Mapped[int | None] = mapped_column(Integer)
    stage: Mapped[str] = mapped_column(String(24), default="registered", index=True)
    status: Mapped[str] = mapped_column(String(16), default="active")
    predicted_release_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    predicted_release_p10: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    predicted_release_p90: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    prediction_explanation: Mapped[dict | None] = mapped_column(JSON)

    containers: Mapped[list[Container]] = relationship(back_populates="shipment", lazy="selectin")
    declaration: Mapped[CargoDeclaration | None] = relationship(back_populates="shipment", uselist=False, lazy="selectin")
    seals: Mapped[list[ElectronicSeal]] = relationship(back_populates="shipment", lazy="selectin")
    processing_events: Mapped[list[CargoProcessingEvent]] = relationship(
        back_populates="shipment", lazy="selectin", order_by="CargoProcessingEvent.occurred_at"
    )


class Container(ULIDPk, Timestamped, Base):
    __tablename__ = "containers"
    __table_args__ = {"schema": "core"}
    shipment_id: Mapped[str] = mapped_column(CHAR(26), ForeignKey("core.shipments.id", ondelete="CASCADE"), index=True)
    number: Mapped[str] = mapped_column(String(11), index=True)  # ISO 6346, check digit validated in schema
    size_ft: Mapped[int] = mapped_column(Integer, default=40)
    type: Mapped[str] = mapped_column(String(8), default="GP")

    shipment: Mapped[Shipment] = relationship(back_populates="containers")


class CargoDeclaration(ULIDPk, Timestamped, Base):
    __tablename__ = "cargo_declarations"
    __table_args__ = {"schema": "core"}
    shipment_id: Mapped[str] = mapped_column(CHAR(26), ForeignKey("core.shipments.id", ondelete="CASCADE"), unique=True)
    reference: Mapped[str] = mapped_column(String(40))
    source: Mapped[str] = mapped_column(String(24), default="manual")  # manual | kra_icms_mock | kra_icms
    declared_items: Mapped[list] = mapped_column(JSON, default=list)
    declared_mass_kg: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(16), default="submitted")

    shipment: Mapped[Shipment] = relationship(back_populates="declaration")


class ElectronicSeal(ULIDPk, Timestamped, Base):
    __tablename__ = "electronic_seals"
    __table_args__ = {"schema": "core"}
    shipment_id: Mapped[str] = mapped_column(CHAR(26), ForeignKey("core.shipments.id", ondelete="CASCADE"), index=True)
    seal_id: Mapped[str] = mapped_column(String(40), index=True)
    provider: Mapped[str] = mapped_column(String(40), default="mock")
    status: Mapped[str] = mapped_column(String(16), default="armed")  # armed, breached, removed, unknown
    armed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    breached_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    shipment: Mapped[Shipment] = relationship(back_populates="seals")


class CargoProcessingEvent(ULIDPk, Base):
    __tablename__ = "cargo_processing_events"
    __table_args__ = {"schema": "core"}
    shipment_id: Mapped[str] = mapped_column(CHAR(26), ForeignKey("core.shipments.id", ondelete="CASCADE"), index=True)
    stage: Mapped[str] = mapped_column(String(24))
    status: Mapped[str] = mapped_column(String(16), default="completed")  # started, completed, blocked
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    source: Mapped[str] = mapped_column(String(24), default="manual")
    notes: Mapped[str | None] = mapped_column(Text)
    actor_user_id: Mapped[str | None] = mapped_column(CHAR(26), ForeignKey("core.users.id"))

    shipment: Mapped[Shipment] = relationship(back_populates="processing_events")


class DeliveryRecord(ULIDPk, Timestamped, Base):
    __tablename__ = "delivery_records"
    __table_args__ = {"schema": "core"}
    shipment_id: Mapped[str | None] = mapped_column(CHAR(26), ForeignKey("core.shipments.id"), index=True)
    backhaul_match_id: Mapped[str | None] = mapped_column(CHAR(26), ForeignKey("core.backhaul_matches.id"))
    delivered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    pod_object_key: Mapped[str | None] = mapped_column(String(255))
    receiver_name: Mapped[str | None] = mapped_column(String(120))
    notes: Mapped[str | None] = mapped_column(Text)
