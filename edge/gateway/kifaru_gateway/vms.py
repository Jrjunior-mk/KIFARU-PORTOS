"""Lane signal / VMS driver over RS-485 Modbus RTU (register map: docs/03-hardware/communications.md §6).

The Modbus RTU codec (functions 03/06/16 + CRC-16) is implemented here so the mock backend and a pyserial backend share
it without depending on pymodbus. `MockModbusBackend` behaves like the VMS slave (register file, exceptions, CRC check).
"""
from __future__ import annotations

import struct
import time
from dataclasses import dataclass, field
from typing import Protocol

REG_SIGNAL_STATE = 0
REG_VMS_MESSAGE_ID = 1
REG_PLATE_ENABLE = 2
REG_HOLD_TIME_S = 3
REG_BRIGHTNESS = 4
REG_HEARTBEAT = 5
REG_CUSTOM_TEXT = 9  # 32 registers
SIGNAL = {"off": 0, "GREEN": 1, "AMBER": 2, "RED": 3, "FLASH_AMBER": 4}
MESSAGE_ID = {"blank": 0, "PROCEED": 1, "WEIGHBRIDGE ->": 2, "STOP INSPECTION": 3, "SLOW": 4, "custom": 5}
DECISION_MAP = {"GREEN": ("GREEN", "PROCEED"), "AMBER": ("AMBER", "WEIGHBRIDGE ->"), "RED": ("RED", "STOP INSPECTION")}


def crc16_modbus(data: bytes) -> int:
    crc = 0xFFFF
    for b in data:
        crc ^= b
        for _ in range(8):
            crc = (crc >> 1) ^ 0xA001 if crc & 1 else crc >> 1
    return crc


def _with_crc(pdu: bytes) -> bytes:
    return pdu + struct.pack("<H", crc16_modbus(pdu))


def check_crc(frame: bytes) -> bool:
    return len(frame) >= 4 and struct.unpack("<H", frame[-2:])[0] == crc16_modbus(frame[:-2])


def req_read_holding(addr: int, start: int, count: int) -> bytes:
    return _with_crc(struct.pack(">BBHH", addr, 0x03, start, count))


def req_write_single(addr: int, reg: int, value: int) -> bytes:
    return _with_crc(struct.pack(">BBHH", addr, 0x06, reg, value & 0xFFFF))


def req_write_multiple(addr: int, start: int, values: list[int]) -> bytes:
    body = struct.pack(">BBHHB", addr, 0x10, start, len(values), 2 * len(values)) + b"".join(struct.pack(">H", v & 0xFFFF) for v in values)
    return _with_crc(body)


class ModbusError(Exception):
    pass


def parse_response(frame: bytes) -> dict:
    if not check_crc(frame):
        raise ModbusError("CRC error")
    addr, fn = frame[0], frame[1]
    if fn & 0x80:
        raise ModbusError(f"exception code {frame[2]} for function {fn & 0x7F}")
    if fn == 0x03:
        n = frame[2]
        return {"addr": addr, "fn": fn, "values": list(struct.unpack(f">{n // 2}H", frame[3: 3 + n]))}
    if fn == 0x06:
        reg, val = struct.unpack(">HH", frame[2:6])
        return {"addr": addr, "fn": fn, "reg": reg, "value": val}
    if fn == 0x10:
        start, cnt = struct.unpack(">HH", frame[2:6])
        return {"addr": addr, "fn": fn, "start": start, "count": cnt}
    raise ModbusError(f"unsupported function {fn}")


class ModbusBackend(Protocol):
    def transact(self, request: bytes) -> bytes: ...


