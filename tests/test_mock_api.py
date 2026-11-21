"""API contract test against mock and, when built, the real module."""
import copy
import sys
from pathlib import Path

import formicae_mock
import numpy as np
import pytest
from formicae_ui.config import load_config
from formicae_ui.mapgen import generate_map
from formicae_ui.types import ANT_DTYPE, COLONY_DTYPE

CONFIG = load_config(Path(__file__).parent.parent / "configs" / "default.json")


def _implementations():
    impls = [formicae_mock]
    try:
        import formicae  # compiled module
        impls.append(formicae)
    except ImportError:
        pass
    return impls


@pytest.fixture(params=_implementations(), ids=lambda m: m.__name__)
def sim(request):
    s = request.param.Simulation(CONFIG)
    s.initialize(generate_map(42, 64, 64, 3, [0, 1, 2]))
    return s


def test_step_and_tick(sim):
    assert sim.step(5) == 5 and sim.tick == 5
    with pytest.raises(ValueError):
        sim.step(0)


def test_views_are_read_only_with_expected_dtypes(sim):
    assert sim.terrain().shape == (64, 64) and sim.terrain().dtype == np.uint8
    assert sim.pheromones().shape == (3, 3, 64, 64)
    assert sim.ants().dtype.itemsize == ANT_DTYPE.itemsize
    assert sim.colonies().dtype.itemsize == COLONY_DTYPE.itemsize
    with pytest.raises(ValueError):
        sim.terrain()[0, 0] = 1


def test_wrong_dtype_is_rejected(sim):
    bad = generate_map(1, 64, 64, 3, [0, 1, 2])
    bad["terrain"] = bad["terrain"].astype(np.int64)
    with pytest.raises(ValueError):
        sim.initialize(bad)


def test_metrics_keys(sim):
    m = sim.metrics()
    for key in ("tick", "population", "births", "kills", "deaths_combat", "deaths_hazard",
                "deaths_age", "deaths_orphan", "colonies_alive", "deliveries",
                "return_steps_sum", "food_total_volume", "food_total_energy"):
        assert key in m


def test_set_param_range(sim):
    sim.set_param("decay_scale", 2.0)
    sim.set_param("nav_scale", 2.0)
    sim.set_param("noise_damp_scale", 1.5)
    with pytest.raises(ValueError):
        sim.set_param("decay_scale", 99)
    with pytest.raises(ValueError):
        sim.set_param("nav_scale", 5)
    with pytest.raises(ValueError):
        sim.set_param("noise_damp_scale", 3)
    with pytest.raises(ValueError):
        sim.set_param("nonsense", 1)


def _snapshot(sim) -> dict:
    """Copies of every view plus the metrics, for exact state comparisons."""
    state = {name: np.array(getattr(sim, name)()) for name in (
        "terrain", "food_volume", "food_density", "pheromones", "ants", "colonies")}
    state["metrics"] = sim.metrics()
    return state


def _assert_same_state(a: dict, b: dict) -> None:
    for name in ("terrain", "food_volume", "food_density", "pheromones", "ants", "colonies"):
        assert a[name].tobytes() == b[name].tobytes(), name
    for key, value in a["metrics"].items():
        assert np.array_equal(value, b["metrics"][key]), key


def test_save_load_round_trip_continues_identically(sim, tmp_path):
    path = str(tmp_path / "run.ants")
    sim.step(120)
    sim.save(path)
    sim.step(80)
    expected = _snapshot(sim)

    sim.load(path)
    assert sim.tick == 120
    sim.step(80)
    assert sim.tick == 200
    _assert_same_state(expected, _snapshot(sim))
    assert open(path, "rb").read(4) == b"ANTS"


def test_load_into_a_fresh_simulation(sim, tmp_path):
    path = str(tmp_path / "run.ants")
    sim.step(30)
    sim.save(path)
    fresh = type(sim)(CONFIG)  # never initialized; load() makes it runnable
    fresh.load(path)
    assert fresh.tick == 30
    _assert_same_state(_snapshot(sim), _snapshot(fresh))
    fresh.step(1)


def test_save_and_load_errors(sim, tmp_path):
    module = type(sim)
    with pytest.raises(RuntimeError):
        module(CONFIG).save(str(tmp_path / "x.ants"))
    with pytest.raises(ValueError):
        sim.load(str(tmp_path / "missing.ants"))
    garbage = tmp_path / "garbage.ants"
    garbage.write_bytes(b"NOPE" + bytes(64))
    with pytest.raises(ValueError):
        sim.load(str(garbage))
    truncated = tmp_path / "truncated.ants"
    sim.save(str(truncated))
    truncated.write_bytes(truncated.read_bytes()[:100])
    with pytest.raises(ValueError):
        sim.load(str(truncated))
    assert sim.step(1) == 1  # a failed load leaves the simulation untouched


def _fresh(module, config=CONFIG, seed=None):
    cfg = copy.deepcopy(config)
    if seed is not None:
        cfg["seeds"]["sim_seed"] = seed
    s = module.Simulation(cfg)
    s.initialize(generate_map(42, 64, 64, 3, [0, 1, 2]))
    return s


def test_state_hash_is_deterministic(sim):
    module = sys.modules[type(sim).__module__]
    twin = _fresh(module)
    other = _fresh(module, seed=CONFIG["seeds"]["sim_seed"] + 1)
    start = sim.state_hash()
    for _ in range(3):
        for s in (sim, twin, other):
            s.step(40)
        assert sim.state_hash() == twin.state_hash()
        assert sim.state_hash() != other.state_hash()
    sim.reset()
    assert sim.state_hash() == start


def test_state_hash_survives_save_and_load(sim, tmp_path):
    path = str(tmp_path / "run.ants")
    sim.step(60)
    sim.save(path)
    expected = sim.state_hash()
    sim.step(5)
    sim.load(path)
    assert sim.state_hash() == expected


def test_state_hash_requires_initialize(sim):
    with pytest.raises(RuntimeError):
        type(sim)(CONFIG).state_hash()


def test_heatmaps(sim):
    sim.step(30)
    for getter in (sim.traffic, sim.combat_map):
        layer = getter()
        assert layer.shape == (64, 64) and layer.dtype == np.uint32
        assert not layer.flags.writeable
    assert sim.traffic().sum() > 0
    module = sys.modules[type(sim).__module__]
    disabled = copy.deepcopy(CONFIG)
    disabled["enable_heatmaps"] = False
    off = _fresh(module, disabled)
    with pytest.raises(RuntimeError):
        off.traffic()
    with pytest.raises(RuntimeError):
        off.combat_map()


def test_population_per_caste(sim):
    sim.step(50)
    m = sim.metrics()
    assert m["population_caste"].shape == (3, 4) and m["population_caste"].dtype == np.int64
    assert np.array_equal(m["population_caste"].sum(axis=1), m["population"])
