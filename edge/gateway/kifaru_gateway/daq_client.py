"""DAQ link: byte-exact codec for the frames defined in docs/03-hardware/communications.md (mirrors
firmware/stm32-wim-daq/App/frames.c), a pass assembler that turns AXLE_EVENT + PASS_SUMMARY into the
`WimMeasurement.to_dict()` shape the API ingests, a UDP client, and a SimulatedDaq built on kifaru_wim_dsp.
"""
from __future__ import annotations

import socket
import struct
import time
import zlib
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import IntEnum

import numpy as np

from kifaru_wim_dsp import ChannelCalibration, LaneGeometry, SensorModel, TruckProfile, generate_pass, process_pass, random_truck

MAGIC = 0x4B57
VERSION = 1
HDR = struct.Struct("<HBBHHI")  # magic, version, type, seq, payload_len, t_tx_us_low  (12 bytes)
CRC_LEN = 4
UDP_PORT_TX = 5010  # DAQ -> gateway
UDP_PORT_RX = 5011  # gateway -> DAQ
CAN_BASE_DAQ_TO_GW = 0x100
CAN_BASE_GW_TO_DAQ = 0x180

DAQ_PIPELINE_VERSION = "stm32-wim-daq-0.1"
FS_HZ = 8000.0
ROW_NAMES = ("P1", "P2", "P3", "BP")
SENSOR_HEALTH_NAMES = ("P1", "P2", "P3", "BP", "L1", "L2", "L3", "IR")
HEALTH_STATUS = {0: "ok", 1: "degraded", 2: "fault"}
CLASS_CODES = {1: "LGV", 2: "HGV2", 3: "HGV3", 4: "HGV4", 5: "HGV5", 6: "HGV6", 7: "HGV7"}

# bit -> (own name, names the clearance engine understands)
QUALITY_FLAG_BITS: dict[int, tuple[str, tuple[str, ...]]] = {
    0: ("sensor_fault", ("sensor_fault",)),
    1: ("sensor_degraded", ("sensor_degraded",)),
    2: ("speed_unavailable", ("speed_unavailable",)),
    3: ("speed_out_of_range", ("speed_out_of_range",)),
    4: ("insufficient_rows", ("insufficient_rows",)),
    5: ("axle_load_missing", ("axle_load_missing",)),
    6: ("high_uncertainty", ("high_uncertainty",)),
    7: ("no_axles_detected", ("no_axles_detected",)),
    8: ("saturation", ("saturation", "sensor_fault")),
    9: ("loop_inconsistent", ("loop_inconsistent", "sensor_degraded")),
    10: ("speed_inconsistent", ("speed_inconsistent", "sensor_degraded")),
    11: ("pavement_hot", ("pavement_hot", "sensor_degraded")),
}
_NAME_TO_BIT = {v[0]: k for k, v in QUALITY_FLAG_BITS.items()}


class MsgType(IntEnum):
    AXLE_EVENT = 0x01
    PASS_SUMMARY = 0x02
    HEALTH = 0x03
    LOOP_EVENT = 0x04
    IR_EVENT = 0x05
    ENV = 0x06
    TIME_SYNC = 0x07
    HEARTBEAT = 0x08


class FrameError(ValueError):
    pass


# ------------------------------------------------------------------------------------------------ payloads
@dataclass
class AxleEvent:
    pass_id: int
    axle_index: int
    rows_valid: int
    flags: int
    t_row_us: tuple[int, int, int, int]
    load_row_kg: tuple[int, int, int, int]
    speed_cmps: int
    spacing_prev_mm: int
    STRUCT = struct.Struct("<IBBBB4Q4HHH")  # 52 bytes

    def pack(self) -> bytes:
        return self.STRUCT.pack(self.pass_id, self.axle_index, self.rows_valid, self.flags, 0, *self.t_row_us, *self.load_row_kg, self.speed_cmps, self.spacing_prev_mm)

    @classmethod
    def unpack(cls, b: bytes) -> AxleEvent:
        v = cls.STRUCT.unpack(b[: cls.STRUCT.size])
        return cls(v[0], v[1], v[2], v[3], tuple(v[5:9]), tuple(v[9:13]), v[13], v[14])


