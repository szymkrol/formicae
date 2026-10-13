"""Procedural map generator (spec section 8, interface I1 input). Owner: P5 (M3).

generate_map() currently returns a trivial valid map (flat grass, ROCK border, spaced hills, a few
food clusters) so the rest of the team can run end to end. P5 replaces the body of _generate()
step by step following spec section 8.2 and keeps the signature and the output dict unchanged.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from antsim_ui.types import Terrain


class MapGenError(RuntimeError):
    """Raised when hills cannot be placed after max_retries attempts."""


@dataclass
class MapGenParams:
    """Parameters of spec section 8.1 (defaults as in the table)."""

    noise_octaves: int = 5
    noise_scale: int = 64
    water_level: float = 0.28
    rock_level: float = 0.78
    sand_moisture: float = 0.30
    mud_moisture: float = 0.70
    thorn_threshold: float = 0.85
    hill_radius: int = 2
    min_hill_distance_factor: float = 0.2  # times min(W, H)
    food_cells_per_cluster: int = 20_000
    food_min_hill_distance: int = 15
    max_retries: int = 100


def generate_map(
    seed: int,
    width: int,
    height: int,
    n_colonies: int,
    species_ids: list[int],
    params: MapGenParams | None = None,
) -> dict:
    """Return MapData (spec 8.3): width, height, terrain u8[H,W], food_volume f32[H,W],
    food_density f32[H,W], colonies i32[K,3] (x, y, species_id), effective_seed, stats.

    Deterministic: the same arguments always give the same map. Raises MapGenError.
    """
    params = params or MapGenParams()
    streams = np.random.SeedSequence(seed).spawn(5)  # elevation, moisture, thorns, placement, food
    return _generate(seed, width, height, n_colonies, species_ids, params, streams)


# ---- steps of spec section 8.2 (P5 implements them one by one) -------------------------------
def _noise_field(rng: np.random.Generator, h: int, w: int, octaves: int, scale: int) -> np.ndarray:
    """Step 1: fractal value noise in [0, 1], shape (h, w)."""
    raise NotImplementedError("TODO(P5): step 1")


def _classify(elevation, moisture, thorns, p: MapGenParams) -> np.ndarray:
    """Step 2: terrain ids (uint8) with the ROCK border; caller retries when < 50% passable."""
    raise NotImplementedError("TODO(P5): step 2")


def _place_hills(terrain, n, species_ids, p: MapGenParams, rng) -> np.ndarray:
    """Step 3: int32 [K, 3] rows (x, y, species); flattens footprints to GRASS."""
    raise NotImplementedError("TODO(P5): step 3")


def _connect(terrain: np.ndarray, hills: np.ndarray) -> int:
    """Step 4: carve L-shaped corridors so all hills share one component; returns corridors carved."""
    raise NotImplementedError("TODO(P5): step 4")


def _carve_paths(terrain: np.ndarray, hills: np.ndarray, p: MapGenParams, rng) -> None:
    """Step 5: biased random walks between consecutive hills, cells become PATH."""
    raise NotImplementedError("TODO(P5): step 5")


def _place_food(terrain, hills, p: MapGenParams, rng) -> tuple[np.ndarray, np.ndarray, int]:
    """Step 6: (food_volume, food_density, clusters_skipped)."""
    raise NotImplementedError("TODO(P5): step 6")


def _validate(map_data: dict) -> None:
    """Step 7: border is ROCK, hills and food in one component, shapes and dtypes as in 8.3."""
    raise NotImplementedError("TODO(P5): step 7")


def _generate(seed, width, height, n_colonies, species_ids, params, streams) -> dict:
    """Placeholder implementation (flat map). Replace with steps 1-7 above."""
    rng = np.random.default_rng(streams[3])
    terrain = np.full((height, width), Terrain.GRASS, dtype=np.uint8)
    terrain[0, :] = terrain[-1, :] = terrain[:, 0] = terrain[:, -1] = Terrain.ROCK
    margin = max(8, params.hill_radius + 4)
    hills = np.zeros((n_colonies, 3), dtype=np.int32)
    for i in range(n_colonies):
        hills[i] = (
            int(rng.integers(margin, width - margin)),
            int(rng.integers(margin, height - margin)),
            species_ids[i % len(species_ids)],
        )
    food_volume = np.zeros((height, width), dtype=np.float32)
    food_density = np.zeros((height, width), dtype=np.float32)
    for _ in range(max(2 * n_colonies, 2)):
        x = int(rng.integers(margin, width - margin))
        y = int(rng.integers(margin, height - margin))
        food_volume[y - 1 : y + 2, x - 1 : x + 2] = 100.0
        food_density[y - 1 : y + 2, x - 1 : x + 2] = 30.0
    return {
        "width": width,
        "height": height,
        "terrain": terrain,
        "food_volume": food_volume,
        "food_density": food_density,
        "colonies": hills,
        "effective_seed": seed,
        "stats": {"placeholder": True},
    }
