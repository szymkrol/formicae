"""Run the mill scenario with dedicated diagnostics artifacts (Step 0).

Usage:
  uv run python tools/run_mill_scenario.py --config configs/scenario_mill.json \
    --ticks 20000 --out artifacts/mill_baseline
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from formicae_ui.analytics.mill_diagnostics import (
    MillDiagnostics,
    build_mill_scenario_config,
    make_mill_scenario_map,
)
from formicae_ui.config import load_config


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
    summary = {
        "ticks": int(sim.tick) if not callable(getattr(sim, "tick", None)) else int(sim.tick()),
        "map_stats": map_data.get("stats", {}),
        "metrics": {
            k: (v.tolist() if hasattr(v, "tolist") else v)
            for k, v in sim.metrics().items()
        },
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
    }
    (out / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps({"out": str(out), "last_mill_index": summary["last_mill_index"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
