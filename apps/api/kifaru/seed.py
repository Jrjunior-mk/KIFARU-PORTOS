"""Seed roles, demo organisations, users, stations, lanes, vehicles and a few shipments.

Run:  python -m kifaru.seed          (idempotent; safe to re-run)
Demo passwords are printed once and are for local development only. Production users are created via /admin/users.
"""
from __future__ import annotations

import sys
from datetime import timedelta

from sqlalchemy import select

from .db import get_engine, get_sessionmaker
from .models import (
    ROLE_NAMES,
    Base,
    CargoDeclaration,
    CargoProcessingEvent,
    ElectronicSeal,
    Fleet,
    Lane,
    Organization,
    QueueRecord,
    RfidTag,
    Role,
    Sensor,
    Shipment,
    User,
    UserPII,
    Vehicle,
    Warehouse,
    WeighingStation,
    utcnow,
)
from .routers.integrations import ensure_registry
from .routers.stations import DEFAULT_LANE_SENSORS
from .security import hash_password

DEMO_PASSWORD = "***REMOVED***"

STATIONS = [
    # code, name, lat, lon, cap/h, static cap/h, alt_allowed
    ("MRK", "Mariakani Weighbridge", -3.8617, 39.4722, 160, 50, False),
    ("ATH", "Athi River Weighbridge", -1.4522, 36.9780, 140, 45, True),
    ("MBS-GATE18", "Port of Mombasa Gate 18 (pre-gate WIM)", -4.0529, 39.6519, 200, 0, False),
    ("GLG", "Gilgil Weighbridge", -0.4928, 36.3228, 120, 40, True),
]

DEMO_USERS = [
    # email, name, roles, org key
    ("admin@demo.invalid", "Platform Administrator", ["platform_admin"], "platform"),
    ("control@demo.invalid", "Port Control Officer", ["port_controller"], "platform"),
    ("operator@demo.invalid", "Weighbridge Operator Mariakani", ["weighbridge_operator"], "platform"),
    ("auditor@demo.invalid", "Compliance Auditor", ["auditor"], "platform"),
    ("dispatch@transporter-a.invalid", "Simba Transporters Dispatch", ["transporter_admin", "dispatcher"], "simba"),
    ("driver1@transporter-a.invalid", "Driver Juma", ["driver"], "simba"),
    ("dispatch@transporter-b.invalid", "Pwani Haulers Admin", ["transporter_admin"], "pwani"),
    ("owner@cargo-a.invalid", "Mama Mboga Traders", ["cargo_owner"], "mamambo"),
    ("owner@cargo-b.invalid", "Nakuru Grains Ltd", ["cargo_owner"], "nakuru"),
    ("wh@warehouse-a.invalid", "Nairobi ICD Warehouse", ["warehouse_manager"], "icd"),
]

ORGS = {
    "platform": ("KIFARU PORTOS Platform", "platform"),
    "simba": ("Simba Transporters Ltd", "transporter"),
    "pwani": ("Pwani Haulers", "transporter"),
    "mamambo": ("Mama Mboga Traders", "cargo_owner"),
    "nakuru": ("Nakuru Grains Ltd", "cargo_owner"),
    "icd": ("Nairobi ICD Warehousing", "warehouse"),
}

VEHICLES = [
    # plate, org, axle_config, tare, max_gvm, payload, body, epc, lat, lon
    ("KDA 412B", "simba", "1+1+2", 14500, 42000, 27000, "container", "E2000017221101441890A001", -3.95, 39.55),
    ("KDB 118C", "simba", "1+2+3", 16500, 50000, 33000, "flatbed", "E2000017221101441890A002", -4.03, 39.66),
    ("KDC 905D", "simba", "1+3+3", 17500, 56000, 38000, "container", "E2000017221101441890A003", -1.30, 36.85),
    ("KCY 377F", "simba", "1+2", 9500, 26000, 16000, "tipper", "E2000017221101441890A004", -3.86, 39.48),
    ("KDE 230G", "pwani", "1+1+2", 14000, 42000, 27500, "flatbed", "E2000017221101441890B001", -3.80, 39.45),
    ("KDF 661H", "pwani", "1+2+3", 16000, 50000, 34000, "tanker", "E2000017221101441890B002", -4.05, 39.67),
    ("KCZ 844J", "pwani", "1+1", 7000, 18000, 11000, "box", None, -1.29, 36.82),
    ("KDG 102K", "pwani", "1+2+3", 16200, 50000, 33800, "reefer", "E2000017221101441890B004", -0.30, 36.07),
]


