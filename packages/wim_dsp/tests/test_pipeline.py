import numpy as np
import pytest

from kifaru_wim_dsp import ChannelCalibration, SensorModel, TruckProfile, generate_pass, process_pass, random_truck


def _truck(loads, spacings, speed=18.0):
    return TruckProfile(axle_loads_kg=loads, axle_spacings_m=spacings, speed_mps=speed, bounce_frac=0.02)


def test_detects_axles_speed_and_loads_within_tolerance():
    rng = np.random.default_rng(1)
    truck = _truck([6500, 9000, 8500, 8500], [3.6, 5.8, 1.35], speed=20.0)
    p = generate_pass(truck, rng=rng)
    m = process_pass(p.channels, p.fs_hz, pavement_temp_c=p.pavement_temp_c)
    assert m.axle_count == 4
    assert abs(m.speed_mps - 20.0) / 20.0 < 0.02
    assert m.axle_config == "1+1+2"
    assert abs(m.gvm_kg - truck.gvm_kg) / truck.gvm_kg < 0.05
    for a, truth in zip(m.axles, truck.axle_loads_kg, strict=True):
        assert abs(a.load_kg - truth) / truth < 0.08
        assert a.u_kg > 0
    assert m.quality_flags == []


@pytest.mark.parametrize("seed", range(20))
def test_random_trucks_gvm_error_mostly_under_5pct(seed):
    rng = np.random.default_rng(seed)
    truck = random_truck(rng)
    p = generate_pass(truck, rng=rng)
    m = process_pass(p.channels, p.fs_hz, pavement_temp_c=p.pavement_temp_c)
    assert m.axle_count == len(truck.axle_loads_kg)
    assert abs(m.gvm_kg - truck.gvm_kg) / truck.gvm_kg < 0.06


def test_temperature_compensation_removes_bias():
    rng = np.random.default_rng(3)
    truck = _truck([7000, 9500], [4.2])
    sensors = {k: SensorModel(temp_coeff_per_c=-0.004, pavement_temp_c=55.0) for k in ("P1", "P2", "P3", "BP")}
    p = generate_pass(truck, sensors=sensors, rng=rng)
    uncomp = process_pass(p.channels, p.fs_hz, pavement_temp_c=55.0)
    cal = {k: ChannelCalibration(temp_coeff_per_c=-0.004) for k in ("P1", "P2", "P3", "BP")}
    comp = process_pass(p.channels, p.fs_hz, calibration=cal, pavement_temp_c=55.0)
    assert abs(comp.gvm_kg - truck.gvm_kg) < abs(uncomp.gvm_kg - truck.gvm_kg)
    assert abs(comp.gvm_kg - truck.gvm_kg) / truck.gvm_kg < 0.04


def test_dead_sensor_raises_fault_flag_but_still_measures():
    rng = np.random.default_rng(5)
    truck = _truck([6000, 9000, 8000], [4.5, 1.35])
    p = generate_pass(truck, sensors={"P1": SensorModel(fault="dead")}, rng=rng)
    m = process_pass(p.channels, p.fs_hz)
    assert "sensor_fault" in m.quality_flags
    assert m.sensor_health["P1"].status == "fault"
    assert m.axle_count == 3


def test_noisy_sensor_flags_degraded():
    rng = np.random.default_rng(6)
    truck = _truck([6000, 9000], [4.2])
    p = generate_pass(truck, sensors={"P2": SensorModel(fault="noisy")}, rng=rng)
    m = process_pass(p.channels, p.fs_hz)
    assert m.sensor_health["P2"].status in ("degraded", "fault")
    assert any(f.startswith("sensor_") for f in m.quality_flags)
