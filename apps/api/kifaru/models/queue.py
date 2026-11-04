from __future__ import annotations

from datetime import datetime

from sqlalchemy import CHAR, DateTime, Float, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, Timestamped, ULIDPk


class QueueRecord(ULIDPk, Base):
    """Observed or forecast queue state for a station. `kind` = observed | forecast_15 | forecast_30 | forecast_60 | forecast_120."""

    __tablename__ = "queue_records"
    __table_args__ = (Index("ix_queue_station_ts", "station_id", "ts"), {"schema": "core"})
    station_id: Mapped[str] = mapped_column(CHAR(26), ForeignKey("core.weighing_stations.id"))
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    kind: Mapped[str] = mapped_column(String(16), default="observed")
    queue_len: Mapped[int] = mapped_column(Integer, default=0)
    avg_wait_s: Mapped[int] = mapped_column(Integer, default=0)
    utilisation: Mapped[float] = mapped_column(Float, default=0.0)
    arrivals_per_hour: Mapped[float] = mapped_column(Float, default=0.0)
    lower: Mapped[int | None] = mapped_column(Integer)  # forecast interval
    upper: Mapped[int | None] = mapped_column(Integer)
    model_version: Mapped[str | None] = mapped_column(String(40))
    source: Mapped[str] = mapped_column(String(12), default="simulated")


class Appointment(ULIDPk, Timestamped, Base):
    """Weighing slot. Capacity per 15-minute window is enforced in the service layer (and by an exclusion
    constraint in PostgreSQL via migration)."""

    __tablename__ = "appointments"
    __table_args__ = (Index("ix_appt_station_slot", "station_id", "slot_start"), {"schema": "core"})
    station_id: Mapped[str] = mapped_column(CHAR(26), ForeignKey("core.weighing_stations.id"))
    vehicle_id: Mapped[str] = mapped_column(CHAR(26), ForeignKey("core.vehicles.id"), index=True)
    shipment_id: Mapped[str | None] = mapped_column(CHAR(26), ForeignKey("core.shipments.id"))
    requested_by: Mapped[str | None] = mapped_column(CHAR(26), ForeignKey("core.users.id"))
    slot_start: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    slot_end: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(16), default="booked")  # booked, arrived, completed, missed, cancelled
    priority: Mapped[int] = mapped_column(Integer, default=5)  # 1 = highest (perishable/hazardous), 9 = lowest
    est_wait_s: Mapped[int | None] = mapped_column(Integer)
    assigned_by: Mapped[str] = mapped_column(String(16), default="manual")  # manual | optimiser
