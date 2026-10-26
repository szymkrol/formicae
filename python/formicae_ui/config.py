"""Configuration loading and validation (spec section 11, interface I5). Owner: P4 (M0)."""

from __future__ import annotations

import json
import math
import warnings
from pathlib import Path
from typing import Any

from formicae_ui.types import MAX_CASTES, S_MAX

SECTIONS = {
    "world",
    "time",
    "pheromone",
    "food",
    "terrain",
    "species",
    "colony",
    "hostility",
    "render",
    "analytics",
    "seeds",
    "max_ants_total",
    "enable_heatmaps",
}

SECTION_KEYS = {
    "world": {"width", "height", "n_colonies"},
    "time": {"base_tps", "frame_budget_ms"},
    "pheromone": {
        "decay",
        "decay_scale",
        "diffusion",
        "cutoff",
        "hit_alarm",
        "death_alarm",
        "hazard_alarm",
        "home_beacon",
        "food_density_ref",
        "epsilon",
    },
    "food": {
        "spawn_interval",
        "spawn_prob",
        "max_food_cells",
        "cluster_radius_min",
        "cluster_radius_max",
        "volume_min",
        "volume_max",
        "density_min",
        "density_max",
    },
    "colony": {
        "hill_radius",
        "max_health",
        "initial_energy",
        "max_population",
        "spawn_cooldown",
        "loot_density",
    },
    "seeds": {"sim_seed"},
    "render": {"window", "sidebar_width", "target_fps"},
    "analytics": {"sample_every_ticks", "redraw_seconds", "history_samples"},
}
TERRAIN_KEYS = {"name", "move_cost", "evap_mod", "passable", "hazard_damage"}
SPECIES_KEYS = {
    "name",
    "castes",
    "max_health",
    "max_age",
    "flee_threshold",
    "flee_ticks",
    "speed",
    "random_move_prob",
    "alpha",
    "forward_bonus",
    "damage",
    "armor",
    "accuracy",
    "defend_while_carrying",
    "cost",
    "carry_capacity",
    "a_home",
    "a_food",
    "trail_len_home",
    "trail_len_food",
    "danger_k",
    "danger_k_home",
    "orphan_loss",
}
CASTE_KEYS = {
    "name",
    "max_health_mul",
    "damage_mul",
    "armor_mul",
    "speed_mul",
    "carry_mul",
    "cost_mul",
    "random_move_prob_add",
    "a_home_mul",
    "a_food_mul",
    "danger_k_add",
    "defend_while_carrying",
}
TERRAIN_NAMES = {"GRASS", "SAND", "MUD", "PATH", "ROCK", "WATER", "THORNS"}
SPECIES_RANGES = {
    "max_health": (0, None, False),
    "max_age": (1, 2**32 - 1, True),
    "flee_threshold": (0, 1, False),
    "flee_ticks": (0, 255, True),
    "speed": (0, 1, False),
    "random_move_prob": (0, 1, False),
    "alpha": (0, None, False),
    "forward_bonus": (0, None, False),
    "damage": (0, None, False),
    "armor": (0, None, False),
    "accuracy": (0, 1, False),
    "cost": (0, None, False),
    "carry_capacity": (0, None, False),
    "a_home": (0, None, False),
    "a_food": (0, None, False),
    "trail_len_home": (0, None, False),
    "trail_len_food": (0, None, False),
    "danger_k": (None, None, False),
    "danger_k_home": (None, None, False),
    "orphan_loss": (0, 1, False),
}
CASTE_RANGES = {
    "max_health_mul": (0, None, False),
    "damage_mul": (0, None, False),
    "armor_mul": (0, None, False),
    "speed_mul": (0, None, False),
    "carry_mul": (0, None, False),
    "cost_mul": (0, None, False),
    "random_move_prob_add": (None, None, False),
    "a_home_mul": (0, None, False),
    "a_food_mul": (0, None, False),
    "danger_k_add": (None, None, False),
}


class ConfigError(ValueError):
    """Raised with a message listing every problem found."""


