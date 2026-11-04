"""Analytics (spec sections 9.5 and 10): history, rates, CSV export and Agg rendering."""
import csv
import os

import formicae_mock
import numpy as np
import pytest
from formicae_ui.analytics import Analytics
from formicae_ui.types import COLONY_DTYPE, METRIC_KEYS_PER_SPECIES


def _metrics(tick, n_species, combat=0):
    m = {key: np.zeros(n_species, dtype=np.int64) for key in METRIC_KEYS_PER_SPECIES}
    m["tick"] = tick
    m["population"][:] = 10 + tick // 10
    m["deaths_combat"][:] = combat
    m["food_total_volume"] = 100.0
    m["food_total_energy"] = 3000.0 - tick
    return m


def _colonies(n, energy=50.0):
    c = np.zeros(n, dtype=COLONY_DTYPE)
    c["stored_energy"] = energy
    c["species"] = np.arange(n) % 2
    return c


def test_record_grows_beyond_initial_capacity():
    a = Analytics(n_species=2, n_colonies=3)
    for i in range(3000):
        a.record(_metrics(10 * i, 2), _colonies(3))
    assert len(a) == 3000
    assert a.history().shape == (3000, len(a.columns()))
    assert a.ticks()[-1] == 29_990
    assert a.series("population").shape == (3000, 2)
    assert a.series("energy").shape == (3000, 3)


def test_csv_matches_history(tmp_path):
    a = Analytics(n_species=2, n_colonies=2)
    for i in range(5):
        a.record(_metrics(10 * i, 2, combat=i), _colonies(2, energy=1.5 * i))
    path = tmp_path / "metrics.csv"
    a.export_csv(path)
    with open(path, newline="", encoding="utf-8") as fh:
        rows = list(csv.reader(fh))
    assert rows[0] == a.columns()
    assert rows[0][:3] == ["tick", "pop_s0", "pop_s1"]
    assert rows[0][-1] == "food_total_energy"
    assert len(rows) == 6
    np.testing.assert_allclose(np.array(rows[1:], dtype=float), a.history())


def test_combat_deaths_per_100_ticks():
    a = Analytics(n_species=1, n_colonies=1)
    for i in range(30):  # one combat death per 10 ticks
        a.record(_metrics(10 * i, 1, combat=i), _colonies(1))
    rate = a.combat_deaths_per_window()
    assert rate[-1, 0] == pytest.approx(10.0)
    rates = a.casualty_rates()
    assert set(rates) == {"combat", "hazard", "age", "orphan"}
    assert rates["combat"][-1, 0] == pytest.approx(0.1)
    assert rates["combat"][0, 0] == 0.0


def test_clear_drops_history():
    a = Analytics(n_species=1, n_colonies=1)
    a.record(_metrics(10, 1), _colonies(1))
    a.clear()
    assert len(a) == 0


def test_render_returns_surface_of_requested_size():
    pygame = pytest.importorskip("pygame")
    os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
    a = Analytics(n_species=2, n_colonies=3)
    surface = a.render((640, 440))  # empty history renders placeholders
    assert isinstance(surface, pygame.Surface)
    assert surface.get_size() == (640, 440)
    for i in range(50):
        a.record(_metrics(10 * i, 2, combat=i // 3), _colonies(3, energy=float(i)))
    assert a.render((280, 600)).get_size() == (280, 600)


def test_records_mock_engine_metrics():
    from pathlib import Path

    from formicae_ui.config import load_config
    from formicae_ui.mapgen import generate_map

    cfg = load_config(Path(__file__).parent.parent / "configs" / "default.json")
    md = generate_map(1, 128, 128, 3, list(range(len(cfg["species"]))))
    sim = formicae_mock.Simulation(cfg)
    sim.initialize(md)
    a = Analytics(n_species=len(cfg["species"]), n_colonies=3)
    for _ in range(5):
        sim.step(10)
        a.record(sim.metrics(), sim.colonies())
    assert len(a) == 5
    assert list(a.ticks()) == [10, 20, 30, 40, 50]
