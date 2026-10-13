"""API contract test: runs against the mock and, when built, against the real module (same checks)."""
from pathlib import Path

import numpy as np
import pytest

import antsim_mock
from antsim_ui.config import load_config
from antsim_ui.mapgen import generate_map
from antsim_ui.types import ANT_DTYPE, COLONY_DTYPE

CONFIG = load_config(Path(__file__).parent.parent / "configs" / "default.json")


def _implementations():
    impls = [antsim_mock]
    try:
        import antsim  # compiled module
        impls.append(antsim)
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
                "deaths_age", "deaths_orphan", "colonies_alive", "food_total_volume",
                "food_total_energy"):
        assert key in m


def test_set_param_range(sim):
    sim.set_param("decay_scale", 2.0)
    with pytest.raises(ValueError):
        sim.set_param("decay_scale", 99)
    with pytest.raises(ValueError):
        sim.set_param("nonsense", 1)