def load_config(path: str | Path) -> dict[str, Any]:
    """Read the JSON file, reject unknown keys, check ranges, return the validated dict."""
    with open(path, encoding="utf-8") as fh:
        cfg = json.load(fh)
    problems = validate_config(cfg)
    if problems:
        raise ConfigError("\n".join(problems))
    return cfg


def validate_config(cfg: Any) -> list[str]:
    """Return all schema and range problems; return an empty list for a valid config."""
    if not isinstance(cfg, dict):
        return ["configuration must be a JSON object"]

    problems: list[str] = []
    for key in cfg:
        if key not in SECTIONS:
            problems.append(f"unknown top-level key '{key}'")

    for section, allowed in SECTION_KEYS.items():
        if section in cfg:
            _check_object(cfg[section], section, allowed, problems)

    _check_int_range(cfg, "max_ants_total", "max_ants_total", problems, 1, 2**31 - 1)
    _check_bool(cfg, "enable_heatmaps", "enable_heatmaps", problems)

    world = cfg.get("world")
    if isinstance(world, dict):
        _check_int_range(world, "width", "world.width", problems, 64, 2048)
        _check_int_range(world, "height", "world.height", problems, 64, 2048)
        _check_int_range(world, "n_colonies", "world.n_colonies", problems, 1, None)

    time = cfg.get("time")
    if isinstance(time, dict):
        _check_number_range(
            time, "base_tps", "time.base_tps", problems, 0, None, low_inclusive=False
        )
        _check_number_range(
            time, "frame_budget_ms", "time.frame_budget_ms", problems, 0, None, low_inclusive=False
        )

    pheromone = cfg.get("pheromone")
    if isinstance(pheromone, dict):
        if "decay" in pheromone:
            decay = pheromone["decay"]
            if not isinstance(decay, list) or len(decay) != 3:
                problems.append("pheromone.decay must be an array of 3 values")
            else:
                for index, value in enumerate(decay):
                    _check_value_range(value, f"pheromone.decay[{index}]", problems, 0, 1)
        for key, low, high in (
            ("decay_scale", 0, 10),
            ("diffusion", 0, 0.2),
            ("cutoff", 0, 1),
            ("hit_alarm", 0, 1),
            ("death_alarm", 0, 1),
            ("hazard_alarm", 0, 1),
            ("home_beacon", 0, 1),
            ("food_density_ref", 0, None),
            ("epsilon", 0, None),
        ):
            _check_number_range(
                pheromone,
                key,
                f"pheromone.{key}",
                problems,
                low,
                high,
                low_inclusive=key not in {"food_density_ref", "epsilon"},
            )

    food = cfg.get("food")
    if isinstance(food, dict):
        for key, low, high in (
            ("spawn_interval", 1, 10000),
            ("max_food_cells", 0, None),
            ("cluster_radius_min", 1, 3),
            ("cluster_radius_max", 1, 3),
        ):
            _check_int_range(food, key, f"food.{key}", problems, low, high)
        for key, low, high in (
            ("spawn_prob", 0, 1),
            ("volume_min", 50, 200),
            ("volume_max", 50, 200),
            ("density_min", 10, 50),
            ("density_max", 10, 50),
        ):
            _check_number_range(
                food,
                key,
                f"food.{key}",
                problems,
                low,
                high,
            )
        _check_order(food, "cluster_radius_min", "cluster_radius_max", "food", problems)
        _check_order(food, "volume_min", "volume_max", "food", problems)
        _check_order(food, "density_min", "density_max", "food", problems)

    colony = cfg.get("colony")
    if isinstance(colony, dict):
        for key, low, high in (
            ("hill_radius", 0, None),
            ("max_population", 1, 2**32 - 1),
            ("spawn_cooldown", 0, 255),
        ):
            _check_int_range(colony, key, f"colony.{key}", problems, low, high)
        for key, low, high in (
            ("max_health", 0, None),
            ("initial_energy", 0, None),
            ("loot_density", 0, None),
        ):
            _check_number_range(
                colony,
                key,
                f"colony.{key}",
                problems,
                low,
                high,
                low_inclusive=key == "initial_energy",
            )

    seeds = cfg.get("seeds")
    if isinstance(seeds, dict):
        _check_int_range(seeds, "sim_seed", "seeds.sim_seed", problems, 0, 2**64 - 1)

    render = cfg.get("render")
    if isinstance(render, dict):
        if "window" in render:
            window = render["window"]
            if (
                not isinstance(window, list)
                or len(window) != 2
                or any(not _is_int(value) or value <= 0 for value in window)
            ):
                problems.append("render.window must be an array of 2 positive integers")
        for key in ("sidebar_width", "target_fps"):
            _check_int_range(render, key, f"render.{key}", problems, 1, None)
        if (
            isinstance(render.get("window"), list)
            and len(render["window"]) == 2
            and _is_int(render["window"][0])
        ):
            sidebar_width = render.get("sidebar_width")
            if _is_int(sidebar_width) and sidebar_width >= render["window"][0]:
                problems.append("render.sidebar_width must be less than render.window[0]")

    analytics = cfg.get("analytics")
    if isinstance(analytics, dict):
        _check_int_range(
            analytics, "sample_every_ticks", "analytics.sample_every_ticks", problems, 1, None
        )
        _check_int_range(
            analytics, "history_samples", "analytics.history_samples", problems, 1, None
        )
        _check_number_range(
            analytics,
            "redraw_seconds",
            "analytics.redraw_seconds",
            problems,
            0,
            None,
            low_inclusive=False,
        )

    if "terrain" in cfg:
        terrain = cfg["terrain"]
        if not isinstance(terrain, list):
            problems.append("terrain must be an array of 7 terrain definitions")
        else:
            if len(terrain) != 7:
                problems.append("terrain must contain exactly 7 terrain definitions")
            names: list[str] = []
            for index, item in enumerate(terrain):
                path = f"terrain[{index}]"
                if not _check_object(item, path, TERRAIN_KEYS, problems):
                    continue
                name = item.get("name")
                if not isinstance(name, str) or name not in TERRAIN_NAMES:
                    allowed_names = ", ".join(sorted(TERRAIN_NAMES))
                    problems.append(f"{path}.name must be one of {allowed_names}")
                else:
                    names.append(name)
                _check_number_range(
                    item, "move_cost", f"{path}.move_cost", problems, 0, None, low_inclusive=False
                )
                _check_number_range(item, "evap_mod", f"{path}.evap_mod", problems, 0, None)
                _check_bool(item, "passable", f"{path}.passable", problems)
                _check_number_range(
                    item, "hazard_damage", f"{path}.hazard_damage", problems, 0, None
                )
            if len(names) == len(terrain) and set(names) != TERRAIN_NAMES:
                problems.append("terrain must define each terrain name exactly once")

    species = cfg.get("species")
    if not isinstance(species, list):
        problems.append("species must be an array")
        species = []
    if not 1 <= len(species) <= S_MAX:
        problems.append(f"species: need 1..{S_MAX} entries, got {len(species)}")
    for index, item in enumerate(species):
        path = f"species[{index}]"
        if not _check_object(item, path, SPECIES_KEYS, problems):
            continue
        if not isinstance(item.get("name"), str) or not item["name"].strip():
            problems.append(f"{path}.name must be a non-empty string")
        for key, (low, high, integer) in SPECIES_RANGES.items():
            if integer:
                _check_int_range(item, key, f"{path}.{key}", problems, int(low), int(high))
            else:
                _check_number_range(
                    item,
                    key,
                    f"{path}.{key}",
                    problems,
                    low,
                    high,
                    low_inclusive=key
                    not in {
                        "max_health",
                        "speed",
                        "cost",
                        "carry_capacity",
                        "trail_len_home",
                        "trail_len_food",
                    },
                    high_inclusive=True,
                )
        _check_bool(item, "defend_while_carrying", f"{path}.defend_while_carrying", problems)
        castes = item.get("castes", [])
        if not isinstance(castes, list):
            problems.append(f"{path}.castes must be an array")
            continue
        if len(castes) > MAX_CASTES:
            problems.append(f"{path}.castes must contain at most {MAX_CASTES} entries")
        for caste_index, caste in enumerate(castes):
            caste_path = f"{path}.castes[{caste_index}]"
            if not _check_object(caste, caste_path, CASTE_KEYS, problems):
                continue
            if "name" in caste and (
                not isinstance(caste["name"], str) or not caste["name"].strip()
            ):
                problems.append(f"{caste_path}.name must be a non-empty string")
            for key, (low, high, _) in CASTE_RANGES.items():
                _check_number_range(caste, key, f"{caste_path}.{key}", problems, low, high)
            if "defend_while_carrying" in caste:
                value = caste["defend_while_carrying"]
                if not (isinstance(value, bool) or (_is_int(value) and value in (-1, 0, 1))):
                    problems.append(
                        f"{caste_path}.defend_while_carrying must be true, false, or -1 (inherit)"
                    )

    if "hostility" in cfg:
        hostility = cfg["hostility"]
        if not isinstance(hostility, list) or len(hostility) != len(species):
            problems.append(f"hostility must be a square matrix for {len(species)} species")
        else:
            for row_index, row in enumerate(hostility):
                if not isinstance(row, list) or len(row) != len(species):
                    problems.append(f"hostility[{row_index}] must contain {len(species)} entries")
                    continue
                for col_index, value in enumerate(row):
                    if not (isinstance(value, bool) or (_is_int(value) and value in (0, 1))):
                        problems.append(f"hostility[{row_index}][{col_index}] must be 0 or 1")

    return problems


