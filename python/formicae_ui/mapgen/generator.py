"""Procedural map generator (spec section 8, interface I1 input). Owner: P5 (M3).

generate_map() builds a map in the seven steps of spec section 8.2: fractal noise fields, terrain
classification, hill placement, connectivity corridors, paths between hills, food clusters and a
final validation. Only NumPy is required; scipy.ndimage.label is used for labeling when installed.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass

import numpy as np

from formicae_ui.types import Terrain

try:  # optional speed-up for connected-component labeling (spec 8.2 step 4)
    from scipy.ndimage import label as _scipy_label
except ImportError:  # pragma: no cover - depends on the environment
    _scipy_label = None


IMPASSABLE = (Terrain.ROCK, Terrain.WATER)
MAX_SEED_RETRIES = 10
MIN_PASSABLE_FRACTION = 0.5
PATH_TOWARD_TARGET_PROB = 0.7
FOOD_VOLUME_RANGE = (50.0, 200.0)
FOOD_DENSITY_RANGE = (10.0, 50.0)
FOOD_DENSITY_JITTER = (0.8, 1.2)
FOOD_RICHNESS_DISTANCE_FACTOR = 0.4  # times max(W, H)
HILL_MARGIN = 2

# (dx, dy) for N, E, S, W
_DIRS = ((0, -1), (1, 0), (0, 1), (-1, 0))


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
    if not (64 <= width <= 2048 and 64 <= height <= 2048):
        raise ValueError(f"map size must be 64..2048 per side, got {width}x{height}")
    if n_colonies < 1:
        raise ValueError("n_colonies must be at least 1")
    if not species_ids:
        raise ValueError("species_ids must not be empty")

    for attempt in range(MAX_SEED_RETRIES + 1):
        effective_seed = seed + attempt
        # elevation, moisture, thorns, placement and paths, food
        streams = np.random.SeedSequence(effective_seed).spawn(5)
        elevation, moisture, thorns = (
            _noise_field(np.random.default_rng(streams[k]), height, width,
                         params.noise_octaves, params.noise_scale)
            for k in range(3)
        )
        terrain = _classify(elevation, moisture, thorns, params)
        passable_fraction = float(_passable(terrain).mean())
        if passable_fraction >= MIN_PASSABLE_FRACTION:
            break
    else:
        raise MapGenError(
            f"no seed in {seed}..{seed + MAX_SEED_RETRIES} gives at least "
            f"{MIN_PASSABLE_FRACTION:.0%} passable cells"
        )

    placement_rng = np.random.default_rng(streams[3])
    food_rng = np.random.default_rng(streams[4])

    hills = _place_hills(terrain, n_colonies, species_ids, params, placement_rng)
    corridors = _connect(terrain, hills, params.hill_radius)
    _carve_paths(terrain, hills, params, placement_rng)
    food_volume, food_density, placed, skipped = _place_food(terrain, hills, params, food_rng)

    map_data = {
        "width": width,
        "height": height,
        "terrain": terrain,
        "food_volume": food_volume,
        "food_density": food_density,
        "colonies": hills,
        "effective_seed": effective_seed,
        "stats": {
            "passable_fraction": float(_passable(terrain).mean()),
            "hills_placed": int(len(hills)),
            "food_clusters_placed": placed,
            "food_clusters_skipped": skipped,
            "corridors_carved": corridors,
            "seed_retries": effective_seed - seed,
        },
    }
    _validate(map_data, params.hill_radius)
    return map_data


# ---- helpers -----------------------------------------------------------------------------------
def _passable(terrain: np.ndarray) -> np.ndarray:
    return (terrain != Terrain.ROCK) & (terrain != Terrain.WATER)


def _hill_mask(shape: tuple[int, int], hills: np.ndarray, radius: int) -> np.ndarray:
    """Boolean mask of all hill footprint cells (squares of half-size `radius`)."""
    mask = np.zeros(shape, dtype=bool)
    for x, y, _ in hills:
        mask[y - radius : y + radius + 1, x - radius : x + radius + 1] = True
    return mask


def _distance_to_hills(shape: tuple[int, int], hills: np.ndarray) -> np.ndarray:
    """Euclidean distance of every cell to the nearest hill center, float32 [H, W]."""
    h, w = shape
    ys = np.arange(h, dtype=np.float32)[:, None]
    xs = np.arange(w, dtype=np.float32)[None, :]
    dist = np.full(shape, np.inf, dtype=np.float32)
    for x, y, _ in hills:
        np.minimum(dist, np.sqrt((xs - x) ** 2 + (ys - y) ** 2), out=dist)
    return dist


def _component_of(passable: np.ndarray, x: int, y: int) -> np.ndarray:
    """Boolean mask of the 4-connected component of passable cells that contains (x, y)."""
    if not passable[y, x]:
        return np.zeros_like(passable)
    if _scipy_label is not None:
        labels, _ = _scipy_label(passable)  # default structure is 4-connectivity
        return labels == labels[y, x]
    return _flood_fill(passable, x, y)


def _flood_fill(passable: np.ndarray, x: int, y: int) -> np.ndarray:
    """Breadth-first flood fill over horizontal runs of passable cells.

    Each row is split into maximal runs [start, end); two runs are 4-connected when they lie in
    adjacent rows and share at least one column. Searching over runs instead of single cells keeps
    the pure-NumPy fallback fast enough for 2048x2048 maps.
    """
    h, w = passable.shape
    padded = np.zeros((h, w + 2), dtype=np.int8)
    padded[:, 1:-1] = passable
    edges = np.diff(padded, axis=1)
    run_row, run_start = np.nonzero(edges == 1)  # row-major order: sorted by row, then start
    _, run_end = np.nonzero(edges == -1)
    row_first = np.searchsorted(run_row, np.arange(h + 1))

    def runs_overlapping(row: int, s: int, e: int):
        lo, hi = row_first[row], row_first[row + 1]
        k = lo + int(np.searchsorted(run_end[lo:hi], s, side="right"))
        while k < hi and run_start[k] < e:
            yield k
            k += 1

    first = next(runs_overlapping(y, x, x + 1))
    seen = np.zeros(len(run_row), dtype=bool)
    seen[first] = True
    queue = deque((first,))
    while queue:
        k = queue.popleft()
        row, s, e = int(run_row[k]), int(run_start[k]), int(run_end[k])
        for nrow in (row - 1, row + 1):
            if 0 <= nrow < h:
                for j in runs_overlapping(nrow, s, e):
                    if not seen[j]:
                        seen[j] = True
                        queue.append(j)

    marks = np.zeros((h, w + 1), dtype=np.int32)
    np.add.at(marks, (run_row[seen], run_start[seen]), 1)
    np.add.at(marks, (run_row[seen], run_end[seen]), -1)
    return np.cumsum(marks, axis=1)[:, :w] > 0


# ---- steps of spec section 8.2 -----------------------------------------------------------------
def _noise_field(rng: np.random.Generator, h: int, w: int, octaves: int, scale: int) -> np.ndarray:
    """Step 1: fractal value noise in [0, 1], shape (h, w).

    Octave o uses a random lattice with cell size max(2, scale / 2^o), upsampled with smoothstep
    bilinear interpolation and weighted by 0.5^o; the sum is rescaled to [0, 1] by min and max.
    """
    total = np.zeros((h, w), dtype=np.float64)
    for o in range(octaves):
        cell = max(2.0, scale / 2**o)
        lattice = rng.random((int(np.ceil(h / cell)) + 2, int(np.ceil(w / cell)) + 2))
        fy = np.arange(h) / cell
        fx = np.arange(w) / cell
        y0 = fy.astype(np.intp)
        x0 = fx.astype(np.intp)
        ty = fy - y0
        tx = fx - x0
        ty = (ty * ty * (3.0 - 2.0 * ty))[:, None]
        tx = (tx * tx * (3.0 - 2.0 * tx))[None, :]
        top = lattice[np.ix_(y0, x0)] * (1.0 - tx) + lattice[np.ix_(y0, x0 + 1)] * tx
        bottom = lattice[np.ix_(y0 + 1, x0)] * (1.0 - tx) + lattice[np.ix_(y0 + 1, x0 + 1)] * tx
        total += (top * (1.0 - ty) + bottom * ty) * 0.5**o
    lo, hi = total.min(), total.max()
    if hi - lo <= 0.0:
        return np.zeros((h, w), dtype=np.float64)
    return (total - lo) / (hi - lo)


def _classify(elevation, moisture, thorns, p: MapGenParams) -> np.ndarray:
    """Step 2: terrain ids (uint8) with the ROCK border; caller retries when < 50% passable.

    Rules are applied from the lowest to the highest priority so that the first matching rule of
    the spec wins.
    """
    terrain = np.full(elevation.shape, Terrain.GRASS, dtype=np.uint8)
    terrain[moisture > p.mud_moisture] = Terrain.MUD
    terrain[moisture < p.sand_moisture] = Terrain.SAND
    terrain[thorns > p.thorn_threshold] = Terrain.THORNS
    terrain[elevation > p.rock_level] = Terrain.ROCK
    terrain[elevation < p.water_level] = Terrain.WATER
    terrain[0, :] = terrain[-1, :] = terrain[:, 0] = terrain[:, -1] = Terrain.ROCK
    return terrain


def _place_hills(terrain, n, species_ids, p: MapGenParams, rng) -> np.ndarray:
    """Step 3: int32 [K, 3] rows (x, y, species); flattens footprints to GRASS.

    Candidate centers are drawn from the cells whose footprint plus a 2-cell margin is entirely
    passable and free of THORNS (precomputed with a summed-area table); each draw then only has to
    pass the minimum-distance test.
    """
    h, w = terrain.shape
    half = p.hill_radius + HILL_MARGIN
    good = (_passable(terrain) & (terrain != Terrain.THORNS)).astype(np.int32)
    sat = np.zeros((h + 1, w + 1), dtype=np.int32)
    sat[1:, 1:] = good.cumsum(0).cumsum(1)
    side = 2 * half + 1
    window_sum = sat[side:, side:] - sat[:-side, side:] - sat[side:, :-side] + sat[:-side, :-side]
    cy, cx = np.nonzero(window_sum == side * side)  # top-left corners of fully good windows
    cy = cy + half
    cx = cx + half

    if len(cx) == 0:
        raise MapGenError("could not place hill of colony 0: no valid footprint on the map")

    min_dist_sq = (p.min_hill_distance_factor * min(w, h)) ** 2
    hills = np.zeros((n, 3), dtype=np.int32)
    for i in range(n):
        for _ in range(p.max_retries):
            k = int(rng.integers(len(cx)))
            x, y = int(cx[k]), int(cy[k])
            if all((x - hx) ** 2 + (y - hy) ** 2 >= min_dist_sq for hx, hy, _ in hills[:i]):
                hills[i] = (x, y, species_ids[i % len(species_ids)])
                break
        else:
            raise MapGenError(f"could not place hill of colony {i} after {p.max_retries} attempts")

    r = p.hill_radius
    for x, y, _ in hills:
        terrain[y - r : y + r + 1, x - r : x + r + 1] = Terrain.GRASS
    return hills


def _connect(terrain: np.ndarray, hills: np.ndarray, hill_radius: int) -> int:
    """Step 4: carve L-shaped corridors so all hills share one component; returns corridors carved.

    Each corridor runs horizontally along the hill's row to the column of hill 0, then vertically
    to hill 0. Impassable and THORNS cells on it become GRASS. The component is re-labeled after
    every corridor.
    """
    x0, y0 = int(hills[0, 0]), int(hills[0, 1])
    component = _component_of(_passable(terrain), x0, y0)
    carved = 0
    for x, y, _ in hills[1:]:
        x, y = int(x), int(y)
        if component[y, x]:
            continue
        row = terrain[y, min(x, x0) : max(x, x0) + 1]
        col = terrain[min(y, y0) : max(y, y0) + 1, x0]
        for segment in (row, col):
            blocked = np.isin(segment, (*IMPASSABLE, Terrain.THORNS))
            segment[blocked] = Terrain.GRASS
        carved += 1
        component = _component_of(_passable(terrain), x0, y0)
    return carved


def _carve_paths(terrain: np.ndarray, hills: np.ndarray, p: MapGenParams, rng) -> None:
    """Step 5: biased random walks between consecutive hills, cells become PATH.

    Moving inside the starting footprint is allowed (otherwise a walk could never leave its hill)
    but those cells stay GRASS; entering any other hill footprint or an impassable cell is skipped.
    """
    h, w = terrain.shape
    r = p.hill_radius
    hill_mask = _hill_mask(terrain.shape, hills, r)
    passable = _passable(terrain)
    for i in range(len(hills) - 1):
        x, y = int(hills[i, 0]), int(hills[i, 1])
        sx, sy = x, y
        tx, ty = int(hills[i + 1, 0]), int(hills[i + 1, 1])
        max_steps = 4 * (abs(tx - x) + abs(ty - y))
        for _ in range(max_steps):
            dx, dy = tx - x, ty - y
            if rng.random() < PATH_TOWARD_TARGET_PROB:
                if abs(dx) >= abs(dy):
                    step = (int(np.sign(dx)), 0)
                else:
                    step = (0, int(np.sign(dy)))
            else:
                step = _DIRS[int(rng.integers(4))]
            nx, ny = x + step[0], y + step[1]
            if not (0 <= nx < w and 0 <= ny < h):
                continue
            if abs(nx - tx) <= r and abs(ny - ty) <= r:
                break  # reached the target footprint
            in_start = abs(nx - sx) <= r and abs(ny - sy) <= r
            if not passable[ny, nx] or (hill_mask[ny, nx] and not in_start):
                continue
            x, y = nx, ny
            if not hill_mask[y, x]:
                terrain[y, x] = Terrain.PATH


def _place_food(terrain, hills, p: MapGenParams, rng) -> tuple[np.ndarray, np.ndarray, int, int]:
    """Step 6: (food_volume, food_density, clusters_placed, clusters_skipped).

    Food is restricted to the component that holds the hills, so that step 7 holds: cells on
    passable islands that ants can never reach receive no food.
    """
    h, w = terrain.shape
    food_volume = np.zeros((h, w), dtype=np.float32)
    food_density = np.zeros((h, w), dtype=np.float32)

    hill_mask = _hill_mask(terrain.shape, hills, p.hill_radius)
    reachable = _component_of(_passable(terrain), int(hills[0, 0]), int(hills[0, 1]))
    dist = _distance_to_hills(terrain.shape, hills)
    can_hold_food = reachable & ~hill_mask
    center_ok = can_hold_food & (terrain != Terrain.THORNS) & (dist >= p.food_min_hill_distance)

    n_clusters = max(2 * len(hills), round(w * h / p.food_cells_per_cluster))
    richness_scale = FOOD_RICHNESS_DISTANCE_FACTOR * max(w, h)
    placed = skipped = 0
    for _ in range(n_clusters):
        for _ in range(p.max_retries):
            x, y = int(rng.integers(w)), int(rng.integers(h))
            if center_ok[y, x]:
                break
        else:
            skipped += 1
            continue

        r = int(rng.integers(1, 4))
        y_lo, y_hi = max(0, y - r), min(h, y + r + 1)
        x_lo, x_hi = max(0, x - r), min(w, x + r + 1)
        yy, xx = np.ogrid[y_lo:y_hi, x_lo:x_hi]
        disc = ((xx - x) ** 2 + (yy - y) ** 2 <= r * r) & can_hold_food[y_lo:y_hi, x_lo:x_hi]

        d = min(1.0, float(dist[y, x]) / richness_scale)
        lo, hi = FOOD_DENSITY_RANGE
        density = np.clip((lo + (hi - lo) * d) * rng.uniform(*FOOD_DENSITY_JITTER), lo, hi)
        volumes = rng.uniform(*FOOD_VOLUME_RANGE, size=disc.shape).astype(np.float32)

        food_volume[y_lo:y_hi, x_lo:x_hi][disc] = volumes[disc]
        food_density[y_lo:y_hi, x_lo:x_hi][disc] = density
        placed += 1
    return food_volume, food_density, placed, skipped


def _validate(map_data: dict, hill_radius: int) -> None:
    """Step 7: border is ROCK, hills and food in one component, shapes and dtypes as in 8.3.

    Raises MapGenError instead of using `assert`, so the checks also run under `python -O`.
    """
    w, h = map_data["width"], map_data["height"]
    terrain = map_data["terrain"]
    volume = map_data["food_volume"]
    density = map_data["food_density"]
    hills = map_data["colonies"]

    expected = {
        "terrain": (terrain, np.uint8, (h, w)),
        "food_volume": (volume, np.float32, (h, w)),
        "food_density": (density, np.float32, (h, w)),
    }
    for name, (arr, dtype, shape) in expected.items():
        if arr.dtype != dtype or arr.shape != shape or not arr.flags.c_contiguous:
            raise MapGenError(f"{name}: expected C-contiguous {np.dtype(dtype)} {shape}, "
                              f"got {arr.dtype} {arr.shape}")
    if hills.dtype != np.int32 or hills.ndim != 2 or hills.shape[1] != 3:
        raise MapGenError(f"colonies: expected int32 [K, 3], got {hills.dtype} {hills.shape}")

    border = np.concatenate((terrain[0], terrain[-1], terrain[:, 0], terrain[:, -1]))
    if np.any(border != Terrain.ROCK):
        raise MapGenError("map border is not ROCK")

    passable = _passable(terrain)
    has_food = volume > 0
    if np.any(has_food & ~passable):
        raise MapGenError("food on impassable cells")
    if np.any(has_food & _hill_mask(terrain.shape, hills, hill_radius)):
        raise MapGenError("food on hill cells")
    if np.any(has_food != (density > 0)):
        raise MapGenError("food_density must be > 0 exactly where food_volume > 0")

    component = _component_of(passable, int(hills[0, 0]), int(hills[0, 1]))
    for i, (x, y, _) in enumerate(hills):
        if not component[y, x]:
            raise MapGenError(f"hill of colony {i} is not connected to hill 0")
    if np.any(has_food & ~component):
        raise MapGenError("food cells outside the component of the hills")
