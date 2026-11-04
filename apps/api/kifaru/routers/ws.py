"""WebSocket live feed. Clients connect with ?token=<access JWT>; events are filtered by the client's organisation
unless the role is platform-wide. Optional ?station=<id> and ?types=a,b,c filters."""
from __future__ import annotations

import asyncio
import json

import jwt
from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect

from ..events import bus
from ..security import decode_token

router = APIRouter(tags=["realtime"])
PLATFORM_WIDE = {"platform_admin", "port_controller", "weighbridge_operator", "auditor", "regulator_readonly"}


@router.websocket("/ws/events")
async def ws_events(ws: WebSocket, token: str = Query(...), station: str | None = None, types: str | None = None):
    try:
        claims = decode_token(token)
    except jwt.PyJWTError:
        await ws.close(code=4401)
        return
    roles = set(claims.get("roles", []))
    org = claims.get("org")
    wanted = set(types.split(",")) if types else None

    def flt(ev: dict) -> bool:
        if station and ev.get("station_id") not in (None, station):
            return False
        if wanted and ev["type"] not in wanted:
            return False
        if roles & PLATFORM_WIDE:
            return True
        # tenant scoping: org-tagged events only for that org; station operational events are visible to all authenticated users
        return ev.get("org_id") in (None, org)

    await ws.accept()
    sid, q = bus.subscribe(flt)
    try:
        await ws.send_text(json.dumps({"type": "hello", "recent": [e for e in bus.recent(20) if flt(e)]}, default=str))
        while True:
            try:
                ev = await asyncio.wait_for(q.get(), timeout=25)
                await ws.send_text(json.dumps(ev, default=str))
            except TimeoutError:
                await ws.send_text(json.dumps({"type": "ping"}))
    except WebSocketDisconnect:
        pass
    finally:
        bus.unsubscribe(sid)