def warn_if_overcrowded(max_ants_total: int, passable_cells: int) -> None:
    """Warn when the configured ant cap exceeds a quarter of the passable map cells."""
    if max_ants_total > passable_cells * 0.25:
        warnings.warn(
            f"max_ants_total ({max_ants_total}) exceeds 25% of passable cells ({passable_cells})",
            UserWarning,
            stacklevel=2,
        )


def _check_object(value: Any, path: str, allowed: set[str], problems: list[str]) -> bool:
    if not isinstance(value, dict):
        problems.append(f"{path} must be an object")
        return False
    for key in value:
        if key not in allowed:
            problems.append(f"unknown key '{path}.{key}'")
    return True


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _check_bool(data: dict[str, Any], key: str, path: str, problems: list[str]) -> None:
    if key in data and not isinstance(data[key], bool):
        problems.append(f"{path} must be a boolean")


def _check_int_range(
    data: dict[str, Any],
    key: str,
    path: str,
    problems: list[str],
    low: int | None,
    high: int | None,
) -> None:
    if key not in data:
        return
    value = data[key]
    if not _is_int(value):
        problems.append(f"{path} must be an integer")
    elif (low is not None and value < low) or (high is not None and value > high):
        problems.append(f"{path} must be in {low}..{high if high is not None else 'unbounded'}")


