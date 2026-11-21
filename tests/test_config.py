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


def test_movement_section_optional_and_validated():
    cfg = valid_config()
    cfg.pop("movement", None)
    for sp in cfg["species"]:
        sp.pop("nav_beta", None)
        sp.pop("noise_damp", None)
        sp.pop("lost_mult", None)
    assert validate_config(cfg) == []

    cfg = valid_config()
    cfg["movement"]["nope"] = 1
    assert any("unknown key 'movement.nope'" in p for p in validate_config(cfg))

    cfg = valid_config()
    cfg["movement"]["nav_memory"] = 1
    assert any("unknown key 'movement.nav_memory'" in p for p in validate_config(cfg))

    cfg = valid_config()
    cfg["movement"]["noise_tau_ref"] = 0
    assert any("movement.noise_tau_ref" in p for p in validate_config(cfg))

    cfg = valid_config()
    cfg["species"][0]["nav_beta"] = -1
    assert any("species[0].nav_beta" in p for p in validate_config(cfg))

    cfg = valid_config()
    cfg["species"][0]["noise_damp"] = 1.1
    assert any("species[0].noise_damp" in p for p in validate_config(cfg))

    cfg = valid_config()
    cfg["species"][0]["lost_mult"] = -0.1
    assert any("species[0].lost_mult" in p for p in validate_config(cfg))

    cfg = valid_config()
    cfg["species"][0]["lost_mult"] = 0
    assert validate_config(cfg) == []


def test_terrain_order_is_fixed():
    cfg = valid_config()
    cfg["terrain"][4], cfg["terrain"][5] = cfg["terrain"][5], cfg["terrain"][4]
    problems = validate_config(cfg)
    assert any("terrain[4].name must be ROCK" in p for p in problems)
    assert any("terrain[5].name must be WATER" in p for p in problems)


# The C++ module must reject bad configs on its own, even when load_config() is bypassed.
def _engine_error(cfg) -> str:
    formicae = pytest.importorskip("formicae")
    with pytest.raises(ValueError) as err:
        formicae.Simulation(cfg)
    return str(err.value)


def test_engine_accepts_default_config():
    formicae = pytest.importorskip("formicae")
    formicae.Simulation(valid_config())


@pytest.mark.parametrize(
    ("mutate", "expected"),
    [
        (lambda c: c.update(bogus=1), "unknown key 'bogus'"),
        (lambda c: c["pheromone"].update(decay_rate=1), "unknown key 'pheromone.decay_rate'"),
        (lambda c: c["species"][1].update(sped=1), "unknown key 'species[1].sped'"),
        (lambda c: c["species"][0].update(castes=[{"nme": "X"}]),
         "unknown key 'species[0].castes[0].nme'"),
        (lambda c: c["terrain"][2].update(cost=1), "unknown key 'terrain[2].cost'"),
        (lambda c: c["species"][0].update(max_age="old"), "species[0].max_age has the wrong type"),
        (lambda c: c["pheromone"].update(decay=[0.1, 0.1]), "pheromone.decay needs 3 values"),
        (lambda c: c.update(hostility=[[0, 1], [1, 0]]), "hostility must be a 3 x 3 matrix"),
        (lambda c: c.update(hostility=[[0, 2, 1], [1, 0, 1], [1, 1, 0]]),
         "hostility[0][1] must be 0 or 1"),
        (lambda c: c["species"][2].update(accuracy=1.5), "species[2].accuracy must be in [0, 1]"),
        (lambda c: c["species"][0].update(cost=0), "species[0].cost must be > 0"),
        (lambda c: c["species"][0].update(flee_ticks=300), "species[0].flee_ticks must be in"),
        (lambda c: c["pheromone"].update(diffusion=0.5), "pheromone.diffusion must be in"),
        (lambda c: c["food"].update(volume_min=150, volume_max=100),
         "food.volume_min must be <= food.volume_max"),
        (lambda c: c["colony"].update(loot_density=0), "colony.loot_density must be > 0"),
        (lambda c: c["movement"].update(nav_max=0.1),
         "movement.nav_max must be >= movement.nav_min"),
        (lambda c: c["terrain"][0].update(name="SAND"), "terrain[0].name must be GRASS"),
        (lambda c: c["species"][0].update(speed=float("nan")),
         "species[0].speed must be in (0, 1]"),
    ],
)
def test_engine_rejects_bad_config(mutate, expected):
    cfg = valid_config()
    mutate(cfg)
    assert expected in _engine_error(cfg)


def test_engine_reports_every_problem_at_once():
    cfg = valid_config()
    cfg["bogus"] = 1
    cfg["species"][0]["accuracy"] = 2.0
    cfg["food"]["spawn_prob"] = -1.0
    message = _engine_error(cfg)
    assert "unknown key 'bogus'" in message
    # Range checks run once the schema is clean; fix the key and both range errors appear.
    del cfg["bogus"]
    message = _engine_error(cfg)
    assert "species[0].accuracy" in message and "food.spawn_prob" in message


def test_caste_ratio_is_checked():
    cfg = valid_config()
    cfg["species"][0]["caste_ratio"] = [0, 0]
    cfg["species"][1]["caste_ratio"] = [1, -1]
    cfg["species"][2].pop("castes")
    cfg["species"][2]["caste_ratio"] = [1, 1]
    problems = validate_config(cfg)
    assert any("species[0].caste_ratio needs at least one positive weight" in p for p in problems)
    assert any("species[1].caste_ratio[1]" in p for p in problems)
    assert any("species[2].caste_ratio[1] weights a caste" in p for p in problems)
    for expected in ("species[0].caste_ratio needs", "species[2].caste_ratio[1] weights a caste"):
        assert expected in _engine_error(cfg)


def test_friendly_swap_must_be_boolean():
    cfg = valid_config()
    cfg["movement"]["friendly_swap"] = 1
    assert "movement.friendly_swap must be a boolean" in validate_config(cfg)


def test_caste_scenario_spawns_every_caste():
    formicae = pytest.importorskip("formicae")
    from formicae_ui.mapgen import generate_map

    cfg = load_config(DEFAULT.parent / "scenario_castes.json")
    sim = formicae.Simulation(cfg)
    sim.initialize(generate_map(42, 128, 128, 3, [0, 1, 2]))
    sim.step(300)
    by_caste = sim.metrics()["population_caste"]
    assert (by_caste[0] > 0).all()  # Swarmers are cheap enough to spawn all four castes quickly


def test_default_caste_ratio_matches_a_config_without_castes():
    """Spec 5.2 acceptance: castes with the default ratio [1, 0, 0, 0] change nothing."""
    formicae = pytest.importorskip("formicae")
    from formicae_ui.mapgen import generate_map

    plain = valid_config()
    for species in plain["species"]:
        species.pop("castes")
        species.pop("caste_ratio")
    runs = []
    for cfg in (valid_config(), plain):
        sim = formicae.Simulation(cfg)
        sim.initialize(generate_map(42, 96, 96, 3, [0, 1, 2]))
        sim.step(600)
        runs.append((sim.ants().tobytes(), sim.pheromones().tobytes(), sim.colonies().tobytes()))
    assert runs[0] == runs[1]
