"""Mill-mitigation diagnostics (Step 0): separate from core Analytics/UI contract.

Computes mill index, pheromone saturation, delivery throughput, and nest-food
profiles from simulation snapshots and writes dedicated CSV/artifacts.
"""

from __future__ import annotations

import csv
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

try:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
except Exception:  # pragma: no cover - plotting is best-effort in headless runs
    plt = None

from formicae_ui.types import AntState


def _hill_mask_shape(height: int, width: int, colonies: np.ndarray, radius: int) -> np.ndarray:
    mask = np.zeros((height, width), dtype=bool)
    for c in colonies:
        cx, cy = int(c["x"]), int(c["y"])
        x0, x1 = max(0, cx - radius), min(width, cx + radius + 1)
        y0, y1 = max(0, cy - radius), min(height, cy + radius + 1)
        mask[y0:y1, x0:x1] = True
    return mask


def _outside_hill_mask(ants: np.ndarray, colonies: np.ndarray, radius: int) -> np.ndarray:
    alive = ants["state"] != AntState.DEAD
    out = np.zeros(len(ants), dtype=bool)
    if not np.any(alive):
        return out
    idx = np.nonzero(alive)[0]
    ax = ants["x"][idx].astype(np.int32)
    ay = ants["y"][idx].astype(np.int32)
    ac = ants["colony"][idx].astype(np.int32)
    # colony footprint square around center
    cx = colonies["x"][ac].astype(np.int32)
    cy = colonies["y"][ac].astype(np.int32)
    outside = (np.abs(ax - cx) > radius) | (np.abs(ay - cy) > radius)
    out[idx] = outside
    return out


@dataclass
class MillSample:
    tick: int
    mill_index: float | None
    matched_ants: int
    saturation: dict[tuple[int, int], float]
    deliveries: list[int]
    population: list[int]
    deliveries_per_ant_1000: list[float]
    return_steps_sum: list[int]


def saturation_index(pheromones: np.ndarray) -> dict[tuple[int, int], float]:
    """Per (species, channel): count(p>=0.95)/count(p>0.01), 0 if denominator 0."""
    result: dict[tuple[int, int], float] = {}
    for s in range(pheromones.shape[0]):
        for ch in range(pheromones.shape[1]):
            plane = pheromones[s, ch]
            denom = int(np.count_nonzero(plane > 0.01))
            if denom == 0:
                result[(s, ch)] = 0.0
            else:
                numer = int(np.count_nonzero(plane >= 0.95))
                result[(s, ch)] = numer / denom
    return result


def sample_nest_food_profile(
    pheromones: np.ndarray, x0: int, y0: int, x1: int, y1: int, species: int = 0
) -> dict[str, np.ndarray]:
    """Sample HOME/FOOD pheromone values along a line from (x0,y0) to (x1,y1)."""
    n = max(abs(x1 - x0), abs(y1 - y0)) + 1
    xs = np.linspace(x0, x1, n).round().astype(int)
    ys = np.linspace(y0, y1, n).round().astype(int)
    h, w = pheromones.shape[2], pheromones.shape[3]
    xs = np.clip(xs, 0, w - 1)
    ys = np.clip(ys, 0, h - 1)
    dist = np.sqrt((xs - x0) ** 2 + (ys - y0) ** 2)
    home = pheromones[species, 0, ys, xs].astype(np.float32, copy=True)
    food = pheromones[species, 1, ys, xs].astype(np.float32, copy=True)
    return {"x": xs, "y": ys, "distance": dist.astype(np.float32), "home": home, "food": food}