@dataclass
class MockModbusBackend:
    """In-memory VMS slave: holding registers 0..40, input registers (status) 0..3."""

    addresses: tuple[int, ...] = (1, 2)
    holding: dict[int, dict[int, int]] = field(default_factory=dict)
    fail_next: int = 0
    log: list[bytes] = field(default_factory=list)

    def __post_init__(self):
        for a in self.addresses:
            self.holding.setdefault(a, {i: 0 for i in range(41)})
            self.holding[a][REG_HOLD_TIME_S] = 8
            self.holding[a][REG_BRIGHTNESS] = 255

    def transact(self, request: bytes) -> bytes:
        self.log.append(request)
        if self.fail_next > 0:
            self.fail_next -= 1
            raise TimeoutError("no response from VMS")
        if not check_crc(request):
            raise TimeoutError("slave ignored frame with bad CRC")
        addr, fn = request[0], request[1]
        if addr not in self.holding:
            raise TimeoutError("no such slave")
        regs = self.holding[addr]
        if fn == 0x03:
            start, count = struct.unpack(">HH", request[2:6])
            if start + count > 41:
                return _with_crc(bytes([addr, fn | 0x80, 0x02]))
            vals = b"".join(struct.pack(">H", regs[i]) for i in range(start, start + count))
            return _with_crc(bytes([addr, fn, len(vals)]) + vals)
        if fn == 0x06:
            reg, val = struct.unpack(">HH", request[2:6])
            if reg > 40:
                return _with_crc(bytes([addr, fn | 0x80, 0x02]))
            regs[reg] = val
            return _with_crc(request[:6])
        if fn == 0x10:
            start, count, nbytes = struct.unpack(">HHB", request[2:7])
            if start + count > 41:
                return _with_crc(bytes([addr, fn | 0x80, 0x02]))
            for i in range(count):
                regs[start + i] = struct.unpack(">H", request[7 + 2 * i: 9 + 2 * i])[0]
            return _with_crc(request[:6])
        return _with_crc(bytes([addr, fn | 0x80, 0x01]))


class SerialModbusBackend:
    """RS-485 via pyserial (not installed here). 115200 8N1, 3.5-char inter-frame gap handled by read timeout."""

    def __init__(self, port: str, baud: int = 115200, timeout_s: float = 0.2):
        try:
            import serial  # type: ignore
        except ImportError as e:
            raise RuntimeError("SerialModbusBackend needs pyserial (pip install pyserial)") from e
        self.ser = serial.Serial(port, baud, bytesize=8, parity="N", stopbits=1, timeout=timeout_s)

    def transact(self, request: bytes) -> bytes:
        self.ser.reset_input_buffer()
        self.ser.write(request)
        time.sleep(0.004)
        resp = self.ser.read(256)
        if not resp:
            raise TimeoutError("no response from VMS")
        return resp


class VmsController:
    def __init__(self, backend: ModbusBackend, vms_addr: int = 1, signal_addr: int = 2):
        self.backend, self.vms_addr, self.signal_addr = backend, vms_addr, signal_addr
        self.state: dict = {"signal": "off", "message": "blank", "plate": None, "fault": False, "heartbeat": 0}

    def _write(self, addr: int, reg: int, value: int) -> None:
        resp = parse_response(self.backend.transact(req_write_single(addr, reg, value)))
        if resp.get("value") != (value & 0xFFFF):
            raise ModbusError("write not echoed")

    def _write_text(self, addr: int, text: str) -> None:
        padded = text[:64].ljust(64).encode("ascii", "replace")
        values = [(padded[i] << 8) | padded[i + 1] for i in range(0, 64, 2)]
        parse_response(self.backend.transact(req_write_multiple(addr, REG_CUSTOM_TEXT, values)))

    def show(self, decision: str, plate: str | None = None, hold_s: int = 8) -> dict:
        signal, message = DECISION_MAP.get(decision, ("FLASH_AMBER", "blank"))
        try:
            self._write(self.signal_addr, REG_SIGNAL_STATE, SIGNAL[signal])
            self._write(self.vms_addr, REG_SIGNAL_STATE, SIGNAL[signal])
            self._write(self.vms_addr, REG_HOLD_TIME_S, hold_s)
            self._write(self.vms_addr, REG_VMS_MESSAGE_ID, MESSAGE_ID[message])
            if plate:
                self._write(self.vms_addr, REG_PLATE_ENABLE, 1)
                self._write_text(self.vms_addr, f"{plate} {message}")
            else:
                self._write(self.vms_addr, REG_PLATE_ENABLE, 0)
            self.state.update(signal=signal, message=message, plate=plate, fault=False)
        except (TimeoutError, ModbusError) as e:
            self.state.update(fault=True, error=str(e))
        return dict(self.state)

    def heartbeat(self) -> bool:
        self.state["heartbeat"] = (self.state["heartbeat"] + 1) & 0xFFFF
        try:
            self._write(self.vms_addr, REG_HEARTBEAT, self.state["heartbeat"])
            self.state["fault"] = False
            return True
        except (TimeoutError, ModbusError) as e:
            self.state.update(fault=True, error=str(e))
            return False

    def blank(self) -> None:
        self.show("off")

    def read_status(self) -> dict:
        resp = parse_response(self.backend.transact(req_read_holding(self.vms_addr, 0, 6)))
        v = resp["values"]
        return {"signal_state": v[0], "message_id": v[1], "plate_enable": v[2], "hold_time_s": v[3], "brightness": v[4], "heartbeat": v[5]}
