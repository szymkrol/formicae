"""Inspector, parameter panel and snapshot key of the UI (spec section 10)."""
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

pygame = pytest.importorskip("pygame")
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

import formicae_mock  # noqa: E402
from formicae_ui.config import load_config  # noqa: E402
from formicae_ui.mapgen import generate_map  # noqa: E402
from formicae_ui.ui.app import App  # noqa: E402
from formicae_ui.ui.camera import Camera  # noqa: E402
from formicae_ui.ui.panels import TUNABLE_PARAMS, ControlPanel, InspectorPanel  # noqa: E402
from formicae_ui.ui.renderer import Renderer  # noqa: E402

CONFIG = load_config(Path(__file__).parent.parent / "configs" / "default.json")
NAMES = [s["name"] for s in CONFIG["species"]]


def _texts(panel: InspectorPanel) -> list[str]:
    return [" ".join(text for _, text in row.cells) for row in panel.rows()]


def _sim(module=formicae_mock):
    map_data = generate_map(42, 64, 64, 3, [0, 1, 2])
    sim = module.Simulation(CONFIG)
    sim.initialize(map_data)
    return sim, map_data


def test_inspector_without_selection_asks_for_a_click():
    assert _texts(InspectorPanel((0, 0, 200, 300), NAMES))[-1] == "click a map cell"


def test_inspector_shows_cell_and_ant():
    sim, _ = _sim()
    ant = sim.ants()[0]
    x, y = int(ant["x"]), int(ant["y"])
    panel = InspectorPanel((0, 0, 200, 300), NAMES)
    panel.select(sim, x, y)
    texts = _texts(panel)
    assert texts[0] == f"Inspector  ({x}, {y})"
    assert texts[1].startswith("terrain ")
    assert any(text.startswith("ant #") and NAMES[int(ant["species"])] in text for text in texts)
    assert any("SEARCHING" in text for text in texts)
    assert sum(text.startswith(tuple(NAMES)) for text in texts) == len(NAMES)  # pheromone rows


def test_inspector_shows_colony_with_real_engine():
    formicae = pytest.importorskip("formicae")
    sim, map_data = _sim(formicae)
    sim.step(5)
    hx, hy, species = (int(v) for v in map_data["colonies"][0])
    panel = InspectorPanel((0, 0, 200, 300), NAMES)
    panel.select(sim, hx, hy)
    texts = _texts(panel)
    assert any(text == f"colony #0  {NAMES[species]}  alive" for text in texts)
    assert any(text.startswith("hp 1000/1000") for text in texts)


def test_inspector_refresh_follows_the_simulation():
    sim, map_data = _sim()
    terrain = map_data["terrain"]
    y, x = (int(v) for v in zip(*((terrain == 0).nonzero()), strict=True).__next__())
    panel = InspectorPanel((0, 0, 200, 300), NAMES)
    panel.select(sim, x, y)
    assert panel.info["food_volume"] == 0
    sim.spawn_food(x, y, 0, 80.0, 25.0)
    panel.refresh(sim)
    assert panel.info["food_volume"] == 80.0
    assert any(text.startswith("food 80.0 units x 25.0") for text in _texts(panel))


def test_control_panel_starts_from_config_and_clamps():
    sim, _ = _sim()
    panel = ControlPanel((0, 0, 300, ControlPanel.height()), sim, CONFIG)
    assert panel.values["diffusion"] == CONFIG["pheromone"]["diffusion"]
    assert panel.values["nav_scale"] == TUNABLE_PARAMS["nav_scale"][2]
    panel.set_value("decay_scale", 99.0)
    assert panel.values["decay_scale"] == 10.0 and sim._params["decay_scale"] == 10.0
    panel.set_value("food_spawn_interval", 12.6)
    assert panel.values["food_spawn_interval"] == 13