class MillDiagnostics:
    def __init__(
        self,
        hill_radius: int,
        n_species: int,
        *,
        mill_every: int = 50,
        mill_window: int = 200,
        mill_move_threshold: float = 5.0,
        saturation_every: int = 10,
    ):
        self.hill_radius = hill_radius
        self.n_species = n_species
        self.mill_every = mill_every
        self.mill_window = mill_window
        self.mill_move_threshold = mill_move_threshold
        self.saturation_every = saturation_every
        self._pos_history: dict[int, dict[int, tuple[int, int]]] = {}
        self.samples: list[MillSample] = []

    def _snapshot_positions(
        self, ants: np.ndarray, colonies: np.ndarray
    ) -> dict[int, tuple[int, int]]:
        mask = _outside_hill_mask(ants, colonies, self.hill_radius)
        idx = np.nonzero(mask)[0]
        return {
            int(ants["id"][i]): (int(ants["x"][i]), int(ants["y"][i])) for i in idx
        }

    def maybe_record(self, tick: int, sim) -> MillSample | None:
        if tick % self.saturation_every != 0 and tick % self.mill_every != 0:
            return None
        ants = sim.ants()
        colonies = sim.colonies()
        metrics = sim.metrics()
        pher = sim.pheromones() if tick % self.saturation_every == 0 else None
        sat = saturation_index(pher) if pher is not None else {}
        mill_index = None
        matched = 0
        if tick % self.mill_every == 0:
            pos = self._snapshot_positions(ants, colonies)
            self._pos_history[tick] = pos
            old = self._pos_history.get(tick - self.mill_window)
            if old is not None:
                ids = set(pos).intersection(old)
                matched = len(ids)
                if matched:
                    stuck = 0
                    thr2 = self.mill_move_threshold * self.mill_move_threshold
                    for aid in ids:
                        dx = pos[aid][0] - old[aid][0]
                        dy = pos[aid][1] - old[aid][1]
                        if dx * dx + dy * dy < thr2:
                            stuck += 1
                    mill_index = stuck / matched
                else:
                    mill_index = 0.0
            # keep bounded history
            cutoff = tick - self.mill_window - self.mill_every
            for t in [t for t in self._pos_history if t < cutoff]:
                del self._pos_history[t]
        deliveries = [
            int(x) for x in np.asarray(metrics["deliveries"], dtype=np.int64)
        ]
        pops = [int(x) for x in np.asarray(metrics["population"], dtype=np.int64)]
        ret_steps = [
            int(x) for x in np.asarray(metrics["return_steps_sum"], dtype=np.int64)
        ]
        dpa = []
        for d, p in zip(deliveries, pops, strict=False):
            denom = max(p, 1)
            dpa.append((d / denom) * 1000.0)
        sample = MillSample(
            tick, mill_index, matched, sat, deliveries, pops, dpa, ret_steps
        )
        self.samples.append(sample)
        return sample

    def export_csv(self, path: str | Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        # union of saturation keys seen
        sat_keys = sorted({k for s in self.samples for k in s.saturation.keys()})
        header = [
            "tick",
            "mill_index",
            "matched_ants",
        ]
        for i in range(self.n_species):
            header += [
                f"deliveries_s{i}",
                f"population_s{i}",
                f"deliveries_per_ant_1000_s{i}",
                f"return_steps_sum_s{i}",
            ]
        for sp, ch in sat_keys:
            header.append(f"saturation_s{sp}_ch{ch}")
        with open(path, "w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(header)
            for s in self.samples:
                row: list[Any] = [
                    s.tick,
                    "" if s.mill_index is None else s.mill_index,
                    s.matched_ants,
                ]
                for i in range(self.n_species):
                    row += [
                        s.deliveries[i],
                        s.population[i],
                        s.deliveries_per_ant_1000[i],
                        s.return_steps_sum[i],
                    ]
                for k in sat_keys:
                    row.append(s.saturation.get(k, ""))
                w.writerow(row)

    def export_nest_food_profile(
        self,
        sim,
        out_dir: str | Path,
        *,
        species: int = 0,
        tick: int | None = None,
    ) -> tuple[Path, Path | None]:
        colonies = sim.colonies()
        ants_food = np.argwhere(sim.food_volume() > 0)
        if len(colonies) == 0:
            raise ValueError("no colonies")
        cx, cy = int(colonies[0]["x"]), int(colonies[0]["y"])
        if len(ants_food):
            # centroid of food cluster
            fy, fx = ants_food.mean(axis=0)
            fx, fy = int(round(fx)), int(round(fy))
        else:
            fx, fy = cx + 60, cy
        profile = sample_nest_food_profile(
            sim.pheromones(), cx, cy, fx, fy, species=species
        )
        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        tlabel = (
            (int(sim.tick) if not callable(getattr(sim, "tick", None)) else int(sim.tick()))
            if tick is None
            else tick
        )
        csv_path = out_dir / f"nest_food_profile_t{tlabel}.csv"
        with open(csv_path, "w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(["x", "y", "distance", "home", "food"])
            for i in range(len(profile["distance"])):
                w.writerow([
                    int(profile["x"][i]),
                    int(profile["y"][i]),
                    float(profile["distance"][i]),
                    float(profile["home"][i]),
                    float(profile["food"][i]),
                ])
        img_path = None
        if plt is not None:
            img_path = out_dir / f"nest_food_profile_t{tlabel}.png"
            fig, ax = plt.subplots(figsize=(6, 3), dpi=120)
            ax.plot(profile["distance"], profile["home"], label="HOME", color="#2ca02c")
            ax.plot(profile["distance"], profile["food"], label="FOOD", color="#d62728")
            ax.set_xlabel("Distance from nest (cells)")
            ax.set_ylabel("Pheromone")
            ax.set_title(f"Nest-food profile (tick {tlabel})")
            ax.set_ylim(0, 1.05)
            ax.legend()
            fig.tight_layout()
            fig.savefig(img_path)
            plt.close(fig)
        return csv_path, img_path


def make_mill_scenario_map(
    *,
    width: int = 256,
    height: int = 256,
    hill_radius: int = 2,
    species_id: int = 0,
    food_distance: int = 60,
    food_cells: int = 60,
    food_volume: float = 120.0,
    food_density: float = 30.0,
    direction: tuple[int, int] = (1, 0),
) -> dict[str, Any]:
    """Controlled deterministic MapData: one hill and one compact food cluster."""
    terrain = np.zeros((height, width), dtype=np.uint8)  # GRASS
    fv = np.zeros((height, width), dtype=np.float32)
    fd = np.zeros((height, width), dtype=np.float32)
    cx, cy = width // 2, height // 2
    dx, dy = direction
    norm = math.hypot(dx, dy) or 1.0
    fx = int(round(cx + dx / norm * food_distance))
    fy = int(round(cy + dy / norm * food_distance))
    fx = max(0, min(width - 1, fx))
    fy = max(0, min(height - 1, fy))
    colonies = np.array([[cx, cy, species_id]], dtype=np.int32)
    # place ~food_cells in a disk around (fx,fy)
    r = max(1, int(math.ceil(math.sqrt(food_cells / math.pi))))
    placed = 0
    for yy in range(fy - r - 1, fy + r + 2):
        for xx in range(fx - r - 1, fx + r + 2):
            if not (0 <= xx < width and 0 <= yy < height):
                continue
            if abs(xx - cx) <= hill_radius and abs(yy - cy) <= hill_radius:
                continue
            if (xx - fx) ** 2 + (yy - fy) ** 2 <= r * r and placed < food_cells:
                fv[yy, xx] = food_volume
                fd[yy, xx] = food_density
                placed += 1
    dist = math.hypot(fx - cx, fy - cy)
    return {
        "width": width,
        "height": height,
        "terrain": terrain,
        "food_volume": fv,
        "food_density": fd,
        "colonies": colonies,
        "effective_seed": 0,
        "stats": {
            "hill_center": (cx, cy),
            "food_center": (fx, fy),
            "food_distance": dist,
            "food_cells_placed": placed,
        },
    }


def build_mill_scenario_config(base_cfg: dict[str, Any]) -> dict[str, Any]:
    """Return a config dict for deterministic 256² single-colony mill scenario.

    Preserves scenario-specific parameters from `base_cfg` (seeds, colony economy,
    species, food/analytics settings) while enforcing 256² single-colony world and
    a single species for focused diagnostics.
    """
    import copy

    cfg = copy.deepcopy(base_cfg)
    cfg["world"] = {"width": 256, "height": 256, "n_colonies": 1}
    cfg.setdefault("seeds", {}).setdefault("sim_seed", 7)
    if len(cfg.get("species", [])) > 1:
        cfg["species"] = [cfg["species"][0]]
    cfg.setdefault("analytics", {}).setdefault("sample_every_ticks", 10)
    cfg.setdefault("food", {})
    cfg["food"].setdefault("spawn_prob", 0.0)
    cfg["food"].setdefault("spawn_interval", 10000)
    cfg["food"].setdefault("max_food_cells", 0)
    return cfg
