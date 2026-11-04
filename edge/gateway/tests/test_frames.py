"""Frame codec round trips (byte-exact with firmware/stm32-wim-daq/App/frames.c) and measurement <-> frames."""
import struct
import zlib

import numpy as np
import pytest
from kifaru_gateway import daq_client as dc

from kifaru_wim_dsp import TruckProfile, generate_pass, process_pass


def test_crc32_matches_firmware_check_value():
    assert zlib.crc32(b"123456789") == 0xCBF43926


def test_udp_frame_round_trip_and_crc_rejection():
    payload = dc.Env(99, -150, 3120, 7800, 4210, 24100, 26400, 0x05).pack()
    assert len(payload) == 22
    frame = dc.encode_frame(dc.MsgType.ENV, 77, payload, 123456)
    assert len(frame) == 12 + 22 + 4
    assert struct.unpack_from("<H", frame, 0)[0] == 0x4B57
    fr = dc.decode_frame(frame)
    assert fr.msg_type == dc.MsgType.ENV and fr.seq == 77 and fr.t_tx_us_low == 123456
    env = fr.decoded()
    assert env.pavement_c_x100 == -150 and env.to_dict()["door_open"] and env.to_dict()["batt_low"] and not env.to_dict()["ac_fail"]
    bad = bytearray(frame)
    bad[15] ^= 1
    with pytest.raises(dc.FrameError):
        dc.decode_frame(bytes(bad))
    with pytest.raises(dc.FrameError):
        dc.decode_frame(frame[:-1])


def test_payload_sizes_match_spec():
    assert dc.AxleEvent.STRUCT.size == 52
    assert dc.PassSummary.FIXED.size == 38
    assert dc.PassAxle.STRUCT.size == 8
    assert dc.HealthChannel.STRUCT.size == 6 and dc.Health.HDR.size == 10
    assert dc.LoopEvent.STRUCT.size == 12
    assert dc.Env.STRUCT.size == 22
    assert dc.TimeSync.STRUCT.size == 12
    assert dc.Heartbeat.STRUCT.size == 17


def test_axle_event_and_summary_round_trip():
    a = dc.AxleEvent(1234, 2, 0x0F, 1, (1 << 40, 2, 3, 4), (6500, 6400, 6600, 6450), 2000, 1350)
    b = dc.AxleEvent.unpack(a.pack())
    assert b == a
    s = dc.PassSummary(7, 1_700_000_000_000_000, 2, 2, 0x42, 1850, 12, 15500, 700, 345, (0, 0, 0, 1, 0, 0, 0, 255),
                       [dc.PassAxle(6500, 400, 4200, 1), dc.PassAxle(9000, 500, 0xFFFF, 2)])
    full = s.pack(include_axles=True)
    assert len(full) == 38 + 16
    assert dc.PassSummary.unpack(full) == s
    fixed = s.pack(include_axles=False)
    assert len(fixed) == 38 and dc.PassSummary.unpack(fixed).axles == []
    h = dc.Health(5, 0, [dc.HealthChannel(123, -4, 1, 0x10), dc.HealthChannel(7, 2, 0, 0)])
    assert dc.Health.unpack(h.pack()) == h
    assert dc.flags_to_names(0x42) == ["high_uncertainty", "sensor_degraded"]
    assert dc.flags_to_names(1 << 8) == ["saturation", "sensor_fault"]
    assert dc.names_to_flags(["sensor_fault", "speed_out_of_range"]) == 0b1001


def test_can_identifiers():
    assert dc.can_id(dc.MsgType.AXLE_EVENT, lane_no=0) == 0x101
    assert dc.can_id(dc.MsgType.HEALTH, lane_no=2) == 0x143
    assert dc.can_id_to_type(0x143) == dc.MsgType.HEALTH


def test_measurement_to_frames_and_back_preserves_api_fields():
    rng = np.random.default_rng(7)
    truck = TruckProfile([6500, 9000, 8500, 8500], [3.6, 5.8, 1.35], speed_mps=20.0, bounce_frac=0.02)
    p = generate_pass(truck, rng=rng)
    m = process_pass(p.channels, p.fs_hz, pavement_temp_c=p.pavement_temp_c).to_dict()

    t_us = 1_762_245_342_123_456
    frames = dc.measurement_to_frames(m, pass_id=42, t_first_axle_us=t_us)
    assert [t for t, _ in frames] == [dc.MsgType.AXLE_EVENT] * 4 + [dc.MsgType.PASS_SUMMARY]

    # UDP path: wrap, unwrap, assemble (axle events first, then the summary with axle records)
    asm = dc.PassAssembler("daq-test")
    out = None
    for i, (t, payload) in enumerate(frames):
        fr = dc.decode_frame(dc.encode_frame(t, i, payload))
        out = asm.add(fr.decoded(), now=0.0) or out
    assert out is not None and out.pass_id == 42
    r = out.measurement
    assert r["gvm_kg"] == m["gvm_kg"] and r["gvm_u_kg"] == m["gvm_u_kg"]
    assert r["axle_config"] == m["axle_config"] == "1+1+2" and r["class_code"] == m["class_code"]
    assert abs(r["speed_mps"] - m["speed_mps"]) < 0.01
    assert [a["load_kg"] for a in r["axles"]] == [a["load_kg"] for a in m["axles"]]
    assert [a["group_no"] for a in r["axles"]] == [a["group_no"] for a in m["axles"]]
    assert [a["spacing_to_next_m"] for a in r["axles"]][-1] is None
    assert all(abs(a["spacing_to_next_m"] - b["spacing_to_next_m"]) < 0.001 for a, b in zip(r["axles"][:-1], m["axles"][:-1], strict=True))
    assert r["quality_flags"] == m["quality_flags"] == []
    assert {k: v["status"] for k, v in r["sensor_health"].items() if k in ("P1", "P2", "P3", "BP")} == {k: v["status"] for k, v in m["sensor_health"].items()}
    assert r["per_row_kg" if False else "axles"][1]["per_row_kg"] == {k: int(round(v)) for k, v in m["axles"][1]["per_row_kg"].items()}
    assert out.occurred_at.year == 2025 and out.occurred_at.tzinfo is not None
    assert asm.add(dc.decode_frame(dc.encode_frame(*frames[-1][:1], 9, frames[-1][1])).decoded(), now=0.0) is None  # duplicate summary ignored

    # CAN-FD path: summary without axle records, axles only from AXLE_EVENTs (arriving before the summary)
    asm2 = dc.PassAssembler("daq-test")
    summary = dc.PassSummary.unpack(frames[-1][1])
    for _t, payload in frames[:-1]:
        assert asm2.add(dc.AxleEvent.unpack(payload), now=0.0) is None
    out2 = asm2.add(dc.PassSummary.unpack(summary.pack(include_axles=False)), now=0.0)
    assert out2 is not None
    assert out2.measurement["axle_config"] == "1+1+2" and out2.measurement["gvm_kg"] == m["gvm_kg"]
    assert all(a["per_row_kg"] for a in out2.measurement["axles"])
