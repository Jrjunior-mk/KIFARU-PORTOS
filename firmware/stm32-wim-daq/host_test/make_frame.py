"""Helper for bench/Proteus work: build an ADS131M08 response frame (STATUS + 8 x 24-bit + CRC-16/CCITT) from channel
values in volts, and print the UDP CRC-32 of a payload, so the firmware's parsers can be checked against an
independent implementation.

  python make_frame.py adc 0.5 -0.25 0 0 0 0 0 0      -> 30 hex bytes for an ADS131M08 frame
  python make_frame.py crc32 4b57010100...            -> CRC-32 of the hex bytes (zlib.crc32)
"""
from __future__ import annotations

import sys
import zlib


def crc16_ccitt(data: bytes, init: int = 0xFFFF) -> int:
    crc = init
    for b in data:
        crc ^= b << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) & 0xFFFF if crc & 0x8000 else (crc << 1) & 0xFFFF
    return crc


def adc_frame(volts: list[float], status: int = 0x0500) -> bytes:
    words = [status.to_bytes(2, "big") + b"\x00"]
    for v in volts:
        raw = int(round(v / 1.2 * (1 << 23)))
        raw = max(-(1 << 23), min((1 << 23) - 1, raw))
        words.append((raw & 0xFFFFFF).to_bytes(3, "big"))
    body = b"".join(words)
    return body + crc16_ccitt(body).to_bytes(2, "big") + b"\x00"


if __name__ == "__main__":
    if len(sys.argv) >= 2 and sys.argv[1] == "adc":
        vals = [float(x) for x in sys.argv[2:]]
        vals += [0.0] * (8 - len(vals))
        print(adc_frame(vals[:8]).hex())
    elif len(sys.argv) == 3 and sys.argv[1] == "crc32":
        print(f"0x{zlib.crc32(bytes.fromhex(sys.argv[2])):08X}")
    else:
        print(__doc__)