@dataclass
class PassAxle:
    load_kg: int
    u_kg: int
    spacing_next_mm: int  # 0xFFFF = none
    group_no: int
    STRUCT = struct.Struct("<HHHBx")  # 8 bytes

    def pack(self) -> bytes:
        return self.STRUCT.pack(self.load_kg, self.u_kg, self.spacing_next_mm, self.group_no)

    @classmethod
    def unpack(cls, b: bytes) -> PassAxle:
        return cls(*cls.STRUCT.unpack(b[: cls.STRUCT.size]))


@dataclass
class PassSummary:
    pass_id: int
    t_first_axle_us: int
    axle_count: int
    n_groups: int
    quality_flags: int
    speed_cmps: int
    speed_u_cmps: int
    gvm_kg: int
    gvm_u_kg: int
    pavement_temp_c_x10: int
    sensor_health: tuple[int, ...]  # 8 entries
    axles: list[PassAxle] = field(default_factory=list)
    FIXED = struct.Struct("<IQBBHHHIIh8B")  # 38 bytes

    def pack(self, include_axles: bool = True) -> bytes:
        out = self.FIXED.pack(self.pass_id, self.t_first_axle_us, self.axle_count, self.n_groups, self.quality_flags, self.speed_cmps,
                              self.speed_u_cmps, self.gvm_kg, self.gvm_u_kg, self.pavement_temp_c_x10, *self.sensor_health)
        if include_axles:
            out += b"".join(a.pack() for a in self.axles[:12])
        return out

    @classmethod
    def unpack(cls, b: bytes) -> PassSummary:
        if len(b) < cls.FIXED.size:
            raise FrameError("PASS_SUMMARY too short")
        v = cls.FIXED.unpack(b[: cls.FIXED.size])
        axles = []
        rest = b[cls.FIXED.size:]
        for i in range(min(12, len(rest) // PassAxle.STRUCT.size)):
            axles.append(PassAxle.unpack(rest[i * 8: i * 8 + 8]))
        return cls(v[0], v[1], v[2], v[3], v[4], v[5], v[6], v[7], v[8], v[9], tuple(v[10:18]), axles)


@dataclass
class HealthChannel:
    noise_rms_kg_x10: int
    baseline_kg: int
    status: int
    flags: int
    STRUCT = struct.Struct("<HhBB")


@dataclass
class Health:
    t_us: int
    first_channel: int
    channels: list[HealthChannel]
    HDR = struct.Struct("<QBB")

    def pack(self) -> bytes:
        return self.HDR.pack(self.t_us, self.first_channel, len(self.channels)) + b"".join(
            HealthChannel.STRUCT.pack(c.noise_rms_kg_x10, c.baseline_kg, c.status, c.flags) for c in self.channels)

    @classmethod
    def unpack(cls, b: bytes) -> Health:
        t, first, n = cls.HDR.unpack(b[: cls.HDR.size])
        chans = [HealthChannel(*HealthChannel.STRUCT.unpack(b[cls.HDR.size + 6 * i: cls.HDR.size + 6 * i + 6])) for i in range(n)]
        return cls(t, first, chans)


@dataclass
class LoopEvent:  # also IR_EVENT
    t_us: int
    id: int
    state: int
    STRUCT = struct.Struct("<QBBH")

    def pack(self) -> bytes:
        return self.STRUCT.pack(self.t_us, self.id, self.state, 0)

    @classmethod
    def unpack(cls, b: bytes) -> LoopEvent:
        t, i, s, _ = cls.STRUCT.unpack(b[: cls.STRUCT.size])
        return cls(t, i, s)


@dataclass
class Env:
    t_us: int
    pavement_c_x100: int
    ambient_c_x100: int
    rh_x100: int
    cabinet_c_x100: int
    bus_mv: int
    batt_mv: int
    digital: int
    STRUCT = struct.Struct("<QhhHhHHBx")  # 22 bytes

    def pack(self) -> bytes:
        return self.STRUCT.pack(self.t_us, self.pavement_c_x100, self.ambient_c_x100, self.rh_x100, self.cabinet_c_x100, self.bus_mv, self.batt_mv, self.digital)

    @classmethod
    def unpack(cls, b: bytes) -> Env:
        return cls(*cls.STRUCT.unpack(b[: cls.STRUCT.size]))

    def to_dict(self) -> dict:
        return {
            "pavement_temp_c": self.pavement_c_x100 / 100, "ambient_temp_c": self.ambient_c_x100 / 100, "ambient_rh_pct": self.rh_x100 / 100,
            "cabinet_temp_c": self.cabinet_c_x100 / 100, "bus_v": self.bus_mv / 1000, "batt_v": self.batt_mv / 1000,
            "door_open": bool(self.digital & 1), "ac_fail": bool(self.digital & 2), "batt_low": bool(self.digital & 4),
            "spd_fault": bool(self.digital & 8), "fan_on": bool(self.digital & 16),
        }


@dataclass
class TimeSync:
    utc_us_at_pps: int
    pps_count: int
    STRUCT = struct.Struct("<QI")

    def pack(self) -> bytes:
        return self.STRUCT.pack(self.utc_us_at_pps, self.pps_count)

    @classmethod
    def unpack(cls, b: bytes) -> TimeSync:
        return cls(*cls.STRUCT.unpack(b[: cls.STRUCT.size]))


@dataclass
class Heartbeat:
    t_us: int
    uptime_s: int
    fw_version: int
    state: int
    STRUCT = struct.Struct("<QIIB")

    def pack(self) -> bytes:
        return self.STRUCT.pack(self.t_us, self.uptime_s, self.fw_version, self.state)

    @classmethod
    def unpack(cls, b: bytes) -> Heartbeat:
        return cls(*cls.STRUCT.unpack(b[: cls.STRUCT.size]))


_DECODERS = {
    MsgType.AXLE_EVENT: AxleEvent.unpack, MsgType.PASS_SUMMARY: PassSummary.unpack, MsgType.HEALTH: Health.unpack,
    MsgType.LOOP_EVENT: LoopEvent.unpack, MsgType.IR_EVENT: LoopEvent.unpack, MsgType.ENV: Env.unpack,
    MsgType.TIME_SYNC: TimeSync.unpack, MsgType.HEARTBEAT: Heartbeat.unpack,
}


def decode_payload(msg_type: int, payload: bytes):
    try:
        return _DECODERS[MsgType(msg_type)](payload)
    except (KeyError, ValueError, struct.error) as e:
        raise FrameError(f"cannot decode type {msg_type}: {e}") from e


# ------------------------------------------------------------------------------------------------ UDP framing
@dataclass
class Frame:
    msg_type: int
    seq: int
    t_tx_us_low: int
    payload: bytes

    def decoded(self):
        return decode_payload(self.msg_type, self.payload)


def encode_frame(msg_type: int, seq: int, payload: bytes, t_tx_us_low: int = 0) -> bytes:
    if len(payload) > 136:
        raise FrameError("payload too long")
    head = HDR.pack(MAGIC, VERSION, int(msg_type), seq & 0xFFFF, len(payload), t_tx_us_low & 0xFFFFFFFF) + payload
    return head + struct.pack("<I", zlib.crc32(head) & 0xFFFFFFFF)


def decode_frame(buf: bytes) -> Frame:
    if len(buf) < HDR.size + CRC_LEN:
        raise FrameError("frame too short")
    magic, version, msg_type, seq, plen, t_tx = HDR.unpack(buf[: HDR.size])
    if magic != MAGIC or version != VERSION:
        raise FrameError("bad magic/version")
    if len(buf) != HDR.size + plen + CRC_LEN:
        raise FrameError(f"length mismatch: {len(buf)} vs {HDR.size + plen + CRC_LEN}")
    body = buf[: HDR.size + plen]
    (crc,) = struct.unpack("<I", buf[HDR.size + plen:])
    if crc != (zlib.crc32(body) & 0xFFFFFFFF):
        raise FrameError("CRC mismatch")
    return Frame(msg_type, seq, t_tx, bytes(buf[HDR.size: HDR.size + plen]))


def can_id(msg_type: int, lane_no: int = 0, base: int = CAN_BASE_DAQ_TO_GW) -> int:
    return base + 0x20 * lane_no + int(msg_type)


def can_id_to_type(can_identifier: int) -> int:
    return can_identifier & 0x1F


# ------------------------------------------------------------------------------------------------ flags / health helpers
def flags_to_names(mask: int, engine_names: bool = True) -> list[str]:
    out: set[str] = set()
    for bit, (own, mapped) in QUALITY_FLAG_BITS.items():
        if mask & (1 << bit):
            out.add(own)
            if engine_names:
                out.update(mapped)
    return sorted(out)


def names_to_flags(names: list[str]) -> int:
    mask = 0
    for n in names:
        if n in _NAME_TO_BIT:
            mask |= 1 << _NAME_TO_BIT[n]
    return mask


def axle_config_from_groups(group_nos: list[int]) -> str:
    sizes: dict[int, int] = {}
    for g in group_nos:
        sizes[g] = sizes.get(g, 0) + 1
    return "+".join(str(sizes[g]) for g in sorted(sizes))


def us_to_datetime(t_us: int) -> datetime | None:
    """UTC µs -> aware datetime; returns None when the DAQ was not time-synced (counts from boot)."""
    if t_us < 1_000_000_000_000_000:  # before 2001-09 in µs => unsynced
        return None
    return datetime.fromtimestamp(t_us / 1e6, tz=UTC)


# ------------------------------------------------------------------------------------------------ measurement <-> frames
@dataclass
class DaqMeasurement:
    device_id: str
    pass_id: int
    occurred_at: datetime
    measurement: dict  # WimMeasurement.to_dict() shape
    pavement_temp_c: float
    truth: dict | None = None  # simulator only
    source: str = "live"


def summary_to_measurement(s: PassSummary, axle_events: dict[int, AxleEvent] | None = None) -> dict:
    axle_events = axle_events or {}
    axles = []
    n = s.axle_count
    for i in range(n):
        pa = s.axles[i] if i < len(s.axles) else None
        ev = axle_events.get(i)
        per_row = {}
        if ev is not None:
            for r, name in enumerate(ROW_NAMES):
                if ev.rows_valid & (1 << r):
                    per_row[name] = int(ev.load_row_kg[r])
        if pa is not None:
            load, u, spacing, group = pa.load_kg, pa.u_kg, pa.spacing_next_mm, pa.group_no
        elif ev is not None:
            vals = [(3.0 if k == "BP" else 1.0, v) for k, v in per_row.items()]
            load = round(sum(w * v for w, v in vals) / sum(w for w, _ in vals)) if vals else 0
            u, spacing, group = round(0.05 * load) * 2, 0xFFFF, 1
            nxt = axle_events.get(i + 1)
            if nxt is not None:
                spacing = nxt.spacing_prev_mm
        else:
            load, u, spacing, group = 0, 0, 0xFFFF, 1
        axles.append({
            "index": i, "load_kg": int(load), "u_kg": int(u),
            "spacing_to_next_m": None if spacing == 0xFFFF else round(spacing / 1000.0, 3),
            "group_no": int(group), "per_row_kg": per_row,
        })
    if not s.axles and axle_events:
        # CAN-FD path: groups were not transmitted per axle; regroup with the 2.0 m rule
        g = 1
        for a in axles:
            a["group_no"] = g
            if a["spacing_to_next_m"] is not None and a["spacing_to_next_m"] >= 2.0:
                g += 1
    health = {}
    for name, code in zip(SENSOR_HEALTH_NAMES, s.sensor_health, strict=True):
        if code == 255:
            continue
        status = HEALTH_STATUS.get(code, "fault")
        health[name] = {"status": status, "reasons": [] if status == "ok" else [f"{name}: reported {status} by DAQ"]}
    return {
        "pipeline_version": DAQ_PIPELINE_VERSION,
        "fs_hz": FS_HZ,
        "speed_mps": round(s.speed_cmps / 100.0, 3),
        "speed_u_mps": round(s.speed_u_cmps / 100.0, 3),
        "axles": axles,
        "gvm_kg": int(s.gvm_kg),
        "gvm_u_kg": int(s.gvm_u_kg),
        "axle_config": axle_config_from_groups([a["group_no"] for a in axles]) if axles else "",
        "class_code": CLASS_CODES.get(n, "HGV7+") if n else "UNKNOWN",
        "quality_flags": flags_to_names(s.quality_flags),
        "sensor_health": health,
        "pavement_temp_c": round(s.pavement_temp_c_x10 / 10.0, 1),
        "coverage_factor": 2.0,
    }


def measurement_to_frames(m: dict, pass_id: int, t_first_axle_us: int) -> list[tuple[int, bytes]]:
    """Inverse of summary_to_measurement: produces the (type, payload) list a DAQ would send for this measurement."""
    out: list[tuple[int, bytes]] = []
    speed_cmps = int(round(m.get("speed_mps", 0.0) * 100))
    axles = m.get("axles", [])
    prev_spacing_mm = 0
    for a in axles:
        rows_valid, loads, times = 0, [0, 0, 0, 0], [0, 0, 0, 0]
        for r, name in enumerate(ROW_NAMES):
            if name in a.get("per_row_kg", {}):
                rows_valid |= 1 << r
                loads[r] = max(0, min(65535, int(round(a["per_row_kg"][name]))))
                # peak time at row r = t_first + (row position offset + axle offset)/v ; positions as LaneGeometry defaults
                pos = {"P1": 4.0, "P2": 7.0, "P3": 16.0, "BP": 10.0}[name]
                v = max(m.get("speed_mps", 0.0), 0.1)
                off = sum((axles[j].get("spacing_to_next_m") or 0.0) for j in range(a["index"]))
                times[r] = int(t_first_axle_us + ((pos - 4.0) + off) / v * 1e6)
        ev = AxleEvent(pass_id, a["index"], rows_valid, 0, tuple(times), tuple(loads), speed_cmps, prev_spacing_mm)
        out.append((MsgType.AXLE_EVENT, ev.pack()))
        sp = a.get("spacing_to_next_m")
        prev_spacing_mm = 0 if sp is None else min(65535, int(round(sp * 1000)))
    health_codes = []
    for name in SENSOR_HEALTH_NAMES:
        h = m.get("sensor_health", {}).get(name)
        if h is None:
            health_codes.append(255)
        else:
            status = h["status"] if isinstance(h, dict) else h
            health_codes.append({"ok": 0, "degraded": 1, "fault": 2}[status])
    summary = PassSummary(
        pass_id=pass_id, t_first_axle_us=t_first_axle_us, axle_count=len(axles),
        n_groups=len({a["group_no"] for a in axles}) if axles else 0,
        quality_flags=names_to_flags(m.get("quality_flags", [])), speed_cmps=speed_cmps,
        speed_u_cmps=int(round(m.get("speed_u_mps", 0.0) * 100)), gvm_kg=int(round(m.get("gvm_kg", 0))),
        gvm_u_kg=int(round(m.get("gvm_u_kg", 0))), pavement_temp_c_x10=int(round(m.get("pavement_temp_c", 0.0) * 10)),
        sensor_health=tuple(health_codes),
        axles=[PassAxle(min(65535, int(round(a["load_kg"]))), min(65535, int(round(a["u_kg"]))),
                        0xFFFF if a.get("spacing_to_next_m") is None else min(65535, int(round(a["spacing_to_next_m"] * 1000))),
                        int(a["group_no"])) for a in axles],
    )
    out.append((MsgType.PASS_SUMMARY, summary.pack(include_axles=True)))
    return out


class PassAssembler:
    """Collects AXLE_EVENTs and the PASS_SUMMARY of a pass (either order) and yields one DaqMeasurement per pass."""

    def __init__(self, device_id: str, stale_s: float = 30.0):
        self.device_id = device_id
        self.stale_s = stale_s
        self._axles: dict[int, dict[int, AxleEvent]] = {}
        self._summaries: dict[int, PassSummary] = {}
        self._seen: dict[int, float] = {}
        self.completed: set[int] = set()

    def add(self, obj, now: float | None = None) -> DaqMeasurement | None:
        now = time.time() if now is None else now
        if isinstance(obj, AxleEvent):
            if obj.pass_id in self.completed:
                return None  # duplicate from the second transport
            self._axles.setdefault(obj.pass_id, {})[obj.axle_index] = obj
            self._seen[obj.pass_id] = now
        elif isinstance(obj, PassSummary):
            if obj.pass_id in self.completed:
                return None
            self._summaries[obj.pass_id] = obj
            self._seen[obj.pass_id] = now
        else:
            return None
        s = self._summaries.get(obj.pass_id)
        if s is None:
            return None
        axles = self._axles.get(obj.pass_id, {})
        have_all = s.axles or len(axles) >= s.axle_count
        if not have_all:
            return None
        m = summary_to_measurement(s, axles)
        occurred = us_to_datetime(s.t_first_axle_us) or datetime.now(UTC)
        self.completed.add(obj.pass_id)
        self._axles.pop(obj.pass_id, None)
        self._summaries.pop(obj.pass_id, None)
        self._seen.pop(obj.pass_id, None)
        self._expire(now)
        return DaqMeasurement(self.device_id, obj.pass_id, occurred, m, m["pavement_temp_c"], None, "live")

    def _expire(self, now: float) -> None:
        for pid in [p for p, t in self._seen.items() if now - t > self.stale_s]:
            self._axles.pop(pid, None)
            self._summaries.pop(pid, None)
            self._seen.pop(pid, None)
        if len(self.completed) > 10000:
            self.completed = set(sorted(self.completed)[-5000:])


# ------------------------------------------------------------------------------------------------ UDP client
class UdpDaqClient:
    """Receives frames from the DAQ on UDP (port 5010) and yields DaqMeasurements; other frames go to callbacks."""

    def __init__(self, bind: str, device_id: str, on_health=None, on_env=None, on_loop=None, on_heartbeat=None, daq_addr: str | None = None):
        host, port = bind.rsplit(":", 1)
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind((host, int(port)))
        self.sock.settimeout(1.0)
        self.assembler = PassAssembler(device_id)
        self.on_health, self.on_env, self.on_loop, self.on_heartbeat = on_health, on_env, on_loop, on_heartbeat
        self.daq_addr = None
        if daq_addr:
            h, p = daq_addr.rsplit(":", 1)
            self.daq_addr = (h, int(p))
        self.stats = {"frames": 0, "crc_errors": 0, "gaps": 0}
        self._last_seq: int | None = None
        self._tx_seq = 0
        self.last_sender: tuple[str, int] | None = None

    def send_time_sync(self, utc_us_at_pps: int, pps_count: int) -> None:
        addr = self.daq_addr or (self.last_sender[0], UDP_PORT_RX) if (self.daq_addr or self.last_sender) else None
        if addr is None:
            return
        self._tx_seq = (self._tx_seq + 1) & 0xFFFF
        self.sock.sendto(encode_frame(MsgType.TIME_SYNC, self._tx_seq, TimeSync(utc_us_at_pps, pps_count).pack()), addr)

    def poll(self) -> DaqMeasurement | None:
        try:
            buf, sender = self.sock.recvfrom(2048)
        except TimeoutError:
            return None
        self.last_sender = sender
        try:
            fr = decode_frame(buf)
        except FrameError:
            self.stats["crc_errors"] += 1
            return None
        self.stats["frames"] += 1
        if self._last_seq is not None and ((fr.seq - self._last_seq) & 0xFFFF) != 1:
            self.stats["gaps"] += 1
        self._last_seq = fr.seq
        try:
            obj = fr.decoded()
        except FrameError:
            return None
        if isinstance(obj, (AxleEvent, PassSummary)):
            return self.assembler.add(obj)
        if isinstance(obj, Health) and self.on_health:
            self.on_health(obj)
        elif isinstance(obj, Env) and self.on_env:
            self.on_env(obj)
        elif isinstance(obj, LoopEvent) and self.on_loop:
            self.on_loop(fr.msg_type, obj)
        elif isinstance(obj, Heartbeat) and self.on_heartbeat:
            self.on_heartbeat(obj)
        return None

    def __iter__(self) -> Iterator[DaqMeasurement]:
        while True:
            m = self.poll()
            if m is not None:
                yield m

    def close(self) -> None:
        self.sock.close()


# ------------------------------------------------------------------------------------------------ simulator
class SimulatedDaq:
    """Produces DaqMeasurements with kifaru_wim_dsp.generate_pass + process_pass (tagged source=simulated)."""

    def __init__(self, device_id: str, seed: int | None = None, overload_prob: float = 0.15, sensor_fault_prob: float = 0.03,
                 pavement_temp_c: float = 32.0, geometry: LaneGeometry | None = None, registry_plates: list[str] | None = None):
        self.device_id = device_id
        self.rng = np.random.default_rng(seed)
        self.overload_prob = overload_prob
        self.sensor_fault_prob = sensor_fault_prob
        self.pavement_temp_c = pavement_temp_c
        self.geometry = geometry or LaneGeometry()
        self.pass_id = 0
        self.cal = {k: ChannelCalibration(temp_coeff_per_c=-0.002, type_b_rel_u=0.02) for k in ("P1", "P2", "P3", "BP")}

    def next_pass(self, truck: TruckProfile | None = None) -> DaqMeasurement:
        truck = truck or random_truck(self.rng, overload_prob=self.overload_prob)
        sensors = {k: SensorModel(pavement_temp_c=self.pavement_temp_c, temp_coeff_per_c=-0.002) for k in ("P1", "P2", "P3", "BP")}
        if self.rng.random() < self.sensor_fault_prob:
            k = str(self.rng.choice(["P1", "P2", "P3", "BP"]))
            sensors[k] = SensorModel(pavement_temp_c=self.pavement_temp_c, fault=str(self.rng.choice(["dead", "noisy"])))
        p = generate_pass(truck, geometry=self.geometry, sensors=sensors, rng=self.rng)
        m = process_pass(p.channels, p.fs_hz, geometry=self.geometry, calibration=self.cal, pavement_temp_c=self.pavement_temp_c)
        self.pass_id += 1
        truth = {"axle_loads_kg": list(truck.axle_loads_kg), "axle_spacings_m": list(truck.axle_spacings_m), "speed_mps": truck.speed_mps, "gvm_kg": truck.gvm_kg}
        return DaqMeasurement(self.device_id, self.pass_id, datetime.now(UTC), m.to_dict(), self.pavement_temp_c, truth, "simulated")

    def frames_for(self, dm: DaqMeasurement) -> list[bytes]:
        """UDP frames a real DAQ would have sent for this measurement (useful for loopback tests)."""
        t_us = int(dm.occurred_at.timestamp() * 1e6)
        out = []
        for i, (t, payload) in enumerate(measurement_to_frames(dm.measurement, dm.pass_id, t_us)):
            out.append(encode_frame(t, (dm.pass_id * 32 + i) & 0xFFFF, payload, t_us & 0xFFFFFFFF))
        return out

    def __iter__(self) -> Iterator[DaqMeasurement]:
        while True:
            yield self.next_pass()
