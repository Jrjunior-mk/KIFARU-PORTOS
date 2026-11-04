from __future__ import annotations

from datetime import datetime

from sqlalchemy import CHAR, Boolean, DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, Timestamped, ULIDPk

SENSOR_KINDS = [
    "piezo_quartz",
    "piezo_polymer",
    "bending_plate",
    "strain_gauge",
    "inductive_loop",
    "radar_speed",
    "ir_beam",
    "anpr_camera",
    "rfid_reader",
    "pavement_temp",
    "ambient_temp_rh",
    "wheel_detector",
]


class WeighingStation(ULIDPk, Timestamped, Base):
    __tablename__ = "weighing_stations"
    __table_args__ = {"schema": "core"}
    code: Mapped[str] = mapped_column(String(16), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(120))
    lat: Mapped[float] = mapped_column(Float)
    lon: Mapped[float] = mapped_column(Float)
    capacity_per_hour: Mapped[int] = mapped_column(Integer, default=120)
    static_capacity_per_hour: Mapped[int] = mapped_column(Integer, default=40)
    alt_allowed: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(16), default="operational")  # operational, degraded, offline
    timezone: Mapped[str] = mapped_column(String(40), default="Africa/Nairobi")

    lanes: Mapped[list[Lane]] = relationship(back_populates="station", lazy="selectin")


class Lane(ULIDPk, Timestamped, Base):
    __tablename__ = "lanes"
    __table_args__ = {"schema": "core"}
    station_id: Mapped[str] = mapped_column(CHAR(26), ForeignKey("core.weighing_stations.id"), index=True)
    lane_no: Mapped[int] = mapped_column(Integer)
    type: Mapped[str] = mapped_column(String(16), default="wim_highspeed")  # wim_highspeed, wim_lowspeed, static
    direction: Mapped[str] = mapped_column(String(16), default="inbound")
    status: Mapped[str] = mapped_column(String(16), default="operational")
    device_id: Mapped[str | None] = mapped_column(String(64), unique=True)  # IoT thing name / edge gateway id
    calibration_valid_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    station: Mapped[WeighingStation] = relationship(back_populates="lanes")
    sensors: Mapped[list[Sensor]] = relationship(back_populates="lane", lazy="selectin")


class Sensor(ULIDPk, Timestamped, Base):
    __tablename__ = "sensors"
    __table_args__ = {"schema": "core"}
    lane_id: Mapped[str] = mapped_column(CHAR(26), ForeignKey("core.lanes.id"), index=True)
    kind: Mapped[str] = mapped_column(String(24))
    serial: Mapped[str | None] = mapped_column(String(64))
    channel: Mapped[int | None] = mapped_column(Integer)
    install_position_m: Mapped[float | None] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String(16), default="ok")  # ok, degraded, fault
    health_reason: Mapped[str | None] = mapped_column(String(200))
    last_reading_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    lane: Mapped[Lane] = relationship(back_populates="sensors")
    calibrations: Mapped[list[CalibrationRecord]] = relationship(back_populates="sensor")


class CalibrationRecord(ULIDPk, Timestamped, Base):
    __tablename__ = "calibration_records"
    __table_args__ = {"schema": "core"}
    sensor_id: Mapped[str] = mapped_column(CHAR(26), ForeignKey("core.sensors.id"), index=True)
    method: Mapped[str] = mapped_column(String(40))  # reference_vehicle, static_scale_comparison, shunt, bench
    reference_mass_kg: Mapped[int | None] = mapped_column(Integer)
    gain: Mapped[float] = mapped_column(Float, default=1.0)
    offset: Mapped[float] = mapped_column(Float, default=0.0)
    temp_coeff_per_c: Mapped[float] = mapped_column(Float, default=0.0)
    reference_temp_c: Mapped[float] = mapped_column(Float, default=25.0)
    uncertainty_pct: Mapped[float] = mapped_column(Float, default=5.0)
    valid_from: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    valid_to: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    performed_by: Mapped[str | None] = mapped_column(CHAR(26), ForeignKey("core.users.id"))
    notes: Mapped[str | None] = mapped_column(String(500))

    sensor: Mapped[Sensor] = relationship(back_populates="calibrations")


class SensorReading(Base):
    """Decimated readings (health stats, temperatures), NOT the raw 8 kHz stream. Partitioned monthly in PostgreSQL."""

    __tablename__ = "sensor_readings"
    __table_args__ = {"schema": "ts"}
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    sensor_id: Mapped[str] = mapped_column(CHAR(26), index=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    metric: Mapped[str] = mapped_column(String(32))  # temp_c, noise_rms, baseline, peak, health
    value: Mapped[float] = mapped_column(Float)
    quality: Mapped[str] = mapped_column(String(8), default="ok")
