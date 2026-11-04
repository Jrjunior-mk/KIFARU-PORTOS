"""kifaru_sim — SimPy weighing-station scenario simulation for KIFARU PORTOS (Phase 5, RTM DT-02).

All outputs are modelled, not measured.
"""
from .model import SimConfig, SimResult, TruckRecord, run_model
from .scenarios import SCENARIOS, build, list_scenarios

__all__ = ["SimConfig", "SimResult", "TruckRecord", "run_model", "SCENARIOS", "build", "list_scenarios"]
__version__ = "0.1.0"
