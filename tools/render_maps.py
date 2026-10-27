"""Render generated maps to PNG files (spec 13.2, P5 weeks 1-2 deliverable).

Usage: uv run python tools/render_maps.py --seeds 0-19 --size 512 --out maps/
"""
from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from formicae_ui.mapgen import generate_map  # noqa: E402
from formicae_ui.ui.renderer import FOOD_COLOR, TERRAIN_COLORS  # noqa: E402


def parse_seeds(text: str) -> list[int]:
    if "-" in text:
        lo, hi = (int(v) for v in text.split("-", 1))
        return list(range(lo, hi + 1))
    return [int(v) for v in text.split(",")]


def map_to_rgb(map_data: dict) -> np.ndarray:
    rgb = TERRAIN_COLORS[map_data["terrain"]].copy()
    rgb[map_data["food_volume"] > 0] = FOOD_COLOR
    return rgb


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--seeds", default="0-19", help="range '0-19' or list '1,5,7'")
    ap.add_argument("--size", type=int, default=512)
    ap.add_argument("--colonies", type=int, default=3)
    ap.add_argument("--out", default="maps")
    args = ap.parse_args()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    for seed in parse_seeds(args.seeds):
        md = generate_map(seed, args.size, args.size, args.colonies, [0, 1, 2])
        fig, ax = plt.subplots(figsize=(6, 6), dpi=100)
        ax.imshow(map_to_rgb(md), interpolation="nearest")
        for x, y, species in md["colonies"]:
            ax.plot(x, y, "o", ms=8, mfc="none", mec="red", mew=2)
            ax.annotate(f"s{species}", (x, y), color="red", xytext=(6, 6),
                        textcoords="offset points")
        s = md["stats"]
        ax.set_title(f"seed {seed} (effective {md['effective_seed']}): "
                     f"passable {s['passable_fraction']:.0%}, "
                     f"food {s['food_clusters_placed']}, corridors {s['corridors_carved']}",
                     fontsize=9)
        ax.set_axis_off()
        fig.tight_layout()
        fig.savefig(out / f"map_seed{seed:03d}.png")
        plt.close(fig)
        print(f"wrote {out / f'map_seed{seed:03d}.png'}")


if __name__ == "__main__":
    main()