def test_control_panel_drag_sets_values():
    pygame.font.init()
    sim, _ = _sim()
    panel = ControlPanel((10, 10, 300, ControlPanel.height()), sim, CONFIG)
    names = list(TUNABLE_PARAMS)
    index = names.index("grad_beta")
    tx, ty, tw, _ = panel._track_rect(index)
    down = SimpleNamespace(type=pygame.MOUSEBUTTONDOWN, button=1, pos=(tx, ty))
    assert panel.handle_event(down) and panel.values["grad_beta"] == 0.0
    move = SimpleNamespace(type=pygame.MOUSEMOTION, pos=(tx + tw, ty), buttons=(1, 0, 0))
    assert panel.handle_event(move) and panel.values["grad_beta"] == 8.0
    up = SimpleNamespace(type=pygame.MOUSEBUTTONUP, button=1, pos=(tx + tw, ty))
    assert panel.handle_event(up) and panel.dragging is None
    # Log-scaled interval: the middle of the track is sqrt(1 * 10000) = 100 ticks.
    tx, ty, tw, _ = panel._track_rect(names.index("food_spawn_interval"))
    middle = SimpleNamespace(type=pygame.MOUSEBUTTONDOWN, button=1, pos=(tx + tw // 2, ty))
    panel.handle_event(middle)
    assert 90 <= panel.values["food_spawn_interval"] <= 110
    outside = SimpleNamespace(type=pygame.MOUSEBUTTONDOWN, button=1, pos=(900, 700))
    assert panel.handle_event(outside) is False
    panel.draw(pygame.Surface((400, 400)))


@pytest.fixture
def app_env():
    sim, map_data = _sim()
    app = App(sim, CONFIG, map_data)
    camera = Camera(1000, 800)
    camera.zoom = 8.0  # the 64x64 test map then covers the parameter panel area
    renderer = Renderer(pygame.Surface((1280, 800)), camera)
    return app, camera, renderer, sim


def test_left_click_inspects_and_respects_spawn_food_mode(app_env):
    app, camera, renderer, sim = app_env
    click = SimpleNamespace(type=pygame.MOUSEBUTTONDOWN, button=1, pos=(40, 40))
    app._handle_event(click, camera, renderer)
    assert app.inspector.cell == renderer.cell_at(40, 40)
    app.inspector.cell = None
    app.spawn_food_mode = True
    app._handle_event(click, camera, renderer)
    assert app.inspector.cell is None  # in spawn-food mode the click spawns food instead
    sidebar = SimpleNamespace(type=pygame.MOUSEBUTTONDOWN, button=1, pos=(1100, 40))
    app.spawn_food_mode = False
    app._handle_event(sidebar, camera, renderer)
    assert app.inspector.cell is None


def test_controls_panel_takes_clicks_only_when_shown(app_env):
    app, camera, renderer, sim = app_env
    tx, ty, tw, _ = app.controls._track_rect(0)
    click = SimpleNamespace(type=pygame.MOUSEBUTTONDOWN, button=1, pos=(tx + tw, ty))
    app._handle_event(SimpleNamespace(type=pygame.KEYDOWN, key=pygame.K_c), camera, renderer)
    assert app.show_controls
    app._handle_event(click, camera, renderer)
    assert app.controls.values["decay_scale"] == 10.0 and app.inspector.cell is None
    app._handle_event(SimpleNamespace(type=pygame.KEYDOWN, key=pygame.K_c), camera, renderer)
    app._handle_event(click, camera, renderer)
    assert app.inspector.cell is not None


def test_save_key_writes_distinct_snapshots(app_env, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    app, camera, renderer, sim = app_env
    sim.step(3)
    first = app._save_snapshot()
    second = app._save_snapshot()
    assert first is not None and second is not None and first != second
    assert first.read_bytes()[:4] == b"ANTS"
    assert "saved" in app._current_status()
    restored = formicae_mock.Simulation(CONFIG)
    restored.load(str(first))
    assert restored.tick == 3


def test_save_failure_is_reported_not_raised(app_env, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    app, camera, renderer, sim = app_env

    def broken(path):
        raise ValueError("disk full")

    monkeypatch.setattr(sim, "save", broken)
    assert app._save_snapshot() is None
    assert app._current_status() == "save failed: disk full"


def test_ant_colors_by_species_caste_and_state():
    import numpy as np
    from formicae_ui.types import ANT_DTYPE, AntState
    from formicae_ui.ui.renderer import (
        SPECIES_CASTE_COLORS,
        SPECIES_COLORS,
        STATE_COLORS,
        ant_colors,
    )

    ants = np.zeros(3, dtype=ANT_DTYPE)
    ants["species"] = [1, 1, 2]
    ants["caste"] = [0, 3, 1]
    ants["state"] = [AntState.SEARCHING, AntState.FIGHTING, AntState.FLEEING]
    by_species = ant_colors(ants, by_state=False)
    assert tuple(by_species[0]) == tuple(SPECIES_COLORS[1])  # STANDARD is the species color
    assert tuple(by_species[1]) == tuple(SPECIES_CASTE_COLORS[1, 3])
    assert len({tuple(c) for c in SPECIES_CASTE_COLORS[1]}) == 4  # castes are distinguishable
    by_state = ant_colors(ants, by_state=True)
    assert tuple(by_state[1]) == STATE_COLORS[AntState.FIGHTING]
    assert tuple(by_state[2]) == STATE_COLORS[AntState.FLEEING]


def test_heatmap_alpha_is_log_scaled():
    import numpy as np
    from formicae_ui.ui.renderer import HEATMAP_MAX_ALPHA, heatmap_alpha

    assert not heatmap_alpha(np.zeros((4, 4), np.uint32)).any()
    alpha = heatmap_alpha(np.array([[0, 1, 10, 1000]], np.uint32))
    assert alpha[0, 0] == 0 and alpha[0, -1] == pytest.approx(HEATMAP_MAX_ALPHA)
    assert alpha[0, 1] > HEATMAP_MAX_ALPHA * 0.05  # rare traffic stays visible on a log scale


def test_overlay_keys(app_env):
    app, camera, renderer, sim = app_env
    press = lambda key: app._handle_event(  # noqa: E731
        SimpleNamespace(type=pygame.KEYDOWN, key=key), camera, renderer
    )
    press(pygame.K_a)
    assert app.overlay.color_by_state
    press(pygame.K_t)
    assert app.overlay.heatmap == "traffic"
    press(pygame.K_t)
    assert app.overlay.heatmap == "combat"
    press(pygame.K_t)
    assert app.overlay.heatmap is None
    press(pygame.K_h)
    assert app.show_help


def test_heatmap_overlay_falls_back_when_disabled():
    import copy

    cfg = copy.deepcopy(CONFIG)
    cfg["enable_heatmaps"] = False
    map_data = generate_map(42, 64, 64, 3, [0, 1, 2])
    sim = formicae_mock.Simulation(cfg)
    sim.initialize(map_data)
    app = App(sim, cfg, map_data)
    app.overlay.heatmap = "traffic"
    views = app._views()
    assert views.heat is None and app.overlay.heatmap is None
    assert "enable_heatmaps" in app._current_status()


def test_every_overlay_combination_draws(app_env):
    pygame.font.init()
    app, camera, renderer, sim = app_env
    sim.step(5)
    font, small = pygame.font.Font(None, 22), pygame.font.Font(None, 18)
    clock = pygame.time.Clock()
    screen = pygame.Surface((1280, 800))
    for by_state in (False, True):
        for heatmap in ("traffic", "combat", None):
            app.overlay.color_by_state = by_state
            app.overlay.heatmap = heatmap
            app.overlay.show_pheromones = True
            renderer.render(app._views(), app.overlay)
            bottom = app._draw_hud(screen, font, small, clock)
            assert bottom < 800 - 150  # room left for the inspector
            app._draw_help(screen, small)
