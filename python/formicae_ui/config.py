"""Configuration loading and validation (spec section 11, interface I5). Owner: P4 (M0)."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from formicae_ui.types import S_MAX

# Allowed top-level sections of the JSON file; the nested keys are checked in _check_section().
SECTIONS = {
    "world", "time", "pheromone", "food", "terrain", "species", "colony", "hostility", "render",
    "analytics", "seeds", "max_ants_total", "enable_heatmaps",
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


def validate_config(cfg: dict[str, Any]) -> list[str]:
    """Return a list of problems (empty when the config is valid)."""
    problems = [f"unknown top-level key '{k}'" for k in cfg if k not in SECTIONS]
    species = cfg.get("species", [])
    if not 1 <= len(species) <= S_MAX:
        problems.append(f"species: need 1..{S_MAX} entries, got {len(species)}")
    for i, s in enumerate(species):
        speed = s.get("speed", 1.0)
        if not 0 < speed <= 1:
            problems.append(f"species[{i}].speed must be in (0, 1]")
    # TODO(P4): check every key and range of spec sections 5.2, 7 and 11 (unknown nested keys too),
    #           and warn when max ants exceed 25% of passable cells.
    return problems
