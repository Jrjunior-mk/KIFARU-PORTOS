"""Synthetic WIM lane signal generator.

Produces the sampled sensor channels a roadside DAQ would see for a truck pass, so the processing pipeline
(`pipeline.py`) can be developed and tested before hardware exists. It models:

* tyre contact pulse on a 50 mm piezo strip (half-sine of duration L_contact / v),
* dynamic load oscillation (suspension bounce, typically 1.5–4 Hz, amplitude a few percent of static load),
* calibration gain error, temperature sensitivity, 1/f + white noise, and
* inductive loop presence channels.

Everything here is clearly SYNTHETIC. The generator is used only for the simulator path (`source=simulated`).
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

STRIP_WIDTH_M = 0.05
TYRE_CONTACT_LENGTH_M = 0.25  # typical truck tyre contact patch length


@dataclass
class LaneGeometry:
    fs_hz: float = 8000.0
    positions_m: dict[str, float] = field(
        default_factory=lambda: {"L1": 0.0, "P1": 4.0, "P2": 7.0, "BP": 10.0, "L2": 12.0, "P3": 16.0, "L3": 19.0}
    )
    loop_length_m: float = 2.0


@dataclass
class TruckProfile:
    axle_loads_kg: list[float]
    axle_spacings_m: list[float]  # len = axles - 1
    speed_mps: float = 20.0
    bounce_hz: float = 2.5
    bounce_frac: float = 0.03  # dynamic amplitude as fraction of static load
    bounce_phase: float = 0.0
    length_m: float | None = None

    @property
    def gvm_kg(self) -> float:
        return float(sum(self.axle_loads_kg))

    @property
    def axle_offsets_m(self) -> list[float]:
        out = [0.0]
        for s in self.axle_spacings_m:
            out.append(out[-1] + s)
        return out


@dataclass
class SensorModel:
    gain: float = 1.0  # multiplicative calibration error
    temp_coeff_per_c: float = -0.002  # piezo-quartz is small; polymer much larger
    pavement_temp_c: float = 30.0
    reference_temp_c: float = 25.0
    noise_rms_frac: float = 0.01  # white noise relative to a 10 t pulse
    drift_frac: float = 0.0  # slow baseline drift
    fault: str | None = None  # None | "dead" | "noisy" | "saturated"


@dataclass
class SyntheticPass:
    fs_hz: float
    t: np.ndarray
    channels: dict[str, np.ndarray]
    truth: TruckProfile
    pavement_temp_c: float
    t0_s: float


def _pulse(t: np.ndarray, t_center: float, duration: float, amplitude: float) -> np.ndarray:
    """Half-sine load pulse (first-order model of a tyre rolling over a narrow strip)."""
    x = (t - t_center) / duration + 0.5
    inside = (x >= 0) & (x <= 1)
    out = np.zeros_like(t)
    out[inside] = amplitude * np.sin(np.pi * x[inside])
    return out


def generate_pass(
    truck: TruckProfile,
    geometry: LaneGeometry | None = None,
    sensors: dict[str, SensorModel] | None = None,
    rng: np.random.Generator | None = None,
    pre_s: float = 0.3,
    post_s: float = 0.3,
) -> SyntheticPass:
    geometry = geometry or LaneGeometry()
    rng = rng or np.random.default_rng()
    sensors = sensors or {}
    fs = geometry.fs_hz
    v = truck.speed_mps
    offsets = truck.axle_offsets_m
    lane_len = max(geometry.positions_m.values()) + geometry.loop_length_m
    total_len = lane_len + offsets[-1]
    dur = total_len / v + pre_s + post_s
    n = int(dur * fs)
    t = np.arange(n) / fs
    t0 = pre_s
    channels: dict[str, np.ndarray] = {}
    pavement_temp = np.mean([s.pavement_temp_c for s in sensors.values()]) if sensors else 30.0

    for name, pos in geometry.positions_m.items():
        sm = sensors.get(name, SensorModel())
        if name.startswith("L"):
            # loop: presence high while any part of vehicle is over loop (vehicle length ~ last offset + 2 m overhangs)
            veh_len = truck.length_m or (offsets[-1] + 3.0)
            front_enter = t0 + (pos - 1.0) / v
            rear_leave = t0 + (pos + geometry.loop_length_m + veh_len - 1.0) / v
            sig = ((t >= front_enter) & (t <= rear_leave)).astype(float)
            if sm.fault == "dead":
                sig[:] = 0.0
            channels[name] = sig
            continue
        # load sensors: piezo strips (P*) or bending plate (BP)
        sig = np.zeros(n)
        contact = (TYRE_CONTACT_LENGTH_M + STRIP_WIDTH_M) / v if name.startswith("P") else (0.5 + TYRE_CONTACT_LENGTH_M) / v
        for load, off in zip(truck.axle_loads_kg, offsets, strict=True):
            tc = t0 + (pos + off) / v
            dyn = 1.0 + truck.bounce_frac * np.sin(2 * np.pi * truck.bounce_hz * tc + truck.bounce_phase)
            amp = load * dyn
            sig += _pulse(t, tc, contact, amp)
        temp_factor = 1.0 + sm.temp_coeff_per_c * (sm.pavement_temp_c - sm.reference_temp_c)
        sig *= sm.gain * temp_factor
        noise = rng.normal(0.0, sm.noise_rms_frac * 10000.0, n)
        if sm.fault == "noisy":
            noise *= 25.0
        sig += noise + sm.drift_frac * 10000.0 * np.linspace(0, 1, n)
        if sm.fault == "dead":
            sig = rng.normal(0.0, 5.0, n)
        if sm.fault == "saturated":
            sig = np.clip(sig, -1e9, 6000.0)
        channels[name] = sig
    return SyntheticPass(fs_hz=fs, t=t, channels=channels, truth=truck, pavement_temp_c=float(pavement_temp), t0_s=t0)


# Common Kenyan/EAC truck configurations used by the simulator -----------------------------------
PROFILES: dict[str, dict] = {
    "2A_rigid": {"spacings": [4.2], "typical_loads": [5500, 9500]},
    "3A_rigid": {"spacings": [4.5, 1.35], "typical_loads": [6500, 8500, 8500]},
    "4A_semi_1+1+2": {"spacings": [3.6, 5.8, 1.35], "typical_loads": [6500, 9500, 8500, 8500]},
    "5A_semi_1+2+2": {"spacings": [3.6, 1.35, 5.6, 1.35], "typical_loads": [6500, 8500, 8500, 8500, 8500]},
    "6A_semi_1+2+3": {"spacings": [3.6, 1.35, 5.6, 1.35, 1.35], "typical_loads": [6500, 8500, 8500, 7800, 7800, 7800]},
    "7A_semi_1+3+3": {"spacings": [3.6, 1.35, 1.35, 5.4, 1.35, 1.35], "typical_loads": [6500, 7500, 7500, 7500, 7800, 7800, 7800]},
}


def random_truck(rng: np.random.Generator, overload_prob: float = 0.15, profile: str | None = None) -> TruckProfile:
    name = profile or rng.choice(list(PROFILES.keys()))
    p = PROFILES[name]
    loads = np.array(p["typical_loads"], dtype=float) * rng.uniform(0.55, 1.0)
    if rng.random() < overload_prob:
        loads = loads * rng.uniform(1.08, 1.30)
    loads = loads * rng.uniform(0.95, 1.05, size=len(loads))  # per-axle imbalance
    return TruckProfile(
        axle_loads_kg=[float(round(x)) for x in loads],
        axle_spacings_m=list(p["spacings"]),
        speed_mps=float(rng.uniform(8.0, 25.0)),
        bounce_hz=float(rng.uniform(1.5, 3.5)),
        bounce_frac=float(rng.uniform(0.01, 0.06)),
        bounce_phase=float(rng.uniform(0, 2 * np.pi)),
    )
