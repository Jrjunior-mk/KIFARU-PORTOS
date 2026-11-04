from __future__ import annotations

from datetime import datetime

from sqlalchemy import CHAR, Boolean, DateTime, ForeignKey, String, Table, Column, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, Timestamped, ULIDPk

ROLE_NAMES = [
    "platform_admin",
    "port_controller",
    "weighbridge_operator",
    "transporter_admin",
    "dispatcher",
    "driver",
    "cargo_owner",
    "warehouse_manager",
    "auditor",
    "regulator_readonly",
]

ORG_TYPES = ["platform", "transporter", "cargo_owner", "warehouse", "regulator", "port_authority"]


class Organization(ULIDPk, Timestamped, Base):
    __tablename__ = "organizations"
    __table_args__ = {"schema": "core"}

    name: Mapped[str] = mapped_column(String(200), index=True)
    type: Mapped[str] = mapped_column(String(32), index=True)
    status: Mapped[str] = mapped_column(String(16), default="active")

    users: Mapped[list[User]] = relationship(back_populates="org")


user_roles = Table(
    "user_roles",
    Base.metadata,
    Column("user_id", CHAR(26), ForeignKey("core.users.id", ondelete="CASCADE"), primary_key=True),
    Column("role_id", CHAR(26), ForeignKey("core.roles.id", ondelete="CASCADE"), primary_key=True),
    schema="core",
)


class Role(ULIDPk, Base):
    __tablename__ = "roles"
    __table_args__ = {"schema": "core"}
    name: Mapped[str] = mapped_column(String(40), unique=True)
    description: Mapped[str | None] = mapped_column(String(200))


class User(ULIDPk, Timestamped, Base):
    __tablename__ = "users"
    __table_args__ = {"schema": "core"}

    email: Mapped[str] = mapped_column(String(254), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    org_id: Mapped[str | None] = mapped_column(CHAR(26), ForeignKey("core.organizations.id"), index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    mfa_secret: Mapped[str | None] = mapped_column(String(64))  # encrypted at rest by DB-level KMS; TOTP base32
    mfa_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failed_logins: Mapped[int] = mapped_column(default=0)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    org: Mapped[Organization | None] = relationship(back_populates="users")
    roles: Mapped[list[Role]] = relationship(secondary=user_roles, lazy="selectin")
    pii: Mapped[UserPII | None] = relationship(back_populates="user", uselist=False, lazy="selectin")

    @property
    def role_names(self) -> list[str]:
        return [r.name for r in self.roles]


class UserPII(Base):
    """Personal data kept in the `pii` schema (separate DB role, column-level encryption in PostgreSQL)."""

    __tablename__ = "user_pii"
    __table_args__ = {"schema": "pii"}
    user_id: Mapped[str] = mapped_column(CHAR(26), ForeignKey("core.users.id", ondelete="CASCADE"), primary_key=True)
    full_name: Mapped[str] = mapped_column(String(200))
    phone_enc: Mapped[str | None] = mapped_column(String(255))
    national_id_enc: Mapped[str | None] = mapped_column(String(255))

    user: Mapped[User] = relationship(back_populates="pii")


class RefreshSession(ULIDPk, Timestamped, Base):
    __tablename__ = "refresh_sessions"
    __table_args__ = (UniqueConstraint("token_hash"), {"schema": "core"})
    user_id: Mapped[str] = mapped_column(CHAR(26), ForeignKey("core.users.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ip: Mapped[str | None] = mapped_column(String(64))
    user_agent: Mapped[str | None] = mapped_column(String(255))
    mfa_verified: Mapped[bool] = mapped_column(Boolean, default=False)
