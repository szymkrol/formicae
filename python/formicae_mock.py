"""Mock engine with the same API, dtypes, shapes and errors as the C++ module `formicae` (spec 9.3).

Lets M3 and M4 be developed from week 1 without the C++ build. Ants random-walk; nothing else is
simulated. Owner: P4 (M0). Keep it in sync with engine/bindings/module.cpp (API_VERSION).
"""
from __future__ import annotations

import numpy as np

from formicae_ui.types import ANT_DTYPE, COLONY_DTYPE, NUM_CHANNELS, AntState

__version__ = "0.1.0-mock"
API_VERSION = 1
_PARAMS = {
    "decay_scale": (0.0, 10.0),
    "diffusion": (0.0, 0.2),
    "food_spawn_prob": (0.0, 1.0),
    "food_spawn_interval": (1, 10000),
}
_DIRS = np.array([(0, -1), (1, 0), (0, 1), (-1, 0)])


class Simulation:
    def __init__(self, config: dict):
        self._config = config
        self._n_species = len(config.get("species", []))
        if not 1 <= self._n_species <= 8:
            raise ValueError("species: need 1..8 entries")
        self._seed = int(config.get("seeds", {}).get("sim_seed", 1))
        self._ready = False
        self._tick = 0
        self._params = {k: 0.0 for k in _PARAMS}

    # --- lifecycle ---------------------------------------------------------------------------
    def initialize(self, map_data: dict) -> None:
        for key, dtype in (("terrain", np.uint8), ("food_volume", np.float32),
                           ("food_density", np.float32), ("colonies", np.int32)):
            arr = map_data.get(key)
            if arr is None:
                raise ValueError(f"map_data is missing key '{key}'")
            if arr.dtype != dtype or not arr.flags["C_CONTIGUOUS"]:
                raise ValueError(f"map_data['{key}'] must be {np.dtype(dtype)} and C-contiguous")
        self._map = {k: (v.copy() if isinstance(v, np.ndarray) else v) for k, v in map_data.items()}
        self._reset_state()
        self._ready = True

    def _reset_state(self) -> None:
        m = self._map
        self._rng = np.random.default_rng(self._seed)
        self._tick = 0
        self._terrain = m["terrain"].copy()
        self._food_volume = m["food_volume"].copy()
        self._food_density = m["food_density"].copy()
        self._pher = np.zeros((self._n_species, NUM_CHANNELS, m["height"], m["width"]), np.float32)
        hills = m["colonies"]
        self._colonies = np.zeros(len(hills), dtype=COLONY_DTYPE)
        self._colonies["x"], self._colonies["y"], self._colonies["species"] = hills.T
        self._colonies["alive"] = 1
        self._colonies["health"] = self._colonies["max_health"] = 1000
        self._colonies["stored_energy"] = 600
        n = 200 * len(hills)
        self._ants = np.zeros(n, dtype=ANT_DTYPE)
        owner = np.arange(n) % max(len(hills), 1)
        self._ants["id"] = np.arange(n)
        self._ants["x"], self._ants["y"] = hills[owner, 0], hills[owner, 1]
        self._ants["colony"], self._ants["species"] = owner, hills[owner, 2]
        self._ants["state"] = AntState.SEARCHING
        self._ants["health"] = 10

    def step(self, n: int = 1) -> int:
        if not self._ready:
            raise RuntimeError("step: call initialize() first")
        if not 1 <= n <= 10_000:
            raise ValueError("step: n must be in 1..10000")
        h, w = self._terrain.shape
        for _ in range(n):
            d = _DIRS[self._rng.integers(0, 4, len(self._ants))]
            self._ants["x"] = np.clip(self._ants["x"] + d[:, 0], 1, w - 2)
            self._ants["y"] = np.clip(self._ants["y"] + d[:, 1], 1, h - 2)
            self._ants["age"] += 1
            self._tick += 1
        return self._tick

    def reset(self) -> None:
        if not self._ready:
            raise RuntimeError("reset: call initialize() first")
        self._reset_state()

    @property
    def tick(self) -> int:
        return self._tick

    def save(self, path: str) -> None:
        raise ValueError("save: not implemented in the mock")

    def load(self, path: str) -> None:
        raise ValueError("load: not implemented in the mock")

    # --- controls ----------------------------------------------------------------------------
    def spawn_food(self, x: int, y: int, radius: int, volume: float, density: float) -> int:
        h, w = self._terrain.shape
        if not (0 <= x < w and 0 <= y < h):
            raise ValueError("spawn_food: cell out of bounds")
        if not (0 <= radius <= 10 and volume > 0 and 0 < density <= 100):
            raise ValueError("spawn_food: bad radius, volume or density")
        yy, xx = np.ogrid[:h, :w]
        mask = (xx - x) ** 2 + (yy - y) ** 2 <= radius**2
        self._food_volume[mask] += volume
        self._food_density[mask] = density
        return int(mask.sum())

    def set_terrain(self, x: int, y: int, terrain_id: int) -> None:
        if not 0 <= terrain_id <= 6:
            raise ValueError("set_terrain: unknown terrain id")
        self._terrain[y, x] = terrain_id

    def set_param(self, name: str, value: float) -> None:
        if name not in _PARAMS:
            raise ValueError(f"set_param: unknown parameter {name}")
        lo, hi = _PARAMS[name]
        if not lo <= value <= hi:
            raise ValueError(f"set_param: {name} out of range")
        self._params[name] = value

    def cell_info(self, x: int, y: int) -> dict:
        h, w = self._terrain.shape
        if not (0 <= x < w and 0 <= y < h):
            raise ValueError("cell_info: cell out of bounds")
        hit = np.nonzero((self._ants["x"] == x) & (self._ants["y"] == y))[0]
        ant = {k: self._ants[k][hit[0]].item() for k in ("id", "age", "colony", "species", "caste", "state", "health")} if len(hit) else None
        return {
            "terrain": int(self._terrain[y, x]),
            "food_volume": float(self._food_volume[y, x]),
            "food_density": float(self._food_density[y, x]),
            "pheromone": self._pher[:, :, y, x].copy(),
            "ant": ant,
            "colony": None,
        }

    # --- snapshots (read-only views, like the C++ module) -------------------------------------
    @staticmethod
    def _ro(a: np.ndarray) -> np.ndarray:
        v = a.view()
        v.flags.writeable = False
        return v

    def terrain(self): return self._ro(self._terrain)
    def food_volume(self): return self._ro(self._food_volume)
    def food_density(self): return self._ro(self._food_density)
    def pheromones(self): return self._ro(self._pher)
    def ants(self): return self._ro(self._ants)
    def colonies(self): return self._ro(self._colonies)

    def metrics(self) -> dict:
        s = self._n_species
        pop = np.bincount(self._ants["species"], minlength=s).astype(np.int64)
        zeros = lambda: np.zeros(s, np.int64)  # noqa: E731
        return {
            "tick": self._tick, "population": pop, "births": pop.copy(), "kills": zeros(),
            "deaths_combat": zeros(), "deaths_hazard": zeros(), "deaths_age": zeros(),
            "deaths_orphan": zeros(),
            "colonies_alive": np.bincount(self._colonies["species"], minlength=s).astype(np.int64),
            "food_total_volume": float(self._food_volume.sum()),
            "food_total_energy": float((self._food_volume * self._food_density).sum()),
        }
