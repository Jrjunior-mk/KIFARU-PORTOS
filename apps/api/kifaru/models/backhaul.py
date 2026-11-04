from __future__ import annotations

from datetime import datetime

from sqlalchemy import CHAR, JSON, DateTime, Float, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, Timestamped, ULIDPk

OFFER_STATUSES = ["open", "matched", "assigned", "in_transit", "delivered", "cancelled", "expired"]
MATCH_STATUSES = [
    "proposed",
    "transporter_accepted",
    "owner_accepted",
    "assigned",
    "rejected",
    "cancelled",
    "delivered",
]


class BackhaulOffer(ULIDPk, Timestamped, Base):
    __tablename__ = "backhaul_offers"
    __table_args__ = {"schema": "core"}
    cargo_owner_org_id: Mapped[str] = mapped_column(CHAR(26), ForeignKey("core.organizations.id"), index=True)
    created_by: Mapped[str | None] = mapped_column(CHAR(26), ForeignKey("core.users.id"))
    title: Mapped[str] = mapped_column(String(160))
    cargo_type: Mapped[str] = mapped_column(String(24), default="general")
    mass_kg: Mapped[int] = mapped_column(Integer)
    volume_m3: Mapped[float | None] = mapped_column(Float)
    length_m: Mapped[float | None] = mapped_column(Float)
    requires_body_types: Mapped[list] = mapped_column(JSON, default=list)  # e.g. ["flatbed","container"]
    origin: Mapped[str] = mapped_column(String(120))
    origin_lat: Mapped[float] = mapped_column(Float)
    origin_lon: Mapped[float] = mapped_column(Float)
    destination: Mapped[str] = mapped_column(String(120))
    dest_lat: Mapped[float] = mapped_column(Float)
    dest_lon: Mapped[float] = mapped_column(Float)
    ready_from: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    deadline: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    offered_price_kes: Mapped[float] = mapped_column(Numeric(14, 2))
    status: Mapped[str] = mapped_column(String(16), default="open", index=True)
    notes: Mapped[str | None] = mapped_column(Text)

    matches: Mapped[list[BackhaulMatch]] = relationship(back_populates="offer", lazy="selectin")


class BackhaulMatch(ULIDPk, Timestamped, Base):
    __tablename__ = "backhaul_matches"
    __table_args__ = {"schema": "core"}
    offer_id: Mapped[str] = mapped_column(CHAR(26), ForeignKey("core.backhaul_offers.id", ondelete="CASCADE"), index=True)
    vehicle_id: Mapped[str] = mapped_column(CHAR(26), ForeignKey("core.vehicles.id"), index=True)
    transporter_org_id: Mapped[str] = mapped_column(CHAR(26), ForeignKey("core.organizations.id"), index=True)
    score: Mapped[float] = mapped_column(Float)
    extra_km: Mapped[float] = mapped_column(Float)
    fuel_litres: Mapped[float] = mapped_column(Float)
    fuel_cost_kes: Mapped[float] = mapped_column(Numeric(14, 2))
    revenue_kes: Mapped[float] = mapped_column(Numeric(14, 2))
    co2_avoided_kg: Mapped[float] = mapped_column(Float)
    explanation: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(24), default="proposed", index=True)
    transporter_decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    owner_decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    assigned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    offer: Mapped[BackhaulOffer] = relationship(back_populates="matches")
