"""Parameter sweep for mill mitigation Steps 1-2.

Builds one Simulation per run and records diagnostics summary metrics.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import itertools
import json
from pathlib import Path
from typing import Any

from formicae_ui.analytics.mill_diagnostics import (
    MillDiagnostics,
    build_mill_scenario_config,
    make_mill_scenario_map,
)
from formicae_ui.config import load_config

SWEEP_CONFIG_KEYS = (
    "seeds.sim_seed",
    "pheromone.decay_scale",
    "species.0.a_food",
    "species.0.a_home",
    "species.0.trail_len_food",
    "species.0.trail_len_home",
    "species.0.deposit_home_while_searching",
    "pheromone.tau_cap",
    "species.0.explore_timer_max",
    "species.0.memory_radius",
    "species.0.goal_max_distance",
)


def load_sim(cfg: dict, map_data: dict, prefer_mock: bool = False):
    if prefer_mock:
        import formicae_mock as formicae
    else:
        try:
            import formicae  # type: ignore
        except Exception:
            import formicae_mock as formicae
    sim = formicae.Simulation(cfg)
    sim.initialize(map_data)
    return sim


def _nav_get(d: dict, dotted: str):
    cur: Any = d
    for part in dotted.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return None
        cur = cur[part]
    return cur


def config_hash(cfg: dict) -> str:
    h = hashlib.sha256()
    for key in SWEEP_CONFIG_KEYS:
        h.update(key.encode())
        h.update(repr(_nav_get(cfg, key)).encode())
    return h.hexdigest()[:16]


def engine_kind(prefer_mock: bool) -> str:
    return "mock" if prefer_mock else "c++"


def run_one(cfg: dict, map_data: dict, ticks: int, prefer_mock: bool = False) -> dict:
    sim = load_sim(cfg, map_data, prefer_mock=prefer_mock)
    diag = MillDiagnostics(hill_radius=cfg["colony"]["hill_radius"], n_species=len(cfg["species"]))
    diag.maybe_record(0, sim)
    while True:
        tick = sim.tick if not callable(sim.tick) else sim.tick()
        tick = int(tick)
        if tick >= ticks:
            break
        sim.step(min(50, ticks - tick))
        tick = sim.tick if not callable(sim.tick) else sim.tick()
        diag.maybe_record(int(tick), sim)
    m = sim.metrics()
    deliveries = [int(x) for x in m["deliveries"]]
    pops = [int(x) for x in m["population"]]
    dpa = [((d / max(p, 1)) * 1000.0) for d, p in zip(deliveries, pops, strict=False)]
    mill_vals = [s.mill_index for s in diag.samples if s.mill_index is not None]
    sat_vals = [
        max(s.saturation.values()) if s.saturation else 0.0
        for s in diag.samples
        if s.saturation
    ]
    stuck_searching = sum(s.stuck_searching for s in diag.samples)
    stuck_returning = sum(s.stuck_returning for s in diag.samples)
    stuck_carrying_food = sum(s.stuck_carrying_food for s in diag.samples)
    return {
        "deliveries": deliveries,
        "deliveries_per_ant_1000": dpa,
        "final_population": pops,
        "food_total_energy": float(m["food_total_energy"]),
        "mean_mill_index": (sum(mill_vals) / len(mill_vals)) if mill_vals else None,
        "last_mill_index": (mill_vals[-1] if mill_vals else None),
        "max_saturation_index": (max(sat_vals) if sat_vals else 0.0),
        "last_saturation_index": (sat_vals[-1] if sat_vals else 0.0),
        "stuck_searching": stuck_searching,
        "stuck_returning": stuck_returning,
        "stuck_carrying_food": stuck_carrying_food,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--config", default="configs/scenario_mill.json")
    ap.add_argument("--ticks", type=int, default=20000)
    ap.add_argument("--seeds", default="1,2,3")
    ap.add_argument("--out", default="artifacts/mill_sweep")
    ap.add_argument("--food-distance", type=int, default=60)
    ap.add_argument("--food-cells", type=int, default=60)
    ap.add_argument("--mock", action="store_true")
    ap.add_argument("--include-extra-trails", action="store_true")
    args = ap.parse_args(argv)

    base_cfg = load_config(args.config)
    seeds = [int(s.strip()) for s in args.seeds.split(",") if s.strip()]
    a_food_vals = [0.18, 0.09, 0.045, 0.03, 0.015]
    decay_scales = [1.0, 2.0]
    trail_vals = [600, 300, 200]
    if args.include_extra_trails:
        trail_vals = sorted(set(trail_vals + [150, 250, 350]))

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    rows = []
    for a_food, decay_scale, trail_len, seed in itertools.product(
        a_food_vals, decay_scales, trail_vals, seeds
    ):
        cfg = build_mill_scenario_config(base_cfg)
        cfg.setdefault("seeds", {})["sim_seed"] = seed
        cfg.setdefault("pheromone", {})["decay_scale"] = decay_scale
        sp = cfg["species"][0]
        sp["a_food"] = a_food
        sp["a_home"] = a_food / 3.0
        sp["trail_len_food"] = trail_len
        sp["trail_len_home"] = trail_len
        map_data = make_mill_scenario_map(
            width=cfg["world"]["width"],
            height=cfg["world"]["height"],
            hill_radius=cfg["colony"]["hill_radius"],
            species_id=0,
            food_distance=args.food_distance,
            food_cells=args.food_cells,
        )
        result = run_one(cfg, map_data, args.ticks, prefer_mock=args.mock)
        row = {
            "engine": engine_kind(args.mock),
            "config_hash": config_hash(cfg),
            "a_food": a_food,
            "a_home": a_food / 3.0,
            "decay_scale": decay_scale,
            "trail_len": trail_len,
            "seed": seed,
            "food_distance": args.food_distance,
            **result,
        }
        rows.append(row)
        print(json.dumps({
            "done": len(rows),
            "a_food": a_food,
            "decay_scale": decay_scale,
            "trail_len": trail_len,
            "seed": seed,
            "mean_mill": row["mean_mill_index"],
            "max_sat": row["max_saturation_index"],
        }))

    json_path = out / "sweep_results.json"
    json_path.write_text(json.dumps(rows, indent=2), encoding="utf-8")
    csv_path = out / "sweep_results.csv"
    if rows:
        keys = list(rows[0].keys())
        with open(csv_path, "w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=keys)
            w.writeheader()
            for r in rows:
                w.writerow(r)
    print(json.dumps({"out": str(out), "runs": len(rows)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
