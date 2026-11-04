from __future__ import annotations

from datetime import datetime

from sqlalchemy import CHAR, DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, Timestamped, ULIDPk


class Fleet(ULIDPk, Timestamped, Base):
    __tablename__ = "fleets"
    __table_args__ = {"schema": "core"}
    org_id: Mapped[str] = mapped_column(CHAR(26), ForeignKey("core.organizations.id"), index=True)
    name: Mapped[str] = mapped_column(String(120))

    vehicles: Mapped[list[Vehicle]] = relationship(back_populates="fleet")


class Vehicle(ULIDPk, Timestamped, Base):
    """Prime mover or rigid truck. `axle_config` uses the common notation of axle-group sizes,
    e.g. "1+1" (2-axle rigid), "1+2" (3-axle rigid, tandem drive), "1+1+2" (tractor with tandem semi-trailer), "1+2+3" (7 axle)."""

    __tablename__ = "vehicles"
    __table_args__ = {"schema": "core"}
    fleet_id: Mapped[str | None] = mapped_column(CHAR(26), ForeignKey("core.fleets.id"), index=True)
    org_id: Mapped[str] = mapped_column(CHAR(26), ForeignKey("core.organizations.id"), index=True)
    plate: Mapped[str] = mapped_column(String(16), unique=True, index=True)
    plate_norm: Mapped[str | None] = mapped_column(String(16), index=True)  # upper, alphanumerics only (ANPR matching)
    make: Mapped[str | None] = mapped_column(String(60))
    model: Mapped[str | None] = mapped_column(String(60))
    axle_config: Mapped[str] = mapped_column(String(16), default="1+1")
    class_code: Mapped[str] = mapped_column(String(8), default="HGV")
    tare_kg: Mapped[int] = mapped_column(Integer, default=0)
    max_gvm_kg: Mapped[int] = mapped_column(Integer, default=56000)
    payload_capacity_kg: Mapped[int] = mapped_column(Integer, default=28000)
    body_type: Mapped[str] = mapped_column(String(24), default="flatbed")  # flatbed, container, tanker, box, tipper, reefer
    status: Mapped[str] = mapped_column(String(16), default="active")
    last_lat: Mapped[float | None] = mapped_column(Float)
    last_lon: Mapped[float | None] = mapped_column(Float)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    watchlist_reason: Mapped[str | None] = mapped_column(String(200))

    fleet: Mapped[Fleet | None] = relationship(back_populates="vehicles")
    tags: Mapped[list[RfidTag]] = relationship(back_populates="vehicle", lazy="selectin")


class Trailer(ULIDPk, Timestamped, Base):
    __tablename__ = "trailers"
    __table_args__ = {"schema": "core"}
    org_id: Mapped[str] = mapped_column(CHAR(26), ForeignKey("core.organizations.id"), index=True)
    fleet_id: Mapped[str | None] = mapped_column(CHAR(26), ForeignKey("core.fleets.id"))
    plate: Mapped[str] = mapped_column(String(16), unique=True, index=True)
    axle_config: Mapped[str] = mapped_column(String(16), default="2")
    tare_kg: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(16), default="active")


class RfidTag(ULIDPk, Timestamped, Base):
    __tablename__ = "rfid_tags"
    __table_args__ = {"schema": "core"}
    epc: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    vehicle_id: Mapped[str] = mapped_column(CHAR(26), ForeignKey("core.vehicles.id", ondelete="CASCADE"), index=True)
    issued_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    vehicle: Mapped[Vehicle] = relationship(back_populates="tags")


class Driver(ULIDPk, Timestamped, Base):
    __tablename__ = "drivers"
    __table_args__ = {"schema": "core"}
    org_id: Mapped[str] = mapped_column(CHAR(26), ForeignKey("core.organizations.id"), index=True)
    fleet_id: Mapped[str | None] = mapped_column(CHAR(26), ForeignKey("core.fleets.id"))
    user_id: Mapped[str | None] = mapped_column(CHAR(26), ForeignKey("core.users.id"))
    license_class: Mapped[str | None] = mapped_column(String(8))
    status: Mapped[str] = mapped_column(String(16), default="active")
    hours_driven_today_s: Mapped[int] = mapped_column(Integer, default=0)

    pii: Mapped[DriverPII | None] = relationship(back_populates="driver", uselist=False, lazy="selectin")


class DriverPII(Base):
    __tablename__ = "driver_pii"
    __table_args__ = {"schema": "pii"}
    driver_id: Mapped[str] = mapped_column(CHAR(26), ForeignKey("core.drivers.id", ondelete="CASCADE"), primary_key=True)
    full_name: Mapped[str] = mapped_column(String(200))
    phone_enc: Mapped[str | None] = mapped_column(String(255))
    license_no_enc: Mapped[str | None] = mapped_column(String(255))
    national_id_enc: Mapped[str | None] = mapped_column(String(255))

    driver: Mapped[Driver] = relationship(back_populates="pii")
