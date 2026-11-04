"""Central AI orchestration service (Module 9).

The orchestrator owns the agent registry, exposes a catalogue (responsibilities, inputs, outputs, versions) and runs
named pipelines. Pipelines pass outputs forward as inputs and collect every AgentResult for logging/explainability.

Invariant: the orchestrator never calls the clearance engine and never writes decisions. Its results are consumed as
advisory inputs by deterministic services.
"""
from __future__ import annotations

from typing import Any

from .agents_misc import (
    CargoVerificationAgent,
    OperationalIncidentAgent,
    QueueOptimizationAgent,
    SecurityAnomalyAgent,
    VehicleIdentityAgent,
    WeighingIntelligenceAgent,
)
from .backhaul_matcher import BackhaulMatchingAgent
from .base import Agent, AgentResult
from .environmental import EnvironmentalAgent
from .release_predictor import ReleasePredictionAgent
from .traffic_forecast import TrafficForecastAgent


class Orchestrator:
    def __init__(self) -> None:
        self.agents: dict[str, Agent] = {
            a.name: a
            for a in (
                WeighingIntelligenceAgent(),
                VehicleIdentityAgent(),
                TrafficForecastAgent(),
                QueueOptimizationAgent(),
                CargoVerificationAgent(),
                BackhaulMatchingAgent(),
                ReleasePredictionAgent(),
                EnvironmentalAgent(),
                SecurityAnomalyAgent(),
                OperationalIncidentAgent(),
            )
        }
        self.pipelines: dict[str, list[str]] = {
            "lane_pass": ["weighing_intelligence", "vehicle_identity", "cargo_verification"],
            "station_ops": ["traffic_forecast", "operational_incident"],
            "cargo": ["cargo_verification", "release_predictor"],
            "marketplace": ["backhaul_matcher", "environmental"],
            "security": ["security_anomaly"],
        }

    def catalogue(self) -> dict:
        return {"agents": [a.describe() for a in self.agents.values()], "pipelines": self.pipelines,
                "policy": "Agent outputs are advisory. Deterministic clearance, legal and safety rules are never overridden."}

    def run(self, agent: str, inputs: dict[str, Any]) -> AgentResult:
        if agent not in self.agents:
            return AgentResult(agent, False, {}, 0.0, "unknown agent", [], f"no agent named {agent}")
        return self.agents[agent].run(inputs)

    def run_pipeline(self, name: str, inputs: dict[str, Any]) -> dict[str, Any]:
        if name not in self.pipelines:
            raise KeyError(name)
        ctx = dict(inputs)
        results: list[AgentResult] = []
        for agent_name in self.pipelines[name]:
            res = self.agents[agent_name].run(ctx)
            results.append(res)
            if res.ok:
                ctx[f"{agent_name}_output"] = res.output
                ctx.update({k: v for k, v in res.output.items() if k not in ctx})
        return {
            "pipeline": name,
            "results": [r.to_dict() for r in results],
            "ok": all(r.ok for r in results),
            "min_confidence": min((r.confidence for r in results if r.ok), default=0.0),
            "warnings": [w for r in results for w in r.warnings],
        }
