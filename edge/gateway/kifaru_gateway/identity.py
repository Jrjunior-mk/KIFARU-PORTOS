"""Vehicle identity adapters: ANPR (camera + OCR) and UHF RFID (LLRP reader).

Mocks are deterministic given a seed and are used by the simulator and the tests. The real adapters document the
exact external dependencies they need (not installed in this environment) and raise clearly if missing.
"""
from __future__ import annotations

import re
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime

import numpy as np

KENYA_PLATE_RE = re.compile(r"^K[A-Z]{2} ?\d{3}[A-Z]$")


@dataclass
class AnprRead:
    plate: str
    confidence: float
    camera: str = "front"
    image_ref: str | None = None  # S3 key / local path of the evidence frame


@dataclass
class RfidRead:
    epc: str
    rssi_dbm: float
    seen_count: int
    antenna: int = 1
    confidence: float = 0.0


def rfid_confidence(seen_count: int, rssi_dbm: float) -> float:
    """Deterministic confidence model (communications.md §5): read count and RSSI consistency."""
    c = 0.6 + 0.08 * min(seen_count, 4) + 0.02 * float(np.clip((rssi_dbm + 70) / 5, 0, 4))
    return round(min(0.999, c), 3)


def normalise_plate(plate: str | None) -> str | None:
    if not plate:
        return None
    return "".join(ch for ch in plate.upper() if ch.isalnum())


# ------------------------------------------------------------------------------------------------ ANPR
class AnprAdapter(ABC):
    def start(self) -> None: ...

    def stop(self) -> None: ...

    @abstractmethod
    def read_window(self, t_start: datetime, t_end: datetime) -> AnprRead | None:
        """Best plate read in the capture window (loop L1 occupied ± 0.8 s for the front camera)."""


class MockAnpr(AnprAdapter):
    """Returns the plate queued with `expect()` (or a random Kenyan plate), with a configurable misread probability."""

    _LETTERS = "ABCDEFGHJKLMNPQRSTUVWXYZ"

    def __init__(self, seed: int | None = None, misread_prob: float = 0.05, miss_prob: float = 0.02):
        self.rng = np.random.default_rng(seed)
        self.misread_prob = misread_prob
        self.miss_prob = miss_prob
        self._next: str | None = None

    def expect(self, plate: str | None) -> None:
        self._next = plate

    def random_plate(self) -> str:
        return f"K{self.rng.choice(list('CDE'))}{self.rng.choice(list(self._LETTERS))} {self.rng.integers(100, 999)}{self.rng.choice(list(self._LETTERS))}"

    def scramble(self, plate: str) -> str:
        chars = list(plate)
        idx = [i for i, c in enumerate(chars) if c.isalnum()]
        i = int(self.rng.choice(idx))
        chars[i] = "8" if chars[i] == "B" else ("B" if chars[i] == "8" else ("0" if chars[i] == "O" else "O"))
        return "".join(chars)

    def read_window(self, t_start: datetime, t_end: datetime) -> AnprRead | None:
        plate = self._next or self.random_plate()
        self._next = None
        if self.rng.random() < self.miss_prob:
            return None
        if self.rng.random() < self.misread_prob:
            return AnprRead(self.scramble(plate), float(self.rng.uniform(0.5, 0.8)), "front")
        return AnprRead(plate, float(self.rng.uniform(0.85, 0.99)), "front")


class PaddleOcrAnpr(AnprAdapter):
    """RTSP (ONVIF-configured) camera -> YOLOv8 plate detector -> PaddleOCR text.

    Requires on the IPC: opencv-python-headless, ultralytics (YOLOv8 weights for licence plates), paddleocr.
    Pipeline per window: grab frames at 25 fps from `rtsp_url`, detect plate boxes, OCR each crop, keep reads that
    match KENYA_PLATE_RE (or the EAC foreign-plate patterns), vote across frames; confidence = OCR score × vote share.
    """

    def __init__(self, rtsp_url: str, camera: str = "front", min_conf: float = 0.5):
        self.rtsp_url, self.camera, self.min_conf = rtsp_url, camera, min_conf
        self._cap = None
        self._detector = None
        self._ocr = None

    def start(self) -> None:
        try:
            import cv2  # noqa: F401
            from paddleocr import PaddleOCR  # noqa: F401
            from ultralytics import YOLO  # noqa: F401
        except ImportError as e:
            raise RuntimeError("PaddleOcrAnpr needs opencv-python-headless, paddleocr and ultralytics (pip install 'kifaru-gateway[field]')") from e
        import cv2
        from paddleocr import PaddleOCR
        from ultralytics import YOLO

        self._cap = cv2.VideoCapture(self.rtsp_url)
        self._detector = YOLO("models/plate_yolov8n.pt")
        self._ocr = PaddleOCR(use_angle_cls=False, lang="en", show_log=False)

    def read_window(self, t_start: datetime, t_end: datetime) -> AnprRead | None:
        if self._cap is None:
            raise RuntimeError("call start() first")
        votes: dict[str, list[float]] = {}
        n_frames = max(1, int((t_end - t_start).total_seconds() * 25))
        for _ in range(n_frames):
            ok, frame = self._cap.read()
            if not ok:
                break
            for box in self._detector(frame, verbose=False)[0].boxes.xyxy.cpu().numpy().astype(int):
                x1, y1, x2, y2 = box
                for line in (self._ocr.ocr(frame[y1:y2, x1:x2], cls=False) or [[]])[0]:
                    text, score = line[1][0], float(line[1][1])
                    norm = normalise_plate(text)
                    if norm and KENYA_PLATE_RE.match(f"{norm[:3]} {norm[3:]}") and score >= self.min_conf:
                        votes.setdefault(norm, []).append(score)
        if not votes:
            return None
        best = max(votes, key=lambda k: len(votes[k]) * np.mean(votes[k]))
        share = len(votes[best]) / sum(len(v) for v in votes.values())
        return AnprRead(f"{best[:3]} {best[3:]}", round(float(np.mean(votes[best])) * share, 3), self.camera)


