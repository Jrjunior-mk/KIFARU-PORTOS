"""Reference WIM processing pipeline (Python mirror of the STM32 firmware pipeline).

Stages (see docs/03-hardware and firmware/stm32-wim-daq/README.md):
  1. Baseline removal (median of pre-trigger window) and anti-alias/low-pass filtering (4th-order Butterworth, 1 kHz).
  2. Axle pulse detection per load channel: threshold + minimum spacing + hysteresis.
  3. Per-axle timing on two piezo rows -> speed and axle spacings.
  4. Per-axle load = calibrated pulse integral / contact time (integral method is more robust to speed than peak).
  5. Temperature compensation using the pavement probe and per-sensor coefficients.
  6. Fusion across rows (weighted by sensor noise) -> axle loads with Type-A/Type-B uncertainty (GUM) and k=2 expansion.
  7. Axle grouping (gap < 2.0 m joins a group), class code, gross vehicle mass.
  8. Sensor health: dead/noisy/saturated/inconsistent flags -> quality flags consumed by the clearance engine.

The numbers produced here are *measurements with uncertainty*. They never become a legal certificate; the static scale does.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from scipy.signal import butter, sosfiltfilt

from .signal_gen import STRIP_WIDTH_M, TYRE_CONTACT_LENGTH_M, LaneGeometry

PIPELINE_VERSION = "wim-dsp-0.3"


@dataclass
class ChannelCalibration:
    gain: float = 1.0
    offset: float = 0.0
    temp_coeff_per_c: float = 0.0
    reference_temp_c: float = 25.0
    type_b_rel_u: float = 0.02  # standard (k=1) relative uncertainty from calibration certificate


@dataclass
class AxleResult:
    index: int
    load_kg: float
    u_kg: float  # expanded uncertainty, k=2
    spacing_to_next_m: float | None
    group_no: int
    per_row_kg: dict[str, float] = field(default_factory=dict)


@dataclass
class SensorHealth:
    status: str  # ok | degraded | fault
    reasons: list[str] = field(default_factory=list)


@dataclass
class WimMeasurement:
    pipeline_version: str
    fs_hz: float
    speed_mps: float
    speed_u_mps: float
    axles: list[AxleResult]
    gvm_kg: float
    gvm_u_kg: float
    axle_config: str
    class_code: str
    quality_flags: list[str]
    sensor_health: dict[str, SensorHealth]
    pavement_temp_c: float
    coverage_factor: float = 2.0

    @property
    def axle_count(self) -> int:
        return len(self.axles)

    def to_dict(self) -> dict:
        return {
            "pipeline_version": self.pipeline_version,
            "fs_hz": self.fs_hz,
            "speed_mps": round(self.speed_mps, 3),
            "speed_u_mps": round(self.speed_u_mps, 3),
            "axles": [
                {
                    "index": a.index,
                    "load_kg": round(a.load_kg),
                    "u_kg": round(a.u_kg),
                    "spacing_to_next_m": None if a.spacing_to_next_m is None else round(a.spacing_to_next_m, 3),
                    "group_no": a.group_no,
                    "per_row_kg": {k: round(v) for k, v in a.per_row_kg.items()},
                }
                for a in self.axles
            ],
            "gvm_kg": round(self.gvm_kg),
            "gvm_u_kg": round(self.gvm_u_kg),
            "axle_config": self.axle_config,
            "class_code": self.class_code,
            "quality_flags": list(self.quality_flags),
            "sensor_health": {k: {"status": v.status, "reasons": v.reasons} for k, v in self.sensor_health.items()},
            "pavement_temp_c": round(self.pavement_temp_c, 1),
            "coverage_factor": self.coverage_factor,
        }


# ------------------------------------------------------------------ filtering
def lowpass(x: np.ndarray, fs: float, fc: float = 1000.0, order: int = 4) -> np.ndarray:
    sos = butter(order, fc / (fs / 2), btype="low", output="sos")
    return sosfiltfilt(sos, x)


def remove_baseline(x: np.ndarray, fs: float, pre_s: float = 0.2) -> np.ndarray:
    n = max(8, int(pre_s * fs))
    return x - np.median(x[:n])


# ------------------------------------------------------------------ pulse detection
def detect_pulses(x: np.ndarray, fs: float, threshold: float, min_gap_s: float) -> list[tuple[int, int, int]]:
    """Return (start, peak, end) sample indices of pulses above `threshold` with hysteresis at 50 %."""
    above = x > threshold
    pulses: list[tuple[int, int, int]] = []
    i, n = 0, len(x)
    min_gap = int(min_gap_s * fs)
    while i < n:
        if above[i]:
            start = i
            while i < n and x[i] > 0.5 * threshold:
                i += 1
            end = i
            peak = start + int(np.argmax(x[start:end]))
            if pulses and (start - pulses[-1][2]) < min_gap:
                # merge with previous pulse (same tyre, noisy edge)
                ps, pp, _ = pulses[-1]
                pulses[-1] = (ps, pp if x[pp] >= x[peak] else peak, end)
            else:
                pulses.append((start, peak, end))
        i += 1
    return pulses


def pulse_load(x: np.ndarray, fs: float, start: int, end: int, speed_mps: float, contact_len_m: float) -> float:
    """Integral method: load ~ (1/T_contact) * integral(pulse) * (pi/2) for a half-sine pulse of duration T_contact.

    For a half-sine of amplitude A and duration T, integral = 2*A*T/pi  =>  A = integral * pi / (2*T).
    T is computed from speed and the effective contact length so the estimate is speed-invariant.
    """
    T = contact_len_m / speed_mps
    integral = float(np.trapezoid(x[start:end], dx=1.0 / fs))
    return integral * np.pi / (2.0 * T)


# ------------------------------------------------------------------ health
def channel_health(x: np.ndarray, pulses: list, expected_axles: int | None, name: str) -> SensorHealth:
    reasons: list[str] = []
    rms = float(np.sqrt(np.mean(x[: max(8, len(x) // 10)] ** 2)))
    if np.max(np.abs(x)) < 50.0:
        return SensorHealth("fault", [f"{name}: no signal (dead channel)"])
    if rms > 800.0:
        reasons.append(f"{name}: baseline noise {rms:.0f} kg-eq exceeds 800")
    flat_top = np.sum(np.isclose(x, np.max(x), rtol=1e-6)) > 8
    if flat_top:
        reasons.append(f"{name}: saturation/flat-top detected")
    if expected_axles is not None and len(pulses) != expected_axles:
        reasons.append(f"{name}: {len(pulses)} pulses vs {expected_axles} expected")
    if any("saturation" in r for r in reasons) or (expected_axles and abs(len(pulses) - expected_axles) > 1):
        return SensorHealth("fault", reasons)
    return SensorHealth("degraded" if reasons else "ok", reasons)


# ------------------------------------------------------------------ main pipeline
def process_pass(
    channels: dict[str, np.ndarray],
    fs: float,
    geometry: LaneGeometry | None = None,
    calibration: dict[str, ChannelCalibration] | None = None,
    pavement_temp_c: float = 30.0,
    threshold_kg: float = 800.0,
) -> WimMeasurement:
    geometry = geometry or LaneGeometry()
    calibration = calibration or {}
    flags: list[str] = []
    health: dict[str, SensorHealth] = {}

    load_rows = [k for k in channels if k.startswith("P") or k == "BP"]
    filtered: dict[str, np.ndarray] = {}
    pulses: dict[str, list[tuple[int, int, int]]] = {}
    for name in load_rows:
        cal = calibration.get(name, ChannelCalibration())
        x = remove_baseline(channels[name], fs)
        x = lowpass(x, fs)
        temp_factor = 1.0 + cal.temp_coeff_per_c * (pavement_temp_c - cal.reference_temp_c)
        x = (x - cal.offset) * cal.gain / temp_factor
        filtered[name] = x
        pulses[name] = detect_pulses(x, fs, threshold_kg, min_gap_s=0.03)

    # consensus axle count = mode of pulse counts from healthy-looking rows
    counts = [len(p) for p in pulses.values() if len(p) > 0]
    if not counts:
        for name in load_rows:
            health[name] = channel_health(filtered[name], pulses[name], None, name)
        return WimMeasurement(
            PIPELINE_VERSION, fs, 0.0, 0.0, [], 0.0, 0.0, "", "UNKNOWN", ["no_axles_detected"], health, pavement_temp_c
        )
    axle_count = int(np.bincount(counts).argmax())
    for name in load_rows:
        health[name] = channel_health(filtered[name], pulses[name], axle_count, name)
    good_rows = [n for n in load_rows if health[n].status != "fault" and len(pulses[n]) == axle_count]
    if any(h.status == "fault" for h in health.values()):
        flags.append("sensor_fault")
    if any(h.status == "degraded" for h in health.values()):
        flags.append("sensor_degraded")

    # --- speed from the two piezo rows with the largest separation among good rows
    piezo_rows = [n for n in good_rows if n.startswith("P")]
    speed_samples: list[float] = []
    if len(piezo_rows) >= 2:
        a, b = piezo_rows[0], piezo_rows[-1]
        dx = geometry.positions_m[b] - geometry.positions_m[a]
        for (_, pa, _), (_, pb, _) in zip(pulses[a], pulses[b], strict=True):
            dt = (pb - pa) / fs
            if dt > 0:
                speed_samples.append(dx / dt)
    if speed_samples:
        speed = float(np.mean(speed_samples))
        speed_u = float(2 * np.std(speed_samples, ddof=1) / np.sqrt(len(speed_samples))) if len(speed_samples) > 1 else 0.5
    else:
        flags.append("speed_unavailable")
        speed, speed_u = 15.0, 5.0  # fallback, forces AMBER through flag

    if speed < 3.0 or speed > 30.0:
        flags.append("speed_out_of_range")

    # --- axle spacings from the first good row
    ref_row = good_rows[0] if good_rows else load_rows[0]
    peaks = [p for _, p, _ in pulses[ref_row]]
    spacings = [((peaks[i + 1] - peaks[i]) / fs) * speed for i in range(len(peaks) - 1)]

    # --- loads per row, per axle
    per_axle_rows: list[dict[str, float]] = [dict() for _ in range(axle_count)]
    for name in good_rows:
        contact = (TYRE_CONTACT_LENGTH_M + STRIP_WIDTH_M) if name.startswith("P") else (0.5 + TYRE_CONTACT_LENGTH_M)
        for i, (s, _, e) in enumerate(pulses[name]):
            per_axle_rows[i][name] = pulse_load(filtered[name], fs, s, e, speed, contact)

    axles: list[AxleResult] = []
    for i in range(axle_count):
        vals = per_axle_rows[i]
        if not vals:
            flags.append("axle_load_missing")
            axles.append(AxleResult(i, 0.0, 1e9, None, 1, {}))
            continue
        # weights: bending plate is lower-noise than piezo strips
        w = np.array([3.0 if k == "BP" else 1.0 for k in vals])
        v = np.array(list(vals.values()))
        mean = float(np.sum(w * v) / np.sum(w))
        # Type A: spread across rows (dynamic component); Type B: calibration uncertainty
        type_a = float(np.sqrt(np.sum(w * (v - mean) ** 2) / np.sum(w) / max(1, len(v) - 1))) if len(v) > 1 else 0.05 * mean
        type_b = np.sqrt(np.mean([calibration.get(k, ChannelCalibration()).type_b_rel_u ** 2 for k in vals])) * mean
        u_c = float(np.sqrt(type_a**2 + type_b**2))
        axles.append(AxleResult(i, mean, 2.0 * u_c, spacings[i] if i < len(spacings) else None, 1, vals))

    # --- grouping: axles closer than 2.0 m belong to the same group
    group = 1
    for a in axles:
        a.group_no = group
        if a.spacing_to_next_m is not None and a.spacing_to_next_m >= 2.0:
            group += 1
    group_sizes: dict[int, int] = {}
    for a in axles:
        group_sizes[a.group_no] = group_sizes.get(a.group_no, 0) + 1
    axle_config = "+".join(str(group_sizes[g]) for g in sorted(group_sizes))

    gvm = float(sum(a.load_kg for a in axles))
    gvm_u = float(np.sqrt(sum((a.u_kg / 2.0) ** 2 for a in axles))) * 2.0

    class_code = {1: "LGV", 2: "HGV2", 3: "HGV3", 4: "HGV4", 5: "HGV5", 6: "HGV6", 7: "HGV7"}.get(axle_count, "HGV7+")
    if len(good_rows) < 2:
        flags.append("insufficient_rows")
    if gvm > 0 and gvm_u / gvm > 0.10:
        flags.append("high_uncertainty")

    return WimMeasurement(
        PIPELINE_VERSION,
        fs,
        speed,
        speed_u,
        axles,
        gvm,
        gvm_u,
        axle_config,
        class_code,
        sorted(set(flags)),
        health,
        pavement_temp_c,
    )
