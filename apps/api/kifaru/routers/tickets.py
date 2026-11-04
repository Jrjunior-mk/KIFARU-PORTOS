from __future__ import annotations

from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel
from sqlalchemy import select

from ..deps import CurrentUser, DbDep
from ..models import DigitalTicket
from ..services import tickets as svc

router = APIRouter(prefix="/tickets", tags=["tickets"])


class TicketOut(BaseModel):
    id: str
    type: str
    payload: dict
    signature: str
    signer_key_id: str
    qr_token: str
    status: str
    signature_valid: bool


def _out(t: DigitalTicket) -> TicketOut:
    return TicketOut(id=t.id, type=t.type, payload=t.payload, signature=t.signature, signer_key_id=t.signer_key_id, qr_token=t.qr_token, status=t.status, signature_valid=svc.verify(t))


@router.get("/{ticket_id}", response_model=TicketOut)
def get_ticket(ticket_id: str, p: CurrentUser, db: DbDep):
    t = db.get(DigitalTicket, ticket_id)
    if t is None:
        raise HTTPException(404, "Ticket not found")
    return _out(t)


@router.get("/{ticket_id}/qr.svg")
def ticket_qr(ticket_id: str, p: CurrentUser, db: DbDep):
    t = db.get(DigitalTicket, ticket_id)
    if t is None:
        raise HTTPException(404, "Ticket not found")
    return Response(svc.qr_svg(t), media_type="image/svg+xml")


class VerifyOut(BaseModel):
    valid: bool
    ticket_type: str | None = None
    legal_status: str | None = None
    plate: str | None = None
    gvm_kg: int | None = None
    decision: str | None = None
    occurred_at: str | None = None
    station: str | None = None
    source: str | None = None
    evidence_hash: str | None = None
    status: str | None = None
    note: str | None = None


@router.get("/verify/{qr_token}", response_model=VerifyOut, tags=["public"])
def verify_public(qr_token: str, db: DbDep):
    """Public, unauthenticated verification of a QR ticket. Returns only non-sensitive fields."""
    t = db.execute(select(DigitalTicket).where(DigitalTicket.qr_token == qr_token)).scalar_one_or_none()
    if t is None:
        return VerifyOut(valid=False)
    ok = svc.verify(t)
    pl = t.payload
    return VerifyOut(valid=ok, ticket_type=t.type, legal_status=pl.get("legal_status"), plate=pl.get("plate"), gvm_kg=pl.get("gvm_kg"),
                     decision=pl.get("decision"), occurred_at=pl.get("occurred_at"), station=pl.get("station"), source=pl.get("source"), evidence_hash=pl.get("evidence_hash"),
                     status=t.status, note="superseded by a later ticket for the same decision (e.g. static certification)" if t.status == "superseded" else None)