# ------------------------------------------------------------------------------------------------ RFID
class RfidAdapter(ABC):
    def start(self) -> None: ...

    def stop(self) -> None: ...

    @abstractmethod
    def read_window(self, t_start: datetime, t_end: datetime) -> RfidRead | None:
        """Dominant tag (by RSSI × seen count) in the window; None if no tag."""


class MockRfid(RfidAdapter):
    def __init__(self, seed: int | None = None, missing_prob: float = 0.10):
        self.rng = np.random.default_rng(seed)
        self.missing_prob = missing_prob
        self._next: str | None = None

    def expect(self, epc: str | None) -> None:
        self._next = epc

    def read_window(self, t_start: datetime, t_end: datetime) -> RfidRead | None:
        epc = self._next
        self._next = None
        if epc is None or self.rng.random() < self.missing_prob:
            return None
        seen = int(self.rng.integers(2, 12))
        rssi = float(self.rng.uniform(-62, -45))
        return RfidRead(epc, rssi, seen, 1, rfid_confidence(seen, rssi))


class LlrpRfid(RfidAdapter):
    """Impinj/Zebra class fixed reader via LLRP (TCP 5084) using `sllurp` (pip install sllurp).

    ROSpec: start Immediate, antennas 1–2, session S2, report every tag with EPC/antenna/peak RSSI/seen count/timestamps.
    """

    def __init__(self, host: str, port: int = 5084, antennas: tuple[int, ...] = (1, 2), tx_power: int = 0):
        self.host, self.port, self.antennas, self.tx_power = host, port, antennas, tx_power
        self._reader = None
        self._tags: list[tuple[datetime, dict]] = []

    def start(self) -> None:
        try:
            from sllurp.llrp import LLRPReaderClient, LLRPReaderConfig  # type: ignore
        except ImportError as e:
            raise RuntimeError("LlrpRfid needs sllurp (pip install sllurp)") from e
        cfg = LLRPReaderConfig({"antennas": list(self.antennas), "tx_power": self.tx_power, "report_every_n_tags": 1, "session": 2,
                                "tag_content_selector": {"EnableAntennaID": True, "EnablePeakRSSI": True, "EnableFirstSeenTimestamp": True,
                                                         "EnableLastSeenTimestamp": True, "EnableTagSeenCount": True}})
        self._reader = LLRPReaderClient(self.host, self.port, cfg)
        self._reader.add_tag_report_callback(self._on_tags)
        self._reader.connect()

    def _on_tags(self, reader, tags) -> None:
        now = datetime.now()
        for t in tags:
            self._tags.append((now, t))
        self._tags = self._tags[-5000:]

    def read_window(self, t_start: datetime, t_end: datetime) -> RfidRead | None:
        window = [t for ts, t in self._tags if t_start <= ts <= t_end]
        if not window:
            return None
        agg: dict[str, dict] = {}
        for t in window:
            epc = t.get("EPC-96") or t.get("EPCData", {}).get("EPC")
            if epc is None:
                continue
            epc = epc.decode() if isinstance(epc, bytes) else str(epc)
            a = agg.setdefault(epc, {"seen": 0, "rssi": -100.0, "ant": t.get("AntennaID", 1)})
            a["seen"] += int(t.get("TagSeenCount", 1))
            a["rssi"] = max(a["rssi"], float(t.get("PeakRSSI", -100)))
        if not agg:
            return None
        best = max(agg, key=lambda k: agg[k]["seen"] * (agg[k]["rssi"] + 100))
        a = agg[best]
        return RfidRead(best, a["rssi"], a["seen"], a["ant"], rfid_confidence(a["seen"], a["rssi"]))
