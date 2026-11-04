"""KIFARU PORTOS edge gateway (roadside IPC).

Pipeline per vehicle pass:
  DAQ frames (CAN-FD/UDP or simulator) -> measurement dict  (daq_client)
  -> identity (ANPR + RFID adapters)                        (identity)
  -> local clearance decision with the API's engine         (clearance_mirror)
  -> lane signal / VMS                                      (vms)
  -> events into the SQLite WAL outbox                      (outbox)
  -> MQTT (mTLS) with HTTP ingest fallback, ordered replay   (uplink)
"""
__version__ = "0.1.0"
GATEWAY_VERSION = f"kifaru-gateway-{__version__}"
