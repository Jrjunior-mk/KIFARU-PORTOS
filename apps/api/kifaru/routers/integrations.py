"""External integration adapters (MP §5). Every adapter has a documented contract, validation, retry, audit and health.

No government endpoint is fabricated: adapters run in `mock` mode until the owner supplies authorised credentials and
base URLs via environment/Secrets Manager, at which point `mode` can be switched to `real` by a platform admin. Real-mode
calls go through `_call_real`, which only executes when `base_url` is configured.
"""
from __future__ import annotations

import os
from datetime import datetime
from typing import Any

import httpx
import structlog
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..deps import CurrentUser, DbDep, audit, require_roles, Principal
from ..models import ApiIntegration, utcnow

log = structlog.get_logger(__name__)
router = APIRouter(prefix="/integrations", tags=["integrations"])

ADAPTERS: dict[str, dict[str, Any]] = {
    "kenha": {"display": "KeNHA axle-load enforcement", "contract": "POST /v1/wim-events {plate, gvm_kg, axle_loads[], decision, station, ticket_id} -> {ack_id}; GET /v1/watchlist -> [{plate, reason}]"},
    "kpa": {"display": "Kenya Ports Authority gate / KWATOS", "contract": "GET /v1/trucks/{plate}/gate-status -> {stage, gate, eta}; POST /v1/appointments"},
    "kra": {"display": "KRA iCMS customs declarations", "contract": "GET /v1/declarations/{reference} -> {status, declared_mass_kg, items[]}; webhook status updates"},
    "ntsa": {"display": "NTSA vehicle registry (TIMS)", "contract": "GET /v1/vehicles/{plate} -> {owner_org, axle_config, tare_kg, class}"},
    "customs": {"display": "Authorised customs/ECTS seal provider", "contract": "GET /v1/seals/{seal_id} -> {status, armed_at, last_position}; webhook breach alerts"},
    "fleet": {"display": "Transporter fleet management platforms", "contract": "GET /vehicles, POST /positions (GPS), webhook trip events"},
    "wms": {"display": "Warehouse management systems", "contract": "GET /docks/availability, POST /inbound-appointments"},
    "payment": {"display": "Payment gateway (M-Pesa Daraja / card)", "contract": "POST /stkpush {phone, amount, ref}; callback /payments/callback"},
    "sms": {"display": "SMS (Africa's Talking)", "contract": "POST /version1/messaging {to, message}"},
    "email": {"display": "Email (SES/SMTP)", "contract": "SendEmail {to, subject, body}"},
    "maps": {"display": "Mapping and routing (OSRM / Google Routes)", "contract": "GET /route/v1/driving/{coords} -> {distance_m, duration_s}"},
    "telematics": {"display": "GPS / telematics providers", "contract": "GET /units, GET /positions?since=; webhook positions"},
}


def ensure_registry(db: Session) -> None:
    existing = {i.name for i in db.execute(select(ApiIntegration)).scalars()}
    for name, meta in ADAPTERS.items():
        if name not in existing:
            db.add(ApiIntegration(name=name, display_name=meta["display"], mode="mock", config={"contract": meta["contract"], "base_url": None}, health_status="mock"))
    db.flush()


class IntegrationOut(BaseModel):
    id: str
    name: str
    display_name: str
    mode: str
    contract: str
    base_url: str | None
    health_status: str
    last_ok_at: datetime | None
    last_error: str | None


def _out(i: ApiIntegration) -> IntegrationOut:
    return IntegrationOut(id=i.id, name=i.name, display_name=i.display_name, mode=i.mode, contract=i.config.get("contract", ""), base_url=i.config.get("base_url"),
                          health_status=i.health_status, last_ok_at=i.last_ok_at, last_error=i.last_error)


@router.get("", response_model=list[IntegrationOut])
def list_integrations(p: CurrentUser, db: DbDep):
    ensure_registry(db)
    db.commit()
    return [_out(i) for i in db.execute(select(ApiIntegration).order_by(ApiIntegration.name)).scalars()]


class ModeIn(BaseModel):
    mode: str = Field(pattern="^(mock|real)$")
    base_url: str | None = None


@router.post("/{name}/mode", response_model=IntegrationOut)
def set_mode(name: str, body: ModeIn, db: DbDep, p: Principal = Depends(require_roles("platform_admin"))):
    i = db.execute(select(ApiIntegration).where(ApiIntegration.name == name)).scalar_one_or_none()
    if i is None:
        raise HTTPException(404, "Unknown integration")
    if body.mode == "real" and not body.base_url and not i.config.get("base_url"):
        raise HTTPException(400, "real mode requires base_url (credentials via environment KIFARU_INT_<NAME>_TOKEN)")
    audit(db, p, "integration_mode", "api_integration", i.id, before={"mode": i.mode}, after=body.model_dump())
    i.mode = body.mode
    i.config = {**i.config, "base_url": body.base_url or i.config.get("base_url")}
    i.health_status = "mock" if body.mode == "mock" else "unknown"
    db.commit()
    return _out(i)


