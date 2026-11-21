"""Run the mill scenario with dedicated diagnostics artifacts (Step 0).

Usage:
  uv run python tools/run_mill_scenario.py --config configs/scenario_mill.json \
    --ticks 20000 --out artifacts/mill_baseline
"""

from __future__ import annotations

import argparse
import hashlib
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


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--config", default="configs/scenario_mill.json")
    ap.add_argument("--ticks", type=int, default=20000)
    ap.add_argument("--out", default="artifacts/mill_scenario")
    ap.add_argument("--food-distance", type=int, default=60)
    ap.add_argument("--food-cells", type=int, default=60)
    ap.add_argument("--mock", action="store_true")
    args = ap.parse_args(argv)

    cfg = load_config(args.config)
    cfg = build_mill_scenario_config(cfg)
    map_data = make_mill_scenario_map(
        width=cfg["world"]["width"],
        height=cfg["world"]["height"],
        hill_radius=cfg["colony"]["hill_radius"],
        species_id=0,
        food_distance=args.food_distance,
        food_cells=args.food_cells,
    )
    sim = load_sim(cfg, map_data, prefer_mock=args.mock)
    diag = MillDiagnostics(hill_radius=cfg["colony"]["hill_radius"], n_species=len(cfg["species"]))
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    # record initial state
    diag.maybe_record(0, sim)
    while (
        int(sim.tick) if not callable(getattr(sim, "tick", None)) else int(sim.tick())
    ) < args.ticks:
        tick = int(sim.tick) if not callable(getattr(sim, "tick", None)) else int(sim.tick())
        step = min(50, args.ticks - tick)
        sim.step(step)
        tick = int(sim.tick) if not callable(getattr(sim, "tick", None)) else int(sim.tick())
        diag.maybe_record(tick, sim)

    diag.export_csv(out / "mill_diagnostics.csv")
    diag.export_nest_food_profile(sim, out)
    mill_vals = [s.mill_index for s in diag.samples if s.mill_index is not None]
    mean_mill = sum(mill_vals) / len(mill_vals) if mill_vals else None
    stuck_searching = sum(s.stuck_searching for s in diag.samples)
    stuck_returning = sum(s.stuck_returning for s in diag.samples)
    stuck_carrying_food = sum(s.stuck_carrying_food for s in diag.samples)
    summary = {
        "engine": engine_kind(args.mock),
        "config_hash": config_hash(cfg),
        "ticks": int(sim.tick) if not callable(getattr(sim, "tick", None)) else int(sim.tick()),
        "map_stats": map_data.get("stats", {}),
        "metrics": {
            k: (v.tolist() if hasattr(v, "tolist") else v)
            for k, v in sim.metrics().items()
        },
        "mean_mill_index": mean_mill,
        "last_mill_index": next(
            (s.mill_index for s in reversed(diag.samples) if s.mill_index is not None),
            None,
        ),
        "last_saturation": {
            f"s{sp}_ch{ch}": v
            for (sp, ch), v in (
                diag.samples[-1].saturation.items() if diag.samples else []
            )
        },
        "stuck_searching": stuck_searching,
        "stuck_returning": stuck_returning,
        "stuck_carrying_food": stuck_carrying_food,
    }
    (out / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps({"out": str(out), "last_mill_index": summary["last_mill_index"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
