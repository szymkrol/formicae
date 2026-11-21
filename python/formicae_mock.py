"""Mock engine with the same API, dtypes, shapes and errors as the C++ module `formicae` (spec 9.3).

Lets M3 and M4 be developed from week 1 without the C++ build. Ants random-walk; nothing else is
simulated. Owner: P4 (M0). Keep it in sync with engine/bindings/module.cpp (API_VERSION).
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import zipfile

import numpy as np
from formicae_ui.types import ANT_DTYPE, COLONY_DTYPE, MAX_CASTES, NUM_CHANNELS, AntState

__version__ = "0.1.0-mock"
API_VERSION = 1
_PARAMS = {
    "decay_scale": (0.0, 10.0),
    "diffusion": (0.0, 0.2),
    "food_spawn_prob": (0.0, 1.0),
    "food_spawn_interval": (1, 10000),
    "grad_beta": (0.0, 8.0),
    "nav_scale": (0.0, 4.0),
    "noise_damp_scale": (0.0, 2.0),
}
_DIRS = np.array([(0, -1), (1, 0), (0, 1), (-1, 0)])
# Snapshot file: "ANTS" + little-endian u32 format version, then an .npz archive (no pickles).
_SNAPSHOT_HEADER = b"ANTS" + (1).to_bytes(4, "little")
_MAP_ARRAYS = ("terrain", "food_volume", "food_density", "colonies")


class Simulation:
    def __init__(self, config: dict):
        self._config = config
        self._n_species = len(config.get("species", []))
        if not 1 <= self._n_species <= 8:
            raise ValueError("species: need 1..8 entries")
        self._seed = int(config.get("seeds", {}).get("sim_seed", 1))
        self._heatmaps = bool(config.get("enable_heatmaps", False))
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
        heat_shape = (m["height"], m["width"]) if self._heatmaps else (0, 0)
        self._traffic = np.zeros(heat_shape, np.uint32)
        self._combat = np.zeros(heat_shape, np.uint32)
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
            if self._heatmaps:
                np.add.at(self._traffic, (self._ants["y"], self._ants["x"]), 1)
            self._tick += 1
        return self._tick

    def reset(self) -> None:
        if not self._ready:
            raise RuntimeError("reset: call initialize() first")
        self._reset_state()

    @property
    def tick(self) -> int:
        return self._tick

    def state_hash(self) -> int:
        """64-bit fingerprint of everything save() stores (same contract as the C++ module)."""
        if not self._ready:
            raise RuntimeError("state_hash: call initialize() first")
        digest = hashlib.blake2b(digest_size=8)
        meta, arrays = self._snapshot()
        digest.update(json.dumps(meta, sort_keys=True).encode())
        for name in sorted(arrays):
            digest.update(name.encode())
            digest.update(np.ascontiguousarray(arrays[name]).tobytes())
        return int.from_bytes(digest.digest(), "little")

    def _snapshot(self) -> tuple[dict, dict]:
        meta = {
            "config": self._config,
            "seed": self._seed,
            "tick": self._tick,
            "params": self._params,
            "rng": self._rng.bit_generator.state,
            "width": int(self._map["width"]),
            "height": int(self._map["height"]),
        }
        arrays = {f"map_{k}": self._map[k] for k in _MAP_ARRAYS}
        arrays.update(
            terrain=self._terrain, food_volume=self._food_volume, food_density=self._food_density,
            pher=self._pher, ants=self._ants, colonies=self._colonies, traffic=self._traffic,
            combat=self._combat,
        )
        return meta, arrays

    def save(self, path: str) -> None:
        if not self._ready:
            raise RuntimeError("save: call initialize() first")
        meta, arrays = self._snapshot()
        arrays["meta"] = np.frombuffer(json.dumps(meta).encode(), np.uint8)
        tmp = f"{path}.tmp"
        try:
            with open(tmp, "wb") as fh:
                fh.write(_SNAPSHOT_HEADER)
                np.savez(fh, **arrays)
            os.replace(tmp, path)
        except OSError as err:
            with contextlib.suppress(OSError):
                os.remove(tmp)
            raise ValueError(f"save: cannot write '{path}': {err}") from err

    def load(self, path: str) -> None:
        try:
            with open(path, "rb") as fh:
                if fh.read(len(_SNAPSHOT_HEADER)) != _SNAPSHOT_HEADER:
                    raise ValueError(f"load: '{path}' is not a valid snapshot (bad header)")
                with np.load(fh, allow_pickle=False) as data:
                    arrays = {k: data[k] for k in data.files}
            meta = json.loads(arrays.pop("meta").tobytes())
        except (OSError, KeyError, zipfile.BadZipFile, json.JSONDecodeError) as err:
            raise ValueError(f"load: '{path}' is not a valid snapshot: {err}") from err
        required = {f"map_{k}" for k in _MAP_ARRAYS} | {
            "terrain", "food_volume", "food_density", "pher", "ants", "colonies", "traffic",
            "combat",
        }
        if missing := required - arrays.keys():
            raise ValueError(f"load: '{path}' is not a valid snapshot (missing {sorted(missing)})")
        restored = Simulation(meta["config"])  # validates the stored config like a fresh one
        restored._map = {"width": meta["width"], "height": meta["height"]}
        restored._map.update({k: arrays[f"map_{k}"] for k in _MAP_ARRAYS})
        restored._reset_state()
        restored._ready = True
        restored._tick = meta["tick"]
        restored._params = meta["params"]
        restored._rng.bit_generator.state = meta["rng"]
        restored._terrain = arrays["terrain"]
        restored._food_volume = arrays["food_volume"]
        restored._food_density = arrays["food_density"]
        restored._pher = arrays["pher"]
        restored._ants = arrays["ants"]
        restored._colonies = arrays["colonies"]
        restored._traffic = arrays["traffic"]
        restored._combat = arrays["combat"]
        self.__dict__.update(restored.__dict__)

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
        ant = (
            {
                k: self._ants[k][hit[0]].item()
                for k in ("id", "age", "colony", "species", "caste", "state", "health")
            }
            if len(hit)
            else None
        )
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

    def traffic(self):
        return self._ro(self._heatmap("traffic", self._traffic))

    def combat_map(self):
        return self._ro(self._heatmap("combat_map", self._combat))

    def _heatmap(self, name: str, layer: np.ndarray) -> np.ndarray:
        if not self._ready:
            raise RuntimeError(f"{name}: call initialize() first")
        if not self._heatmaps:
            raise RuntimeError(f"{name}: enable_heatmaps is not set")
        return layer

    def metrics(self) -> dict:
        s = self._n_species
        pop = np.bincount(self._ants["species"], minlength=s).astype(np.int64)
        zeros = lambda: np.zeros(s, np.int64)  # noqa: E731
        return {
            "tick": self._tick, "population": pop, "births": pop.copy(), "kills": zeros(),
            "deaths_combat": zeros(), "deaths_hazard": zeros(), "deaths_age": zeros(),
            "deaths_orphan": zeros(),
            "colonies_alive": np.bincount(self._colonies["species"], minlength=s).astype(np.int64),
            "deliveries": zeros(), "return_steps_sum": zeros(),
            "population_caste": np.pad(pop[:, None], ((0, 0), (0, MAX_CASTES - 1))),
            "food_total_volume": float(self._food_volume.sum()),
            "food_total_energy": float((self._food_volume * self._food_density).sum()),
        }
