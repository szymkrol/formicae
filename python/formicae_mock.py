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
API_VERSION = 2
_PARAMS = {
    "decay_scale": (0.0, 10.0),
    "diffusion": (0.0, 0.2),
    "food_spawn_prob": (0.0, 1.0),
    "food_spawn_interval": (1, 10000),
    "grad_beta": (0.0, 8.0),
    "nav_scale": (0.0, 4.0),
    "noise_damp_scale": (0.0, 2.0),
}
_DIRS = np.array([(0, -1), (1, 0), (0, 1), (-1, 0)], dtype=np.int16)
# Snapshot file: "ANTS" + little-endian u32 format version, then an .npz archive (no pickles).
_SNAPSHOT_HEADER = b"ANTS" + (2).to_bytes(4, "little")
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

    def _species(self, idx: int) -> dict:
        return self._config.get("species", [{}])[idx]

    def _pher_params(self) -> dict:
        p = self._config.get("pheromone", {})
        return {
            "decay": np.array(p.get("decay", [0.0015, 0.001, 0.015]), dtype=np.float32),
            "decay_scale": float(p.get("decay_scale", 1.0)),
            "diffusion": float(p.get("diffusion", 0.03)),
            "cutoff": float(p.get("cutoff", 0.001)),
            "tau_cap": float(p.get("tau_cap", 1.0)),
            "epsilon": float(p.get("epsilon", 0.05)),
            "grad_beta": float(p.get("grad_beta", 2.0)),
            "food_density_ref": float(p.get("food_density_ref", 50.0)),
        }

    def _deposit(self, species: int, channel: int, y: int, x: int, amount: float) -> None:
        if amount <= 0:
            return
        p = self._pher_params()
        cap = 1.0 if channel == 2 else float(p["tau_cap"])
        cur = float(self._pher[species, channel, y, x])
        if cap < 1.0 and channel != 2:
            cur = min(1.0, cur + amount * max(0.0, 1.0 - cur / cap))
        else:
            cur = min(1.0, cur + amount)
        self._pher[species, channel, y, x] = cur

    def _on_friendly_hill(self, colony_idx: int, species: int, x: int, y: int) -> bool:
        colony = self._colonies[colony_idx]
        return (
            bool(colony["alive"])
            and int(colony["species"]) == species
            and abs(x - int(colony["x"])) <= 2
            and abs(y - int(colony["y"])) <= 2
        )

    def _is_lost(self, ant, cfg: dict) -> bool:
        lost_mult = float(cfg.get("lost_mult", 1.0))
        if lost_mult <= 0:
            return False
        searching = int(ant["state"]) == AntState.SEARCHING
        trail_len = float(cfg.get("trail_len_home" if searching else "trail_len_food", 600))
        return float(ant["trail_age"]) >= lost_mult * trail_len

    def _has_food_memory(self, ant) -> bool:
        return int(ant["food_x"]) >= 0 and int(ant["food_y"]) >= 0

    def _near_remembered_food(self, ant, x: int, y: int) -> bool:
        return self._has_food_memory(ant) and max(
            abs(x - int(ant["food_x"])),
            abs(y - int(ant["food_y"])),
        ) <= 1

    def _erase_local_food(self, species: int, x: int, y: int, cfg: dict, ant_i: int) -> None:
        factor = min(1.0, max(0.0, float(cfg.get("food_erase_factor", 0.3))))
        self._pher[species, 1, y, x] *= factor
        explore_ticks = int(cfg.get("explore_ticks", 40))
        self._ants["explore_timer"][ant_i] = max(
            int(self._ants["explore_timer"][ant_i]),
            explore_ticks,
        )

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
        self._ants["food_x"] = -1
        self._ants["food_y"] = -1
        self._ants["explore_timer"] = 0
        self._ants["fidelity_fail"] = 0
        self._metrics = self._empty_metrics()

    def _empty_metrics(self) -> dict:
        s = self._n_species
        zeros = lambda: np.zeros(s, np.int64)  # noqa: E731
        return {
            "tick": self._tick,
            "population": zeros(),
            "births": zeros(),
            "kills": zeros(),
            "deaths_combat": zeros(),
            "deaths_hazard": zeros(),
            "deaths_age": zeros(),
            "deaths_orphan": zeros(),
            "colonies_alive": np.bincount(
                self._colonies[self._colonies["alive"] != 0]["species"],
                minlength=s,
            ).astype(np.int64),
            "deliveries": zeros(),
            "return_steps_sum": zeros(),
            "population_caste": np.zeros((s, MAX_CASTES), np.int64),
            "food_total_volume": float(self._food_volume.sum()),
            "food_total_energy": float((self._food_volume * self._food_density).sum()),
        }

    def _refresh_metrics(self) -> None:
        s = self._n_species
        pop = np.bincount(self._ants["species"], minlength=s).astype(np.int64)
        self._metrics["tick"] = self._tick
        self._metrics["population"] = pop
        self._metrics["colonies_alive"] = np.bincount(
            self._colonies[self._colonies["alive"] != 0]["species"], minlength=s
        ).astype(np.int64)
        caste = np.zeros((s, MAX_CASTES), np.int64)
        caste[:, 0] = pop
        self._metrics["population_caste"] = caste
        self._metrics["food_total_volume"] = float(self._food_volume.sum())
        self._metrics["food_total_energy"] = float((self._food_volume * self._food_density).sum())

    def step(self, n: int = 1) -> int:
        if not self._ready:
            raise RuntimeError("step: call initialize() first")
        if not 1 <= n <= 10_000:
            raise ValueError("step: n must be in 1..10000")
        h, w = self._terrain.shape
        pp = self._pher_params()
        decay = np.clip(1.0 - pp["decay"] * pp["decay_scale"], 0.0, 1.0).astype(np.float32)
        for _ in range(n):
            self._tick += 1
            for ch in range(NUM_CHANNELS):
                self._pher[:, ch] *= decay[ch]
            self._pher[self._pher < pp["cutoff"]] = 0.0
            for ant_i in range(len(self._ants)):
                a = self._ants[ant_i]
                if a["state"] == AntState.DEAD:
                    continue
                sp = int(a["species"])
                cfg = self._species(sp)
                x, y = int(a["x"]), int(a["y"])
                if a["explore_timer"] > 0:
                    self._ants["explore_timer"][ant_i] -= 1
                self._ants["age"][ant_i] += 1
                colony_idx = int(a["colony"])
                colony = self._colonies[colony_idx]
                cx, cy = int(colony["x"]), int(colony["y"])
                searching = int(a["state"]) == AntState.SEARCHING
                returning = int(a["state"]) == AntState.RETURNING

                if searching:
                    if self._on_friendly_hill(colony_idx, sp, x, y):
                        self._ants["trail_age"][ant_i] = 0
                    if (
                        self._has_food_memory(a)
                        and self._ants["explore_timer"][ant_i] == 0
                        and self._is_lost(a, cfg)
                    ):
                        self._ants["food_x"][ant_i] = -1
                        self._ants["food_y"][ant_i] = -1
                        self._ants["explore_timer"][ant_i] = int(cfg.get("explore_ticks", 40))
                        self._ants["fidelity_fail"][ant_i] = min(255, int(a["fidelity_fail"]) + 1)
                    goal_before = bool(
                        int(self._ants["state"][ant_i]) == AntState.SEARCHING
                        and self._ants["carried_volume"][ant_i] <= 0
                        and self._has_food_memory(self._ants[ant_i])
                        and self._ants["explore_timer"][ant_i] == 0
                    )
                    if self._food_volume[y, x] > 0:
                        take = min(
                            float(cfg.get("carry_capacity", 2)),
                            float(self._food_volume[y, x]),
                        )
                        self._ants["carried_volume"][ant_i] = take
                        self._ants["carried_density"][ant_i] = float(self._food_density[y, x])
                        self._food_volume[y, x] -= take
                        if self._food_volume[y, x] <= 0:
                            self._food_density[y, x] = 0
                        self._ants["state"][ant_i] = AntState.RETURNING
                        self._ants["trail_age"][ant_i] = 0
                        self._ants["food_x"][ant_i] = x
                        self._ants["food_y"][ant_i] = y
                        self._ants["explore_timer"][ant_i] = 0
                        self._ants["fidelity_fail"][ant_i] = 0
                        searching = False
                        returning = True
                    elif goal_before and self._near_remembered_food(self._ants[ant_i], x, y):
                        self._ants["food_x"][ant_i] = -1
                        self._ants["food_y"][ant_i] = -1
                        self._ants["explore_timer"][ant_i] = int(cfg.get("explore_ticks", 40))
                        self._ants["fidelity_fail"][ant_i] = min(
                            255,
                            int(self._ants["fidelity_fail"][ant_i]) + 1,
                        )
                        self._erase_local_food(sp, x, y, cfg, ant_i)
                elif returning and self._on_friendly_hill(colony_idx, sp, x, y):
                    self._metrics["deliveries"][sp] += 1
                    self._metrics["return_steps_sum"][sp] += int(a["trail_age"])
                    self._ants["carried_volume"][ant_i] = 0
                    self._ants["carried_density"][ant_i] = 0
                    self._ants["state"][ant_i] = AntState.SEARCHING
                    self._ants["trail_age"][ant_i] = 0
                    if not self._has_food_memory(self._ants[ant_i]) or self._rng.random() >= float(
                        cfg.get("p_fid", 0.95)
                    ):
                        self._ants["food_x"][ant_i] = -1
                        self._ants["food_y"][ant_i] = -1
                    searching = True
                    returning = False

                a = self._ants[ant_i]
                searching = int(a["state"]) == AntState.SEARCHING
                returning = int(a["state"]) == AntState.RETURNING
                goal_mode = bool(
                    searching
                    and a["carried_volume"] <= 0
                    and self._has_food_memory(a)
                    and int(a["explore_timer"]) == 0
                )

                dirs = []
                for dx, dy in ((0, -1), (1, 0), (0, 1), (-1, 0)):
                    nx, ny = x + dx, y + dy
                    if 1 <= nx < w - 1 and 1 <= ny < h - 1 and self._terrain[ny, nx] not in (4, 5):
                        dirs.append((dx, dy))
                moved = False
                if dirs:
                    weights = []
                    for dx, dy in dirs:
                        nx, ny = x + dx, y + dy
                        wgt = 1.0 + pp["epsilon"]
                        if searching and int(a["explore_timer"]) == 0 and not goal_mode:
                            wgt += float(self._pher[sp, 1, ny, nx])
                        if returning or (searching and int(a["explore_timer"]) > 0):
                            wgt += 0.2 * float(self._pher[sp, 0, ny, nx])
                        if goal_mode:
                            gx, gy = int(a["food_x"]) - x, int(a["food_y"]) - y
                            gd = (gx * gx + gy * gy) ** 0.5 or 1.0
                            align = (gx * dx + gy * dy) / gd
                            wgt *= max(
                                0.3,
                                min(3.0, 1.0 + float(cfg.get("goal_beta", 2.0)) * align),
                            )
                        if returning:
                            hx, hy = cx - x, cy - y
                            hd = (hx * hx + hy * hy) ** 0.5 or 1.0
                            wgt *= 1.0 + 0.8 * ((hx * dx + hy * dy) / hd)
                        weights.append(max(0.001, wgt))
                    weights = np.array(weights, dtype=np.float64)
                    weights /= weights.sum()
                    dx, dy = dirs[int(self._rng.choice(len(dirs), p=weights))]
                    nx, ny = x + dx, y + dy
                    self._ants["x"][ant_i] = nx
                    self._ants["y"][ant_i] = ny
                    self._ants["trail_age"][ant_i] = min(
                        65535,
                        int(self._ants["trail_age"][ant_i]) + 1,
                    )
                    if self._heatmaps:
                        self._traffic[ny, nx] += 1

                    trail_age = int(self._ants["trail_age"][ant_i])
                    if returning and self._has_food_memory(self._ants[ant_i]):
                        trail_len = max(1.0, float(cfg.get("trail_len_food", 600)))
                        fade = max(0.0, 1.0 - trail_age / trail_len)
                        amount = float(cfg.get("a_food", 0.18)) * fade
                        food_density_ref = max(1e-6, float(pp.get("food_density_ref", 50.0)))
                        amount *= min(
                            1.0,
                            float(self._ants["carried_density"][ant_i]) / food_density_ref,
                        )
                        self._deposit(sp, 1, ny, nx, amount)
                    elif bool(cfg.get("deposit_home_while_searching", True)):
                        trail_len = max(1.0, float(cfg.get("trail_len_home", 600)))
                        fade = max(0.0, 1.0 - trail_age / trail_len)
                        self._deposit(sp, 0, ny, nx, float(cfg.get("a_home", 0.06)) * fade)
                    x, y = nx, ny
                    moved = True

                if (
                    searching
                    and moved
                    and int(self._ants["state"][ant_i]) == AntState.SEARCHING
                    and self._food_volume[y, x] <= 0
                ):
                    if goal_mode and self._near_remembered_food(self._ants[ant_i], x, y):
                        self._ants["food_x"][ant_i] = -1
                        self._ants["food_y"][ant_i] = -1
                        self._ants["fidelity_fail"][ant_i] = min(
                            255,
                            int(self._ants["fidelity_fail"][ant_i]) + 1,
                        )
                        self._ants["explore_timer"][ant_i] = int(cfg.get("explore_ticks", 40))
                        self._erase_local_food(sp, x, y, cfg, ant_i)
                    elif (
                        int(self._ants["explore_timer"][ant_i]) == 0
                        and not self._on_friendly_hill(colony_idx, sp, x, y)
                    ):
                        cur = float(self._pher[sp, 1, y, x])
                        if cur >= float(cfg.get("food_erase_tau", 0.1)):
                            nbr = [cur]
                            has_food_nbr = self._food_volume[y, x] > 0
                            for ddx, ddy in ((0, -1), (1, 0), (0, 1), (-1, 0)):
                                nnx, nny = x + ddx, y + ddy
                                if 0 <= nnx < w and 0 <= nny < h:
                                    nbr.append(float(self._pher[sp, 1, nny, nnx]))
                                    has_food_nbr = has_food_nbr or self._food_volume[nny, nnx] > 0
                            if (not has_food_nbr) and max(nbr) - cur <= float(
                                cfg.get("food_erase_delta", 0.02)
                            ):
                                self._erase_local_food(sp, x, y, cfg, ant_i)
            self._refresh_metrics()
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
        for k, v in self._metrics.items():
            arrays[f"metric_{k}"] = np.asarray(v)
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
        restored._metrics = restored._empty_metrics()
        for key in restored._metrics:
            name = f"metric_{key}"
            if name in arrays:
                val = arrays[name]
                if np.isscalar(restored._metrics[key]):
                    restored._metrics[key] = val.item() if hasattr(val, "item") else val
                else:
                    restored._metrics[key] = np.array(val)
        restored._refresh_metrics()
        if restored._ants.dtype != ANT_DTYPE:
            raise ValueError(
                "load: incompatible ant layout "
                f"{restored._ants.dtype.itemsize}B; expected 44B (API_VERSION 2)"
            )
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
        self._refresh_metrics()
        out = {k: (v.copy() if isinstance(v, np.ndarray) else v) for k, v in self._metrics.items()}
        out["tick"] = self._tick
        return out