def _call_real(i: ApiIntegration, path: str, method: str = "GET", json: dict | None = None, retries: int = 2) -> dict:
    base = i.config.get("base_url")
    if not base:
        raise HTTPException(409, "integration has no base_url")
    token = os.environ.get(f"KIFARU_INT_{i.name.upper()}_TOKEN")
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    last: Exception | None = None
    for attempt in range(retries + 1):
        try:
            r = httpx.request(method, base.rstrip("/") + path, json=json, headers=headers, timeout=10)
            r.raise_for_status()
            return r.json()
        except Exception as exc:  # noqa: BLE001
            last = exc
            log.warning("integration_call_failed", name=i.name, attempt=attempt, error=str(exc))
    raise HTTPException(502, f"{i.name} call failed after retries: {last}")


@router.post("/{name}/health", response_model=IntegrationOut)
def health_check(name: str, db: DbDep, p: Principal = Depends(require_roles("platform_admin", "port_controller"))):
    i = db.execute(select(ApiIntegration).where(ApiIntegration.name == name)).scalar_one_or_none()
    if i is None:
        raise HTTPException(404, "Unknown integration")
    if i.mode == "mock":
        i.health_status, i.last_ok_at, i.last_error = "mock", utcnow(), None
    else:
        try:
            _call_real(i, "/health")
            i.health_status, i.last_ok_at, i.last_error = "ok", utcnow(), None
        except HTTPException as exc:
            i.health_status, i.last_error = "down", str(exc.detail)[:300]
    db.commit()
    return _out(i)


class LookupOut(BaseModel):
    integration: str
    mode: str
    data: dict
    label: str


@router.get("/ntsa/vehicle/{plate}", response_model=LookupOut)
def ntsa_lookup(plate: str, db: DbDep, p: Principal = Depends(require_roles("platform_admin", "port_controller", "weighbridge_operator", "transporter_admin"))):
    i = db.execute(select(ApiIntegration).where(ApiIntegration.name == "ntsa")).scalar_one_or_none()
    if i and i.mode == "real":
        return LookupOut(integration="ntsa", mode="real", data=_call_real(i, f"/v1/vehicles/{plate}"), label="live data from NTSA adapter")
    return LookupOut(integration="ntsa", mode="mock", data={"plate": plate.upper(), "axle_config": None, "note": "MOCK: no NTSA access configured"}, label="MOCK DATA — not from NTSA")


@router.get("/kra/declaration/{reference}", response_model=LookupOut)
def kra_lookup(reference: str, db: DbDep, p: Principal = Depends(require_roles("platform_admin", "port_controller", "cargo_owner", "transporter_admin"))):
    i = db.execute(select(ApiIntegration).where(ApiIntegration.name == "kra")).scalar_one_or_none()
    if i and i.mode == "real":
        return LookupOut(integration="kra", mode="real", data=_call_real(i, f"/v1/declarations/{reference}"), label="live data from KRA adapter")
    return LookupOut(integration="kra", mode="mock", data={"reference": reference, "status": "unknown", "note": "MOCK: no KRA iCMS access configured"}, label="MOCK DATA — not from KRA")


@router.get("/maps/route")
def route(p: CurrentUser, db: DbDep, from_lat: float, from_lon: float, to_lat: float, to_lon: float):
    """Routing: real mode calls an OSRM-compatible endpoint; mock uses great-circle x 1.25 road factor."""
    i = db.execute(select(ApiIntegration).where(ApiIntegration.name == "maps")).scalar_one_or_none()
    if i and i.mode == "real":
        data = _call_real(i, f"/route/v1/driving/{from_lon},{from_lat};{to_lon},{to_lat}?overview=false")
        r = data["routes"][0]
        return {"mode": "real", "distance_km": r["distance"] / 1000, "duration_min": r["duration"] / 60}
    from kifaru_ai_agents.base import ROAD_FACTOR, haversine_km

    km = haversine_km(from_lat, from_lon, to_lat, to_lon) * ROAD_FACTOR
    return {"mode": "mock", "distance_km": round(km, 1), "duration_min": round(km / 45 * 60), "label": "estimated (great-circle x 1.25) — not a routed distance"}