def _check_number_range(
    data: dict[str, Any],
    key: str,
    path: str,
    problems: list[str],
    low: float | None,
    high: float | None,
    *,
    low_inclusive: bool = True,
    high_inclusive: bool = True,
) -> None:
    if key not in data:
        return
    _check_value_range(
        data[key],
        path,
        problems,
        low,
        high,
        low_inclusive=low_inclusive,
        high_inclusive=high_inclusive,
    )


def _check_value_range(
    value: Any,
    path: str,
    problems: list[str],
    low: float | None,
    high: float | None,
    *,
    low_inclusive: bool = True,
    high_inclusive: bool = True,
) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        problems.append(f"{path} must be a finite number")
        return
    below = low is not None and (value < low or (not low_inclusive and value == low))
    above = high is not None and (value > high or (not high_inclusive and value == high))
    if below or above:
        lower = f"{'[' if low_inclusive else '('}{low}" if low is not None else "(-inf"
        upper = f"{high}{']' if high_inclusive else ')'}" if high is not None else "inf)"
        problems.append(f"{path} must be in {lower}, {upper}")


def _check_order(
    data: dict[str, Any], lower_key: str, upper_key: str, path: str, problems: list[str]
) -> None:
    lower, upper = data.get(lower_key), data.get(upper_key)

    def is_number(value: Any) -> bool:
        return (
            not isinstance(value, bool) and isinstance(value, (int, float)) and math.isfinite(value)
        )

    if is_number(lower) and is_number(upper) and lower > upper:
        problems.append(f"{path}.{lower_key} must be <= {path}.{upper_key}")
