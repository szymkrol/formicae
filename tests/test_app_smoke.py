"""Opens the UI headless for a few frames with the mock engine (no display needed)."""
import os
from pathlib import Path

import pytest

pygame = pytest.importorskip("pygame")
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

import formicae_mock  # noqa: E402

from formicae_ui.config import load_config  # noqa: E402
from formicae_ui.mapgen import generate_map  # noqa: E402
from formicae_ui.ui.app import App  # noqa: E402


def test_app_runs_a_few_frames():
    cfg = load_config(Path(__file__).parent.parent / "configs" / "default.json")
    map_data = generate_map(42, 128, 128, 3, [0, 1, 2])
    sim = formicae_mock.Simulation(cfg)
    sim.initialize(map_data)
    App(sim, cfg, map_data).run(max_frames=10)
    assert sim.tick > 0
