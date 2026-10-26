"""Command line entry point: python -m formicae_ui --config configs/default.json --map-seed 42"""

from __future__ import annotations

import argparse

from formicae_ui.config import load_config
from formicae_ui.mapgen import MapGenParams, generate_map


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="formicae_ui", description="Ant colony simulation")
    ap.add_argument("--config", default="configs/default.json")
    ap.add_argument("--map-seed", type=int, default=42)
    ap.add_argument("--sim-seed", type=int, default=None, help="overrides seeds.sim_seed")
    ap.add_argument(
        "--mock", action="store_true", help="use formicae_mock instead of the C++ engine"
    )
    ap.add_argument("--frames", type=int, default=None, help="exit after N frames (smoke test)")
    args = ap.parse_args(argv)

    cfg = load_config(args.config)
    if args.sim_seed is not None:
        cfg.setdefault("seeds", {})["sim_seed"] = args.sim_seed

    if args.mock:
        import formicae_mock as formicae
    else:
        import formicae  # compiled module, see CMakeLists.txt

    world = cfg.get("world", {})
    species_ids = list(range(len(cfg["species"])))
    map_data = generate_map(
        seed=args.map_seed,
        width=world.get("width", 512),
        height=world.get("height", 512),
        n_colonies=world.get("n_colonies", 3),
        species_ids=species_ids,
        params=MapGenParams(),
    )
    sim = formicae.Simulation(cfg)
    sim.initialize(map_data)

    from formicae_ui.ui.app import App  # imports pygame lazily

    App(sim, cfg, map_data).run(max_frames=args.frames)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
