"""Metrics history, graphs and CSV export (spec section 10, interface I6). Owner: P5 (M4)."""
from __future__ import annotations

import csv
from pathlib import Path

import numpy as np

from formicae_ui.types import METRIC_KEYS_PER_SPECIES


class Analytics:
    """Records sim.metrics() every 10 ticks, draws graphs with Matplotlib's Agg backend (at most
    once per second) and exports the full history as CSV.

    CSV columns: tick, pop_s{i}, births_s{i}, kills_s{i}, deaths_combat_s{i}, deaths_hazard_s{i},
    deaths_age_s{i}, deaths_orphan_s{i}, colonies_alive_s{i}, energy_c{j}, food_total_energy.
    """

    def __init__(self, n_species: int, n_colonies: int):
        self.n_species = n_species
        self.n_colonies = n_colonies
        self._rows: list[list[float]] = []

    def record(self, metrics: dict, colonies: np.ndarray) -> None:
        """Store one sample (called every 10 ticks)."""
        row: list[float] = [int(metrics["tick"])]
        for key in METRIC_KEYS_PER_SPECIES:
            row.extend(float(v) for v in metrics[key])
        row.extend(float(e) for e in colonies["stored_energy"])
        row.append(float(metrics["food_total_energy"]))
        self._rows.append(row)

    def columns(self) -> list[str]:
        short = {"population": "pop"}
        cols = ["tick"]
        for key in METRIC_KEYS_PER_SPECIES:
            cols += [f"{short.get(key, key)}_s{i}" for i in range(self.n_species)]
        cols += [f"energy_c{j}" for j in range(self.n_colonies)]
        cols.append("food_total_energy")
        return cols

    def export_csv(self, path: str | Path) -> None:
        with open(path, "w", newline="", encoding="utf-8") as fh:
            writer = csv.writer(fh)
            writer.writerow(self.columns())
            writer.writerows(self._rows)

    def render(self, size: tuple[int, int]):
        """Return a pygame.Surface with the four graphs (population per species, stored energy per
        colony, combat deaths per 100 ticks per species, total food)."""
        raise NotImplementedError("TODO(P5): Matplotlib Agg figure -> pygame.Surface")
