"""WIM + identification simulator (Phase 2 deliverable). Everything it produces is tagged source=simulated.

It picks a registered vehicle (or an unregistered plate), builds a physically-plausible truck profile for the
vehicle's axle configuration, synthesises 8 kHz lane signals, runs the SAME DSP pipeline the firmware mirrors, and
simulates ANPR/RFID reads with realistic failure modes (misread, missing tag, cloned tag).
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session

from kifaru_wim_dsp import (
    ChannelCalibration,
    LaneGeometry,
    SensorModel,
    TruckProfile,
    generate_pass,
    process_pass,
)
from kifaru_wim_dsp.signal_gen import PROFILES

from ..models import Lane, Vehicle, WeighingEvent
from . import weighing_service

CONFIG_TO_PROFILE = {
    "1+1": "2A_rigid",
    "1+2": "3A_rigid",
    "1+1+2": "4A_semi_1+1+2",
    "1+2+2": "5A_semi_1+2+2",
    "1+2+3": "6A_semi_1+2+3",
    "1+3+3": "7A_semi_1+3+3",
}


@dataclass
class SimOptions:
    overload_prob: float = 0.15
    anpr_misread_prob: float = 0.05
    rfid_missing_prob: float = 0.10
    clone_prob: float = 0.01
    sensor_fault_prob: float = 0.03
    unregistered_prob: float = 0.05
    pavement_temp_c: float = 32.0
    speed_mps: float | None = None
    force_gvm_kg: int | None = None
    vehicle_id: str | None = None
    seed: int | None = None


def _scramble_plate(plate: str, rng: np.random.Generator) -> str:
    chars = list(plate)
    swaps = {"0": "O", "O": "0", "1": "I", "I": "1", "8": "B", "B": "8", "5": "S", "S": "5"}
    idx = [i for i, c in enumerate(chars) if c in swaps]
    if idx:
        i = int(rng.choice(idx))
        chars[i] = swaps[chars[i]]
    return "".join(chars)


def simulate_pass(db: Session, lane: Lane, opts: SimOptions | None = None) -> WeighingEvent:
    opts = opts or SimOptions()
    rng = np.random.default_rng(opts.seed)

    vehicles = db.execute(select(Vehicle).where(Vehicle.status == "active")).scalars().all()
    vehicle: Vehicle | None = None
    if opts.vehicle_id:
        vehicle = db.get(Vehicle, opts.vehicle_id)
    elif vehicles and rng.random() >= opts.unregistered_prob:
        vehicle = vehicles[int(rng.integers(len(vehicles)))]

    cfg = vehicle.axle_config if vehicle else str(rng.choice(list(CONFIG_TO_PROFILE)))
    prof = PROFILES[CONFIG_TO_PROFILE.get(cfg, "4A_semi_1+1+2")]
    loads = np.array(prof["typical_loads"], dtype=float) * rng.uniform(0.55, 1.0)
    if rng.random() < opts.overload_prob:
        loads *= rng.uniform(1.08, 1.30)
    loads *= rng.uniform(0.95, 1.05, size=len(loads))
    if opts.force_gvm_kg:
        loads *= opts.force_gvm_kg / loads.sum()
    truck = TruckProfile(
        axle_loads_kg=[float(round(x)) for x in loads],
        axle_spacings_m=list(prof["spacings"]),
        speed_mps=opts.speed_mps or float(rng.uniform(8.0, 25.0)),
        bounce_hz=float(rng.uniform(1.5, 3.5)),
        bounce_frac=float(rng.uniform(0.01, 0.06)),
        bounce_phase=float(rng.uniform(0, 2 * np.pi)),
    )
    sensors = {k: SensorModel(pavement_temp_c=opts.pavement_temp_c, temp_coeff_per_c=-0.002) for k in ("P1", "P2", "P3", "BP")}
    if rng.random() < opts.sensor_fault_prob:
        k = str(rng.choice(["P1", "P2", "P3", "BP"]))
        sensors[k] = SensorModel(pavement_temp_c=opts.pavement_temp_c, fault=str(rng.choice(["dead", "noisy"])))
    geometry = LaneGeometry()
    p = generate_pass(truck, geometry=geometry, sensors=sensors, rng=rng)
    cal = {k: ChannelCalibration(temp_coeff_per_c=-0.002, type_b_rel_u=0.02) for k in sensors}
    m = process_pass(p.channels, p.fs_hz, geometry=geometry, calibration=cal, pavement_temp_c=opts.pavement_temp_c)

    # --- identity simulation
    anpr_plate, anpr_conf, rfid_epc, rfid_conf = None, None, None, None
    if vehicle:
        anpr_plate = vehicle.plate
        anpr_conf = float(rng.uniform(0.85, 0.99))
        if rng.random() < opts.anpr_misread_prob:
            anpr_plate = _scramble_plate(vehicle.plate, rng)
            anpr_conf = float(rng.uniform(0.5, 0.8))
        if vehicle.tags and rng.random() >= opts.rfid_missing_prob:
            rfid_epc = vehicle.tags[0].epc
            rfid_conf = float(rng.uniform(0.95, 0.999))
        if rng.random() < opts.clone_prob and len(vehicles) > 1:
            other = vehicles[int(rng.integers(len(vehicles)))]
            if other.id != vehicle.id and other.tags:
                rfid_epc, rfid_conf = other.tags[0].epc, 0.98  # cloned tag from another truck
    else:
        anpr_plate = f"K{rng.choice(list('CDE'))}{rng.choice(list('ABCDEFGHJKLMNPQRSTUVWXYZ'))} {rng.integers(100, 999)}{rng.choice(list('ABCDEFGHJKLMNPQRSTUVWXYZ'))}"
        anpr_conf = float(rng.uniform(0.7, 0.95))

    return weighing_service.process_lane_pass(
        db,
        lane,
        m.to_dict(),
        anpr_plate,
        anpr_conf,
        rfid_epc,
        rfid_conf,
        source="simulated",
        ambient_temp_c=float(opts.pavement_temp_c - 4.0),
    )
