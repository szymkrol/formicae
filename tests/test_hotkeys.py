"""Ensure App hotkey constants exist on pygame-ce (regression for K_MINUS)."""
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

pygame = pytest.importorskip("pygame")
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

import formicae_mock  # noqa: E402
from formicae_ui.config import load_config  # noqa: E402
from formicae_ui.mapgen import generate_map  # noqa: E402
from formicae_ui.types import Channel  # noqa: E402
from formicae_ui.ui.app import App  # noqa: E402
from formicae_ui.ui.camera import Camera  # noqa: E402
from formicae_ui.ui.renderer import Renderer  # noqa: E402

# Every pygame.K_* name referenced by App._handle_event must resolve.
HOTKEY_CONSTANTS = (
    "K_SPACE",
    "K_n",
    "K_PLUS",
    "K_EQUALS",
    "K_KP_PLUS",
    "K_MINUS",
    "K_KP_MINUS",
    "K_p",
    "K_e",
    "K_1",
    "K_KP1",
    "K_2",
    "K_KP2",
    "K_3",
    "K_KP3",
    "K_LEFTBRACKET",
    "K_RIGHTBRACKET",
    "K_f",
    "K_r",
)


@pytest.fixture
def app_env():
    cfg = load_config(Path(__file__).parent.parent / "configs" / "default.json")
    map_data = generate_map(42, 64, 64, 2, [0, 1])
    sim = formicae_mock.Simulation(cfg)
    sim.initialize(map_data)
    app = App(sim, cfg, map_data)
    camera = Camera(100, 100)
    screen = pygame.Surface((1280, 800))
    renderer = Renderer(screen, camera)
    return app, camera, renderer, sim


def test_hotkey_constants_exist():
    missing = [name for name in HOTKEY_CONSTANTS if not hasattr(pygame, name)]
    assert missing == [], f"unknown pygame key constants: {missing}"


def test_keydown_handlers_do_not_crash(app_env):
    app, camera, renderer, sim = app_env
    pygame.display.init()
    try:
        for name in HOTKEY_CONSTANTS:
            event = SimpleNamespace(type=pygame.KEYDOWN, key=getattr(pygame, name))
            assert app._handle_event(event, camera, renderer) is True
        assert app.overlay.show_pheromones is True or app.overlay.channel in Channel
        tick_before = sim.tick
        app._reset_simulation()
        assert sim.tick == 0
        assert tick_before >= 0
    finally:
        pygame.display.quit()
