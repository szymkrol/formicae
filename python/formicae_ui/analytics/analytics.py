"""Metrics history, graphs and CSV export (spec section 10, interface I6). Owner: P5 (M4)."""
from __future__ import annotations

import csv
from pathlib import Path

import numpy as np

from formicae_ui.types import METRIC_KEYS_PER_SPECIES
from formicae_ui.ui.renderer import SPECIES_COLORS

INITIAL_CAPACITY = 1024
COMBAT_WINDOW_TICKS = 100
DEATH_CAUSES = ("combat", "hazard", "age", "orphan")
_SHORT_NAMES = {"population": "pop"}
_FOOD_LINE_COLOR = "#b08a10"


class Analytics:
    """Records sim.metrics() every 10 ticks, draws graphs with Matplotlib's Agg backend (at most
    once per second) and exports the full history as CSV.

    The history is a preallocated float64 array that doubles its capacity when full, so a long run
    keeps every sample for the CSV without per-sample allocation.

    CSV columns: tick, pop_s{i}, births_s{i}, kills_s{i}, deaths_combat_s{i}, deaths_hazard_s{i},
    deaths_age_s{i}, deaths_orphan_s{i}, colonies_alive_s{i}, energy_c{j}, food_total_energy.
    """

    def __init__(self, n_species: int, n_colonies: int):
        self.n_species = n_species
        self.n_colonies = n_colonies
        self._columns, self._blocks = self._build_columns()
        self._colony_species = np.zeros(n_colonies, dtype=np.intp)
        self._data = np.zeros((INITIAL_CAPACITY, len(self._columns)), dtype=np.float64)
        self._n = 0

    # ---- recording ----------------------------------------------------------------------------
    def record(self, metrics: dict, colonies: np.ndarray) -> None:
        """Store one sample (called every 10 ticks)."""
        if self._n == len(self._data):
            grown = np.zeros((2 * len(self._data), self._data.shape[1]), dtype=np.float64)
            grown[: self._n] = self._data
            self._data = grown
        row = self._data[self._n]
        row[0] = int(metrics["tick"])
        col = 1
        for key in METRIC_KEYS_PER_SPECIES:
            row[col : col + self.n_species] = np.asarray(metrics[key], dtype=np.float64)
            col += self.n_species
        row[col : col + self.n_colonies] = np.asarray(colonies["stored_energy"], dtype=np.float64)
        self._colony_species[:] = np.asarray(colonies["species"], dtype=np.intp)
        row[-1] = float(metrics["food_total_energy"])
        self._n += 1

    def clear(self) -> None:
        """Drop the history, e.g. after the simulation was reset."""
        self._n = 0

    def __len__(self) -> int:
        return self._n

    # ---- access -------------------------------------------------------------------------------
    def columns(self) -> list[str]:
        return list(self._columns)

    def history(self) -> np.ndarray:
        """Read-only view of the recorded samples, shape [n_samples, n_columns]."""
        view = self._data[: self._n]
        view.flags.writeable = False
        return view

    def series(self, key: str) -> np.ndarray:
        """Per-species (or per-colony for `energy`) block of the history, shape [n_samples, k].

        `key` is a metric name of METRIC_KEYS_PER_SPECIES, `energy` or `food_total_energy`.
        """
        return self._data[: self._n, self._blocks[key]]

    def ticks(self) -> np.ndarray:
        return self._data[: self._n, 0]

    def casualty_rates(self) -> dict[str, np.ndarray]:
        """Deaths per tick over each sampling window, split by cause (spec section 10).

        Returns {cause: float64 [n_samples, S]}; the first sample has rate 0.
        """
        ticks = self.ticks()
        dt = np.diff(ticks, prepend=ticks[:1])
        dt[dt <= 0] = 1.0
        rates = {}
        for cause in DEATH_CAUSES:
            deaths = self.series(f"deaths_{cause}")
            delta = np.diff(deaths, axis=0, prepend=deaths[:1])
            rates[cause] = delta / dt[:, None]
        return rates

    def combat_deaths_per_window(self, window: int = COMBAT_WINDOW_TICKS) -> np.ndarray:
        """Rolling combat deaths per `window` ticks per species, float64 [n_samples, S]."""
        ticks = self.ticks()
        deaths = self.series("deaths_combat")
        if self._n == 0:
            return deaths
        start = np.searchsorted(ticks, ticks - window, side="left")
        span = ticks - ticks[start]
        span[span <= 0] = 1.0
        return (deaths - deaths[start]) * (window / span)[:, None]

    # ---- output -------------------------------------------------------------------------------
    def export_csv(self, path: str | Path) -> None:
        with open(path, "w", newline="", encoding="utf-8") as fh:
            writer = csv.writer(fh)
            writer.writerow(self._columns)
            for row in self._data[: self._n]:
                writer.writerow([int(row[0]), *(_format(v) for v in row[1:])])

    def render(self, size: tuple[int, int]):
        """Return a pygame.Surface with the four graphs (population per species, stored energy per
        colony, combat deaths per 100 ticks per species, total food)."""
        import pygame
        from matplotlib.backends.backend_agg import FigureCanvasAgg
        from matplotlib.figure import Figure

        width, height = max(int(size[0]), 1), max(int(size[1]), 1)
        dpi = 100
        fig = Figure(figsize=(width / dpi, height / dpi), dpi=dpi, facecolor="#202026")
        canvas = FigureCanvasAgg(fig)
        rows, cols = (2, 2) if width >= height else (4, 1)
        axes = fig.subplots(rows, cols, squeeze=False).ravel()

        ticks = self.ticks()
        species = list(range(self.n_species))
        panels = (
            ("Population", self.series("population"), "s", species),
            ("Stored energy", self.series("energy"), "c", list(self._colony_species)),
            (f"Combat deaths / {COMBAT_WINDOW_TICKS} ticks", self.combat_deaths_per_window(), "s",
             species),
            ("Food energy", self.series("food_total_energy"), None, None),
        )
        for ax, (title, values, label_prefix, color_species) in zip(axes, panels, strict=True):
            _style_axes(ax, title)
            if self._n == 0:
                ax.text(0.5, 0.5, "no data yet", color="#606068", ha="center", va="center",
                        transform=ax.transAxes, fontsize=8)
                continue
            for k in range(values.shape[1]):
                if color_species is None:
                    color, label = _FOOD_LINE_COLOR, None
                else:
                    rgb = SPECIES_COLORS[color_species[k] % len(SPECIES_COLORS)]
                    color, label = tuple(rgb / 255.0), f"{label_prefix}{k}"
                ax.plot(ticks, values[:, k], color=color, linewidth=1.2, label=label)
            if label_prefix and values.shape[1] > 1:
                ax.legend(fontsize=6, loc="upper left", frameon=False)
        fig.tight_layout(pad=0.6)

        canvas.draw()
        buf = canvas.buffer_rgba()
        return pygame.image.frombuffer(bytes(buf), canvas.get_width_height(), "RGBA")

    # ---- internals ----------------------------------------------------------------------------
    def _build_columns(self) -> tuple[list[str], dict[str, slice]]:
        """Column names and, per metric key, the slice of its columns in a history row."""
        cols = ["tick"]
        blocks: dict[str, slice] = {}
        for key in METRIC_KEYS_PER_SPECIES:
            blocks[key] = slice(len(cols), len(cols) + self.n_species)
            cols += [f"{_SHORT_NAMES.get(key, key)}_s{i}" for i in range(self.n_species)]
        blocks["energy"] = slice(len(cols), len(cols) + self.n_colonies)
        cols += [f"energy_c{j}" for j in range(self.n_colonies)]
        blocks["food_total_energy"] = slice(len(cols), len(cols) + 1)
        cols.append("food_total_energy")
        return cols, blocks


def _format(value: float):
    """Write integral values without a trailing .0 so counters stay readable in the CSV."""
    return int(value) if float(value).is_integer() else value


def _style_axes(ax, title: str) -> None:
    # Light plot area: the species palette contains near-black colors (SPECIES_COLORS[0]).
    ax.set_facecolor("#e4e4ea")
    ax.set_title(title, color="#d0d0d8", fontsize=8)
    ax.tick_params(colors="#a0a0aa", labelsize=6)
    for spine in ax.spines.values():
        spine.set_color("#50505a")
