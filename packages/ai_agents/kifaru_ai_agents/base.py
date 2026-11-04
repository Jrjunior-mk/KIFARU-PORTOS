"""Agent protocol shared by all KIFARU PORTOS agents (Module 9).

Every agent:
  * declares `name`, `responsibilities`, `inputs` and `outputs` (documentation surfaced by the orchestrator API),
  * implements `run(inputs) -> AgentResult` with a confidence in [0,1], an explanation and warnings,
  * never raises on bad input: it returns `ok=False` with the error so the orchestrator can degrade gracefully,
  * logs every run (structured) and is unit-tested.

Agent outputs are ADVISORY. The deterministic clearance engine and the legal/safety rules are never overridden by them.
"""
from __future__ import annotations

import logging
import time
import traceback
from dataclasses import dataclass, field
from typing import Any, ClassVar

log = logging.getLogger("kifaru.agents")


@dataclass
class AgentResult:
    agent: str
    ok: bool
    output: dict[str, Any]
    confidence: float
    explanation: str
    warnings: list[str] = field(default_factory=list)
    error: str | None = None
    duration_ms: int = 0
    version: str = "0.1"

    def to_dict(self) -> dict:
        return self.__dict__.copy()


class Agent:
    name: ClassVar[str] = "base"
    version: ClassVar[str] = "0.1"
    responsibilities: ClassVar[str] = ""
    inputs: ClassVar[dict[str, str]] = {}
    outputs: ClassVar[dict[str, str]] = {}

    def validate(self, inputs: dict[str, Any]) -> list[str]:
        missing = [k for k in self.inputs if k not in inputs and not self.inputs[k].startswith("optional")]
        return [f"missing input '{k}'" for k in missing]

    def _run(self, inputs: dict[str, Any]) -> tuple[dict[str, Any], float, str, list[str]]:  # pragma: no cover - abstract
        raise NotImplementedError

    def run(self, inputs: dict[str, Any]) -> AgentResult:
        t0 = time.perf_counter()
        errors = self.validate(inputs)
        if errors:
            return AgentResult(self.name, False, {}, 0.0, "input validation failed", errors, "; ".join(errors), 0, self.version)
        try:
            output, confidence, explanation, warnings = self._run(inputs)
            res = AgentResult(self.name, True, output, max(0.0, min(1.0, confidence)), explanation, warnings, None,
                              int((time.perf_counter() - t0) * 1000), self.version)
        except Exception as exc:  # noqa: BLE001 - agents must never crash the pipeline
            log.exception("agent_failed", extra={"agent": self.name})
            res = AgentResult(self.name, False, {}, 0.0, "agent raised an exception", [], f"{type(exc).__name__}: {exc}\n{traceback.format_exc()[-500:]}",
                              int((time.perf_counter() - t0) * 1000), self.version)
        log.info("agent_run", extra={"agent": self.name, "ok": res.ok, "confidence": res.confidence, "duration_ms": res.duration_ms})
        return res

    @classmethod
    def describe(cls) -> dict:
        return {"name": cls.name, "version": cls.version, "responsibilities": cls.responsibilities, "inputs": cls.inputs, "outputs": cls.outputs}


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    import math

    r = 6371.0088
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = math.radians(lat2 - lat1), math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


ROAD_FACTOR = 1.25  # typical ratio of road distance to great-circle distance on the Northern Corridor
