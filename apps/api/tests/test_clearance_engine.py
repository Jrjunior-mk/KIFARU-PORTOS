"""Unit tests for the deterministic clearance engine (RCS-04..RCS-10)."""
from kifaru.services.clearance_engine import (
    AxleInput,
    CargoInput,
    IdentityInput,
    MeasurementInput,
    VehicleInput,
    decide,
)
from kifaru.services.limits import DEFAULT_LIMITS


def _m(loads, groups, u_frac=0.03, flags=None, cfg="1+1+2", health=None):
    axles = [AxleInput(i, l, l * u_frac * 2, g) for i, (l, g) in enumerate(zip(loads, groups, strict=True))]
    gvm = sum(loads)
    return MeasurementInput(gvm, (sum((a.u_kg) ** 2 for a in axles)) ** 0.5, axles, cfg, flags or [], health or {})


VEH = VehicleInput("v1", "KDA 123A", "1+1+2", 14000, 56000)
ID_OK = IdentityInput(0.97, "v1", "rfid+anpr")


def test_green_when_everything_clear():
    r = decide(_m([6000, 8000, 7500, 7500], [1, 2, 3, 3]), ID_OK, VEH, audit_seed=1, audit_rate=0.0)
    assert r.decision == "GREEN"
    assert r.rules_fired == []
    assert r.margins["gvm"]["margin_kg"] > 0
    assert len(r.evidence_hash) == 64


def test_red_when_gvm_certainly_over():
    # 7 axle limit 56 t; measure 62 t with small U
    r = decide(_m([8000, 9000, 9000, 9000, 9000, 9000, 9000], [1, 2, 2, 3, 3, 3, 3], cfg="1+2+4"), ID_OK, VEH, audit_rate=0.0)
    assert r.decision == "RED"
    assert any(x["rule"] == "GVM_OVER_CERTAIN" for x in r.rules_fired)


def test_amber_when_within_uncertainty_of_limit():
    # steering axle limit 8000 with 5 % tol = 8400; measure 8300 ± 500 -> possible over -> AMBER
    r = decide(_m([8300, 8000, 7000, 7000], [1, 2, 3, 3], u_frac=0.03), ID_OK, VEH, audit_rate=0.0)
    assert r.decision == "AMBER"
    assert any(x["rule"] == "AXLE_GROUP_OVER_POSSIBLE" for x in r.rules_fired)


def test_red_when_axle_group_certainly_over():
    r = decide(_m([9500, 8000, 7000, 7000], [1, 2, 3, 3], u_frac=0.02), ID_OK, VEH, audit_rate=0.0)
    assert r.decision == "RED"
    assert any(x["rule"] == "AXLE_GROUP_OVER_CERTAIN" for x in r.rules_fired)


def test_quality_flag_blocks_green():
    for flag in ("sensor_fault", "speed_unavailable", "no_axles_detected", "calibration_expired", "insufficient_rows"):
        r = decide(_m([6000, 8000, 7500, 7500], [1, 2, 3, 3], flags=[flag]), ID_OK, VEH, audit_rate=0.0)
        assert r.decision != "GREEN", flag


def test_expired_calibration_blocks_green():
    r = decide(_m([6000, 8000, 7500, 7500], [1, 2, 3, 3]), ID_OK, VEH, audit_rate=0.0, lane_calibration_valid=False)
    assert r.decision == "AMBER"


def test_low_identity_confidence_is_amber():
    r = decide(_m([6000, 8000, 7500, 7500], [1, 2, 3, 3]), IdentityInput(0.6, "v1", "anpr"), VEH, audit_rate=0.0)
    assert r.decision == "AMBER"
    assert any(x["rule"] == "IDENTITY_LOW_CONFIDENCE" for x in r.rules_fired)


def test_unknown_vehicle_is_amber():
    r = decide(_m([6000, 8000, 7500, 7500], [1, 2, 3, 3]), IdentityInput(0.0, None, "none"), None, audit_rate=0.0)
    assert r.decision == "AMBER"


def test_identity_conflict_is_red():
    r = decide(_m([6000, 8000, 7500, 7500], [1, 2, 3, 3]), IdentityInput(0.5, "v1", "conflict"), VEH, audit_rate=0.0)
    assert r.decision == "RED"


def test_watchlist_is_red():
    v = VehicleInput("v1", "KDA 123A", "1+1+2", 14000, 56000, watchlist_reason="KRA alert")
    r = decide(_m([6000, 8000, 7500, 7500], [1, 2, 3, 3]), ID_OK, v, audit_rate=0.0)
    assert r.decision == "RED"


def test_seal_breach_is_red():
    r = decide(_m([6000, 8000, 7500, 7500], [1, 2, 3, 3]), ID_OK, VEH, CargoInput(seal_status="breached"), audit_rate=0.0)
    assert r.decision == "RED"


def test_declaration_mismatch_amber_and_red():
    m = _m([6000, 8000, 7500, 7500], [1, 2, 3, 3])  # gvm 29 000, tare 14 000 -> cargo ~15 000
    amber = decide(m, ID_OK, VEH, CargoInput(declared_mass_kg=10000), audit_rate=0.0)  # expected 24 000, diff 5 000 > 15 %
    assert amber.decision == "AMBER"
    red = decide(m, ID_OK, VEH, CargoInput(declared_mass_kg=2000), audit_rate=0.0)  # expected 16 000, diff 13 000
    assert red.decision == "RED"


def test_axle_config_mismatch_is_amber():
    r = decide(_m([6000, 8000, 7500, 7500], [1, 2, 3, 3], cfg="1+3"), ID_OK, VEH, audit_rate=0.0)
    assert r.decision == "AMBER"
    assert any(x["rule"] == "AXLE_CONFIG_MISMATCH" for x in r.rules_fired)


def test_random_audit_is_seeded_and_logged():
    m = _m([6000, 8000, 7500, 7500], [1, 2, 3, 3])
    a = decide(m, ID_OK, VEH, audit_rate=1.0, audit_seed=42)
    assert a.decision == "AMBER" and a.audit_selected and a.audit_seed == 42
    b = decide(m, ID_OK, VEH, audit_rate=1.0, audit_seed=42)
    assert a.evidence_hash == b.evidence_hash  # deterministic


def test_group_limits_configuration():
    assert DEFAULT_LIMITS.group_limit_kg(0, 1) == 8000
    assert DEFAULT_LIMITS.group_limit_kg(1, 1) == 10000
    assert DEFAULT_LIMITS.group_limit_kg(1, 2) == 18000
    assert DEFAULT_LIMITS.group_limit_kg(2, 3) == 24000
    assert DEFAULT_LIMITS.gvm_limit_for_config([1, 2, 3]) == 50000
    assert DEFAULT_LIMITS.gvm_limit_for_config([1, 3, 3]) == 56000
