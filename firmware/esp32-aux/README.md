# `esp32-aux` — Cabinet / Environment Auxiliary Node (ESP32, ESP-IDF)

**Status: written, NOT compiled** (no ESP-IDF on the authoring machine). Target ESP-IDF v5.2 or later (uses the
`i2c_master`, `adc_oneshot`, `adc_cali` drivers and esp-mqtt with MQTT 5).

## Role (WIM-06, hardware-architecture §2)

| Input | Interface | Output field (ENV payload, `communications.md` §1.5) |
|---|---|---|
| PT1000 pavement probe (beside P2) | MAX31865, SPI, 4-wire, R_REF 4.3 kΩ | `pavement_c_x100` |
| SHT4x outside (radiation shield) | I2C 0x44 | `ambient_c_x100`, `rh_x100` |
| SHT4x inside cabinet | I2C 0x45 | `cabinet_c_x100` |
| 24 V bus, battery | ADC1 via 100k/10k dividers | `bus_mv`, `batt_mv` |
| Door switch, PSU AC-fail, battery-low, SPD fault contacts | GPIO (pull-up, contacts to GND) | `digital` bits 0–3 |
| Circulation fan relay | GPIO 27 | `digital` bit 4 (on > 35 °C, off < 32 °C) |

Every 10 s the node sends the 22-byte ENV payload as three classic CAN frames (0x206/0x207/0x208, 500 kbit/s) on the
DAQ's FDCAN2 segment; the DAQ reassembles it, caches the pavement temperature for compensation, and forwards it to the
gateway. If the CAN link is bus-off or has had no successful transmission for 60 s, the node starts Wi-Fi (cabinet AP
on the LTE router) and publishes the same data as JSON on `kifaru/stations/{station}/lanes/{lane}/aux` (QoS 1, retained,
TLS, device certificate when embedded). When CAN recovers the fallback is stopped.

## Build (not performed here)

```powershell
# ESP-IDF v5.2+ installed and exported (install.ps1 / export.ps1)
cd firmware/esp32-aux
idf.py set-target esp32           # or esp32s3 (TWAI pins configurable in menuconfig)
idf.py menuconfig                 # "KIFARU aux node": station, lane, Wi-Fi, MQTT URI, CAN pins, period
idf.py build
idf.py -p COM5 flash monitor
```

For mTLS, add `EMBED_TXTFILES "certs/ca.pem" "certs/cert.pem" "certs/key.pem"` to `main/CMakeLists.txt`; the symbols
are declared weak in `mqtt_fallback.c` so the project links without them (then TLS runs without server verification —
development only).

## Files

```
CMakeLists.txt, sdkconfig.defaults, main/CMakeLists.txt, main/Kconfig.projbuild
main/main.c            sampling loop, fan hysteresis, CAN -> MQTT fallback switch, task watchdog
main/sht4x.[ch]        SHT40/45 high-precision measurement, CRC-8 (0x31)
main/max31865.[ch]     PT1000 ratio read, fault handling, inverse Callendar-Van Dusen
main/twai_link.[ch]    3-frame ENV transmission, bus health, recovery
main/mqtt_fallback.[ch] Wi-Fi STA + esp-mqtt (MQTT 5, TLS/mTLS), retained last will
main/env_frame.[ch]    ENV byte layout (shared with the STM32 frames.c) and JSON rendering
```

## Verification plan

1. `idf.py monitor`: log shows plausible pavement/ambient/cabinet temperatures (ice-water test on the PT1000 → 0.0 ±
   0.3 °C; compare SHT4x pair within 0.3 °C side by side).
2. CAN analyser on the aux segment: frames 0x206–0x208 every 10 s, DLC 8/8/6; the DAQ's forwarded ENV appears on the
   gateway with the same values.
3. Disconnect the CAN transceiver: after 60 s the node joins Wi-Fi and the retained message appears on the broker;
   reconnect: fallback stops within one period.
4. Door contact, AC-fail contact simulation: bits toggle in the payload.
