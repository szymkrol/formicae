import json
from pathlib import Path

import pytest
from formicae_ui.config import ConfigError, load_config, validate_config

DEFAULT = Path(__file__).parent.parent / "configs" / "default.json"


def valid_config():
    return load_config(DEFAULT)


def test_default_config_is_valid():
    cfg = load_config(DEFAULT)
    assert len(cfg["species"]) == 3


def test_unknown_key_is_reported():
    cfg = valid_config()
    cfg["bogus"] = 1
    problems = validate_config(cfg)
    assert any("unknown" in p for p in problems)


def test_species_count_is_checked():
    cfg = valid_config()
    cfg["species"] = []
    assert any("1..8" in problem for problem in validate_config(cfg))


def test_unknown_nested_keys_are_reported():
    cfg = valid_config()
    cfg["pheromone"]["misspelled"] = 1
    cfg["species"][0]["movement"] = {}
    cfg["species"][0]["castes"] = [{"unknown": 1}]

    problems = validate_config(cfg)

    assert "unknown key 'pheromone.misspelled'" in problems
    assert "unknown key 'species[0].movement'" in problems
    assert "unknown key 'species[0].castes[0].unknown'" in problems


@pytest.mark.parametrize(
    ("path", "value", "message"),
    [
        (("world", "width"), 63, "world.width"),
        (("max_ants_total",), 2**31, "max_ants_total"),
        (("time", "base_tps"), 0, "time.base_tps"),
        (("pheromone", "decay"), [0.1, 0.2], "pheromone.decay"),
        (("food", "spawn_prob"), 1.1, "food.spawn_prob"),
        (("food", "volume_min"), 250, "food.volume_min"),
        (("food", "density_max"), 51, "food.density_max"),
        (("colony", "hill_radius"), -1, "colony.hill_radius"),
        (("seeds", "sim_seed"), -1, "seeds.sim_seed"),
        (("render", "window"), [1280, True], "render.window"),
        (("analytics", "sample_every_ticks"), 0, "analytics.sample_every_ticks"),
        (("species", 0, "speed"), 0, "species[0].speed"),
        (("species", 0, "accuracy"), 1.1, "species[0].accuracy"),
        (("species", 0, "max_age"), 1.5, "species[0].max_age"),
        (("species", 0, "defend_while_carrying"), 1, "species[0].defend_while_carrying"),
        (("species", 0, "castes"), [{"speed_mul": -1}], "species[0].castes[0].speed_mul"),
    ],
)
def test_invalid_values_report_their_path(path, value, message):
    cfg = valid_config()
    target = cfg
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value

    problems = validate_config(cfg)

    assert any(message in problem for problem in problems)


def test_invalid_section_shapes_are_reported_without_raising():
    cfg = valid_config()
    cfg["world"] = []
    cfg["species"] = [None]
    cfg["terrain"] = [None]

    problems = validate_config(cfg)

    assert any("world must be an object" in problem for problem in problems)
    assert any("species[0] must be an object" in problem for problem in problems)
    assert any("terrain[0] must be an object" in problem for problem in problems)


def test_invalid_render_window_values_do_not_crash_cross_field_validation():
    cfg = valid_config()
    cfg["render"]["window"] = ["wide", 800]

    problems = validate_config(cfg)

    assert any("render.window" in problem for problem in problems)


def test_caste_limit_is_checked():
    cfg = valid_config()
    cfg["species"][0]["castes"] = [{}] * 5

    assert any("at most 4" in problem for problem in validate_config(cfg))


def test_hostility_matrix_must_match_species_count():
    cfg = valid_config()
    cfg["hostility"] = [[1, 0], [0, 1]]

    assert any("square matrix for 3 species" in problem for problem in validate_config(cfg))


def test_load_config_raises_config_error_for_invalid_values(tmp_path):
    cfg = valid_config()
    cfg["world"]["width"] = 1
    path = tmp_path / "invalid.json"
    path.write_text(json.dumps(cfg), encoding="utf-8")

    with pytest.raises(ConfigError, match="world.width"):
        load_config(path)


@pytest.mark.parametrize("value", [None, [], "config"])
def test_non_object_config_is_reported(value):
    assert validate_config(value) == ["configuration must be a JSON object"]
