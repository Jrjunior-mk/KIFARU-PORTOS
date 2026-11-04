"""Notifications: in-app (WS + inbox), SMS (Africa's Talking adapter, mock by default), email (SES/SMTP adapter, mock by default)."""
from __future__ import annotations

from datetime import datetime

import httpx
import structlog
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..deps import CurrentUser, DbDep, require_roles, Principal
from ..events import publish
from ..models import ApiIntegration, Notification, User, utcnow

log = structlog.get_logger(__name__)
router = APIRouter(prefix="/notifications", tags=["notifications"])

SMS_TEMPLATES = {  # <= 160 chars, Kiswahili/English, for low-bandwidth cargo owners and drivers
    "slot_assigned": "KIFARU: {plate} slot {slot} at {station}. Est wait {wait} min. Reply STOP to opt out.",
    "clearance": "KIFARU: {plate} {decision} at {station}. {instruction}",
    "cargo_stage": "KIFARU: Shipment {ref} now {stage}. ETA release {eta}.",
    "backhaul": "KIFARU: Return load {title} {origin}->{dest}, KES {price}. Open app to accept.",
    "delivered": "KIFARU: Shipment {ref} delivered. Asante.",
}


def _integration(db: Session, name: str) -> ApiIntegration | None:
    return db.execute(select(ApiIntegration).where(ApiIntegration.name == name)).scalar_one_or_none()


def send_sms(db: Session, to: str, text: str) -> tuple[str, str | None]:
    """Returns (status, provider_ref). Real mode uses Africa's Talking REST API when `api_key`/`username` are configured
    (secrets come from the environment / Secrets Manager, never from the DB)."""
    integ = _integration(db, "sms")
    if integ is None or integ.mode != "real":
        log.info("sms_mock", to=to, text=text)
        return "sent", "mock-sms"
    import os

    username = os.environ.get("KIFARU_AT_USERNAME")
    api_key = os.environ.get("KIFARU_AT_API_KEY")
    if not (username and api_key):
        return "failed", None
    try:
        r = httpx.post("https://api.africastalking.com/version1/messaging", headers={"apiKey": api_key, "Accept": "application/json"},
                       data={"username": username, "to": to, "message": text, "from": integ.config.get("sender_id", "")}, timeout=10)
        r.raise_for_status()
        return "sent", r.json().get("SMSMessageData", {}).get("Recipients", [{}])[0].get("messageId")
    except Exception as exc:  # noqa: BLE001
        log.warning("sms_failed", error=str(exc))
        return "failed", None


def notify(db: Session, *, user_id: str | None, org_id: str | None, template: str, title: str, body: str, payload: dict | None = None, channels=("ws",)) -> list[Notification]:
    out = []
    user = db.get(User, user_id) if user_id else None
    for ch in channels:
        n = Notification(user_id=user_id, org_id=org_id, channel=ch, template=template, title=title, body=body, payload=payload or {})
        if ch == "ws":
            n.status, n.sent_at = "sent", utcnow()
            publish("notification", {"user_id": user_id, "org_id": org_id, "title": title, "body": body, "template": template, **(payload or {})}, org_id=org_id)
        elif ch == "sms":
            phone = user.pii.phone_enc if user and user.pii else None
            if phone:
                n.status, n.provider_ref = send_sms(db, phone, body[:160])
                n.sent_at = utcnow()
            else:
                n.status, n.error = "failed", "no phone on record"
        elif ch == "email":
            n.status, n.sent_at, n.provider_ref = "sent", utcnow(), "mock-email"
        db.add(n)
        out.append(n)
    db.flush()
    return out


class NotificationOut(BaseModel):
    id: str
    channel: str
    template: str
    title: str
    body: str
    payload: dict
    status: str
    created_at: datetime
    read_at: datetime | None


@router.get("", response_model=list[NotificationOut])
def inbox(p: CurrentUser, db: DbDep, unread_only: bool = False):
    q = select(Notification).where((Notification.user_id == p.user.id) | ((Notification.org_id == p.org_id) & (Notification.user_id.is_(None)))).order_by(Notification.created_at.desc()).limit(100)
    if unread_only:
        q = q.where(Notification.read_at.is_(None))
    return [NotificationOut(id=n.id, channel=n.channel, template=n.template, title=n.title, body=n.body, payload=n.payload, status=n.status, created_at=n.created_at, read_at=n.read_at) for n in db.execute(q).scalars()]


@router.post("/{notification_id}/read", status_code=204)
def mark_read(notification_id: str, p: CurrentUser, db: DbDep):
    n = db.get(Notification, notification_id)
    if n is None:
        raise HTTPException(404, "Not found")
    n.read_at = utcnow()
    db.commit()


class SendIn(BaseModel):
    user_id: str | None = None
    org_id: str | None = None
    template: str = Field(pattern="^(slot_assigned|clearance|cargo_stage|backhaul|delivered|custom)$")
    title: str = Field(max_length=160)
    body: str = Field(max_length=1000)
    channels: list[str] = ["ws"]
    payload: dict = {}


@router.post("/send", response_model=list[NotificationOut], status_code=201)
def send(body: SendIn, db: DbDep, p: Principal = Depends(require_roles("platform_admin", "port_controller", "dispatcher", "transporter_admin"))):
    ns = notify(db, user_id=body.user_id, org_id=body.org_id, template=body.template, title=body.title, body=body.body, payload=body.payload, channels=tuple(body.channels))
    db.commit()
    return [NotificationOut(id=n.id, channel=n.channel, template=n.template, title=n.title, body=n.body, payload=n.payload, status=n.status, created_at=n.created_at, read_at=n.read_at) for n in ns]


@router.get("/templates/sms")
def sms_templates():
    return SMS_TEMPLATES