def seed(verbose: bool = True) -> None:
    engine = get_engine()
    Base.metadata.create_all(engine)
    Session = get_sessionmaker()
    with Session() as db:
        roles = {r.name: r for r in db.execute(select(Role)).scalars()}
        for name in ROLE_NAMES:
            if name not in roles:
                roles[name] = Role(name=name, description=name.replace("_", " ").title())
                db.add(roles[name])
        db.flush()

        orgs: dict[str, Organization] = {}
        for key, (name, typ) in ORGS.items():
            o = db.execute(select(Organization).where(Organization.name == name)).scalar_one_or_none()
            if o is None:
                o = Organization(name=name, type=typ)
                db.add(o)
                db.flush()
            orgs[key] = o

        for email, full_name, role_names, org_key in DEMO_USERS:
            u = db.execute(select(User).where(User.email == email)).scalar_one_or_none()
            if u is None:
                u = User(email=email, password_hash=hash_password(DEMO_PASSWORD), org_id=orgs[org_key].id)
                u.roles = [roles[r] for r in role_names]
                db.add(u)
                db.flush()
                db.add(UserPII(user_id=u.id, full_name=full_name, phone_enc="+254700000000"))

        stations: dict[str, WeighingStation] = {}
        for code, name, lat, lon, cap, scap, alt in STATIONS:
            st = db.execute(select(WeighingStation).where(WeighingStation.code == code)).scalar_one_or_none()
            if st is None:
                st = WeighingStation(code=code, name=name, lat=lat, lon=lon, capacity_per_hour=cap, static_capacity_per_hour=scap, alt_allowed=alt)
                db.add(st)
                db.flush()
                for lane_no in (1, 2):
                    lane = Lane(station_id=st.id, lane_no=lane_no, type="wim_highspeed", direction="inbound" if lane_no == 1 else "outbound",
                                device_id=f"gw-{code.lower()}-l{lane_no}", calibration_valid_to=utcnow() + timedelta(days=150))
                    db.add(lane)
                    db.flush()
                    for i, (kind, pos) in enumerate(DEFAULT_LANE_SENSORS):
                        db.add(Sensor(lane_id=lane.id, kind=kind, channel=i, install_position_m=pos, serial=f"{code}-L{lane_no}-{kind[:4].upper()}-{i:02d}"))
                if scap:
                    db.add(Lane(station_id=st.id, lane_no=9, type="static", direction="inbound", device_id=f"static-{code.lower()}"))
                db.add(QueueRecord(station_id=st.id, ts=utcnow(), kind="observed", queue_len=12, avg_wait_s=900, utilisation=0.6, arrivals_per_hour=cap * 0.6, source="simulated"))
            stations[code] = st

        fleets: dict[str, Fleet] = {}
        for key in ("simba", "pwani"):
            f = db.execute(select(Fleet).where(Fleet.org_id == orgs[key].id)).scalar_one_or_none()
            if f is None:
                f = Fleet(org_id=orgs[key].id, name=f"{orgs[key].name} main fleet")
                db.add(f)
                db.flush()
            fleets[key] = f

        vehicles: dict[str, Vehicle] = {}
        for plate, org_key, cfg, tare, gvm, payload, body, epc, lat, lon in VEHICLES:
            v = db.execute(select(Vehicle).where(Vehicle.plate == plate)).scalar_one_or_none()
            if v is None:
                v = Vehicle(org_id=orgs[org_key].id, fleet_id=fleets[org_key].id, plate=plate, axle_config=cfg, class_code=f"HGV{sum(int(x) for x in cfg.split('+'))}",
                            tare_kg=tare, max_gvm_kg=gvm, payload_capacity_kg=payload, body_type=body, last_lat=lat, last_lon=lon, last_seen_at=utcnow())
                db.add(v)
                db.flush()
                if epc:
                    db.add(RfidTag(epc=epc, vehicle_id=v.id, issued_at=utcnow()))
            vehicles[plate] = v

        wh = db.execute(select(Warehouse).where(Warehouse.org_id == orgs["icd"].id)).scalar_one_or_none()
        if wh is None:
            wh = Warehouse(org_id=orgs["icd"].id, name="Nairobi ICD Shed 4", lat=-1.3200, lon=36.8930, dock_count=6)
            db.add(wh)
            db.flush()

        if not db.execute(select(Shipment)).scalars().first():
            demo = [
                ("mamambo", "KDA 412B", "40ft container — FMCG for Nairobi", "container", "Port of Mombasa", "Nairobi ICD", 24000, "KRA-ICMS-2026-118822", "SEAL-7731", "at_port"),
                ("nakuru", "KDB 118C", "Bagged fertiliser 30 t", "general", "Port of Mombasa", "Nakuru", 30000, "KRA-ICMS-2026-118901", None, "declared"),
                ("mamambo", None, "Dry goods 8 t (truck not yet assigned)", "general", "Mariakani", "Mombasa Island", 8000, None, None, "registered"),
            ]
            for org_key, plate, desc, ctype, origin, dest, mass, decl, seal, stage in demo:
                v = vehicles.get(plate) if plate else None
                s = Shipment(reference=f"KP-DEMO{len(db.new):03d}{mass % 97:02d}", owner_org_id=orgs[org_key].id, transporter_org_id=v.org_id if v else None,
                             vehicle_id=v.id if v else None, warehouse_id=wh.id if dest == "Nairobi ICD" else None, description=desc, cargo_type=ctype,
                             origin=origin, destination=dest, origin_lat=-4.05, origin_lon=39.65, dest_lat=-1.32 if "Nairobi" in dest else -0.30, dest_lon=36.89 if "Nairobi" in dest else 36.07,
                             declared_mass_kg=mass, stage=stage)
                db.add(s)
                db.flush()
                db.add(CargoProcessingEvent(shipment_id=s.id, stage="registered", occurred_at=utcnow() - timedelta(hours=30), source="platform"))
                if decl:
                    db.add(CargoDeclaration(shipment_id=s.id, reference=decl, source="manual", declared_mass_kg=mass))
                    db.add(CargoProcessingEvent(shipment_id=s.id, stage="declared", occurred_at=utcnow() - timedelta(hours=26), source="manual"))
                if seal:
                    db.add(ElectronicSeal(shipment_id=s.id, seal_id=seal, provider="mock", status="armed", armed_at=utcnow() - timedelta(hours=20)))
                if stage == "at_port":
                    db.add(CargoProcessingEvent(shipment_id=s.id, stage="at_port", occurred_at=utcnow() - timedelta(hours=18), source="manual"))

        ensure_registry(db)
        db.commit()
    if verbose:
        print("Seed complete. Demo accounts (password for all: %s):" % DEMO_PASSWORD)
        for email, _, roles_, _ in DEMO_USERS:
            print(f"  {email:40s} {', '.join(roles_)}")


if __name__ == "__main__":
    seed(verbose="--quiet" not in sys.argv)
