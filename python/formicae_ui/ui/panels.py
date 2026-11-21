"""Side panels: cell inspector and parameter controls (spec section 10). Owner: P4 with P6."""
from __future__ import annotations

import math
from dataclasses import dataclass

from formicae_ui.types import AntState, Channel, Terrain

# Runtime-tunable parameters: (min, max, default) as in spec section 9.3, set_param. The diffusion
# default follows spec sections 4 and 11 and the engine (0.03); the 9.3 table still says 0.05.
TUNABLE_PARAMS = {
    "decay_scale": (0.0, 10.0, 1.0),
    "diffusion": (0.0, 0.2, 0.03),
    "food_spawn_prob": (0.0, 1.0, 0.5),
    "food_spawn_interval": (1, 10000, 50),
    "grad_beta": (0.0, 8.0, 2.0),
    "nav_scale": (0.0, 4.0, 1.0),
    "noise_damp_scale": (0.0, 2.0, 1.0),
}
# Config location of each parameter's starting value (spec section 11). nav_scale and
# noise_damp_scale are runtime-only and start at their defaults.
CONFIG_SOURCES = {
    "decay_scale": ("pheromone", "decay_scale"),
    "diffusion": ("pheromone", "diffusion"),
    "food_spawn_prob": ("food", "spawn_prob"),
    "food_spawn_interval": ("food", "spawn_interval"),
    "grad_beta": ("pheromone", "grad_beta"),
}
# Integer parameter spanning four orders of magnitude: its slider is logarithmic.
LOG_PARAMS = {"food_spawn_interval"}

HEADING_COLOR = (180, 180, 190)
TEXT_COLOR = (220, 220, 220)
DIM_COLOR = (160, 160, 170)
PANEL_BG = (32, 32, 38)
PANEL_BORDER = (90, 90, 100)
TRACK_COLOR = (70, 70, 80)
FILL_COLOR = (110, 150, 210)
LINE_HEIGHT = 16
TERRAIN_NAMES = {t.value: t.name for t in Terrain}
STATE_NAMES = {s.value: s.name for s in AntState}


@dataclass
class Row:
    """One inspector line: text segments at x offsets, optionally led by a species swatch."""

    cells: list[tuple[int, str]]
    color: tuple[int, int, int] = TEXT_COLOR
    swatch: int | None = None
    gap_before: int = 0


class InspectorPanel:
    """Shows sim.cell_info(x, y) for the clicked cell; refreshed every frame while selected."""

    def __init__(
        self,
        rect,
        species_names: list[str],
        species_colors=None,
        caste_names: list[list[str]] | None = None,
    ):
        self.rect = rect
        self.species_names = list(species_names)
        self.caste_names = caste_names or []
        self.species_colors = species_colors
        self.cell: tuple[int, int] | None = None
        self.info: dict | None = None
        self._font = None

    def select(self, sim, x: int, y: int) -> None:
        self.info = sim.cell_info(x, y)
        self.cell = (x, y)

    def refresh(self, sim) -> None:
        if self.cell is not None:
            self.info = sim.cell_info(*self.cell)

    def _species(self, index: int) -> str:
        if 0 <= index < len(self.species_names):
            return self.species_names[index]
        return f"species {index}"

    def _caste(self, ant: dict) -> str:
        """'  GATHERER' when the species defines more than one caste, else ''."""
        species, caste = int(ant["species"]), int(ant.get("caste", 0))
        names = self.caste_names[species] if species < len(self.caste_names) else []
        if len(names) <= 1:
            return ""
        return f"  {names[caste]}" if caste < len(names) else f"  caste {caste}"

    def rows(self) -> list[Row]:
        """Text content of the panel; separate from drawing so it can be tested headless."""
        if self.info is None or self.cell is None:
            return [
                Row([(0, "Inspector")], HEADING_COLOR),
                Row([(0, "click a map cell")], DIM_COLOR),
            ]
        info = self.info
        x, y = self.cell
        terrain = TERRAIN_NAMES.get(int(info["terrain"]), str(info["terrain"]))
        rows = [
            Row([(0, f"Inspector  ({x}, {y})")], HEADING_COLOR),
            Row([(0, "terrain"), (70, terrain)]),
        ]
        volume = float(info["food_volume"])
        food = f"{volume:.1f} units x {float(info['food_density']):.1f}" if volume > 0 else "none"
        rows.append(Row([(0, "food"), (70, food)]))

        pheromone = info["pheromone"]
        rows.append(
            Row(
                [(0, "pheromone"), (110, "HOME"), (155, "FOOD"), (200, "DNGR")],
                DIM_COLOR,
                gap_before=4,
            )
        )
        for s in range(len(pheromone)):
            values = [f"{float(pheromone[s][c]):.2f}" for c in Channel]
            rows.append(
                Row(
                    [(16, self._species(s)[:11]), (110, values[0]), (155, values[1]),
                     (200, values[2])],
                    swatch=s,
                )
            )

        ant = info.get("ant")
        if ant is None:
            rows.append(Row([(0, "ant"), (70, "none")], gap_before=4))
        else:
            state = STATE_NAMES.get(int(ant["state"]), str(ant["state"]))
            species = int(ant["species"])
            rows.append(
                Row([(16, f"ant #{ant['id']}  {self._species(species)}{self._caste(ant)}")],
                    swatch=species, gap_before=4)
            )
            rows.append(Row([(16, f"{state}  hp {float(ant['health']):.1f}  age {ant['age']}")]))
            carried = float(ant.get("carried_volume", 0.0))
            if carried > 0:
                density = float(ant.get("carried_density", 0.0))
                rows.append(Row([(16, f"carrying {carried:.1f} x {density:.1f}")]))

        colony = info.get("colony")
        if colony is not None:
            species = int(colony["species"])
            status = "alive" if colony["alive"] else "destroyed"
            rows.append(
                Row([(16, f"colony #{colony['index']}  {self._species(species)}  {status}")],
                    swatch=species, gap_before=4)
            )
            rows.append(
                Row([(16, f"hp {float(colony['health']):.0f}/{float(colony['max_health']):.0f}"
                          f"  pop {colony['population']}")])
            )
            rows.append(Row([(16, f"energy {float(colony['stored_energy']):.0f}")]))
        return rows

    def draw(self, surface) -> None:
        import pygame

        if self._font is None:
            self._font = pygame.font.Font(None, 18)
        x0, y0, _, height = self.rect
        y = y0
        for row in self.rows():
            y += row.gap_before
            if y + LINE_HEIGHT > y0 + height:
                break
            if row.swatch is not None and self.species_colors is not None:
                color = self.species_colors[row.swatch % len(self.species_colors)]
                pygame.draw.rect(surface, tuple(int(c) for c in color), (x0, y + 2, 10, 10))
            for dx, text in row.cells:
                surface.blit(self._font.render(text, True, row.color), (x0 + dx, y))
            y += LINE_HEIGHT


class ControlPanel:
    """Sliders for TUNABLE_PARAMS; each change calls sim.set_param(name, value)."""

    PADDING = 10
    HEADER_HEIGHT = 22
    ROW_HEIGHT = 32
    TRACK_HEIGHT = 6

    def __init__(self, rect, sim, config: dict | None = None):
        self.rect = rect
        self.sim = sim
        self.values = {name: _initial_value(name, config or {}) for name in TUNABLE_PARAMS}
        self.dragging: str | None = None
        self._font = None

    @classmethod
    def height(cls) -> int:
        return 2 * cls.PADDING + cls.HEADER_HEIGHT + len(TUNABLE_PARAMS) * cls.ROW_HEIGHT

    def set_value(self, name: str, value: float) -> None:
        """Clamps to the parameter's range and applies it to the simulation."""
        low, high, _ = TUNABLE_PARAMS[name]
        value = min(max(value, low), high)
        if name in LOG_PARAMS:
            value = round(value)
        self.sim.set_param(name, value)
        self.values[name] = value

    def handle_event(self, event) -> bool:
        """Returns True when the event belongs to the panel (the map must then ignore it)."""
        import pygame

        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if not self._contains(event.pos):
                return False
            name = self._param_at(event.pos)
            if name is not None:
                self.dragging = name
                self._drag_to(name, event.pos[0])
            return True
        if event.type == pygame.MOUSEMOTION and self.dragging is not None:
            self._drag_to(self.dragging, event.pos[0])
            return True
        if event.type == pygame.MOUSEBUTTONUP and event.button == 1 and self.dragging is not None:
            self.dragging = None
            return True
        if event.type in (pygame.MOUSEBUTTONDOWN, pygame.MOUSEWHEEL):
            # Other buttons and the wheel over the panel must not pan or zoom the map below it.
            pos = event.pos if hasattr(event, "pos") else pygame.mouse.get_pos()
            return self._contains(pos)
        return False

    def draw(self, surface) -> None:
        import pygame

        if self._font is None:
            self._font = pygame.font.Font(None, 18)
        x, y, w, h = self.rect
        pygame.draw.rect(surface, PANEL_BG, (x, y, w, h))
        pygame.draw.rect(surface, PANEL_BORDER, (x, y, w, h), width=2)
        title = "Parameters  (C to close)"
        surface.blit(self._font.render(title, True, HEADING_COLOR), (x + self.PADDING, y + 8))
        for index, name in enumerate(TUNABLE_PARAMS):
            row_y = y + self.PADDING + self.HEADER_HEIGHT + index * self.ROW_HEIGHT
            label_color = TEXT_COLOR if name != self.dragging else FILL_COLOR
            surface.blit(self._font.render(name, True, label_color), (x + self.PADDING, row_y))
            value = self._format(name)
            text = self._font.render(value, True, TEXT_COLOR)
            surface.blit(text, (x + w - self.PADDING - text.get_width(), row_y))
            tx, ty, tw, th = self._track_rect(index)
            pygame.draw.rect(surface, TRACK_COLOR, (tx, ty, tw, th), border_radius=3)
            filled = int(tw * self._fraction(name))
            pygame.draw.rect(surface, FILL_COLOR, (tx, ty, filled, th), border_radius=3)
            pygame.draw.circle(surface, TEXT_COLOR, (tx + filled, ty + th // 2), 6)

    # --- geometry and scaling ----------------------------------------------------------------
    def _contains(self, pos) -> bool:
        x, y, w, h = self.rect
        return x <= pos[0] < x + w and y <= pos[1] < y + h

    def _track_rect(self, index: int) -> tuple[int, int, int, int]:
        x, y, w, _ = self.rect
        row_y = y + self.PADDING + self.HEADER_HEIGHT + index * self.ROW_HEIGHT
        return (x + self.PADDING, row_y + 17, w - 2 * self.PADDING, self.TRACK_HEIGHT)

    def _param_at(self, pos) -> str | None:
        for index, name in enumerate(TUNABLE_PARAMS):
            _, ty, _, th = self._track_rect(index)
            # The whole row (label and track) is clickable.
            if ty - 17 <= pos[1] < ty + th + 8:
                return name
        return None

    def _drag_to(self, name: str, sx: int) -> None:
        tx, _, tw, _ = self._track_rect(list(TUNABLE_PARAMS).index(name))
        fraction = min(max((sx - tx) / tw, 0.0), 1.0)
        self.set_value(name, self._from_fraction(name, fraction))

    def _fraction(self, name: str) -> float:
        low, high, _ = TUNABLE_PARAMS[name]
        value = self.values[name]
        if name in LOG_PARAMS:
            return math.log(value / low) / math.log(high / low)
        return (value - low) / (high - low)

    def _from_fraction(self, name: str, fraction: float) -> float:
        low, high, _ = TUNABLE_PARAMS[name]
        if name in LOG_PARAMS:
            return low * (high / low) ** fraction
        return low + fraction * (high - low)

    def _format(self, name: str) -> str:
        value = self.values[name]
        if name in LOG_PARAMS:
            return f"{int(value)} ticks"
        return f"{value:.3f}" if TUNABLE_PARAMS[name][1] <= 1 else f"{value:.2f}"


def _initial_value(name: str, config: dict) -> float:
    """The value the engine starts with: from the config when set there, else the default."""
    default = TUNABLE_PARAMS[name][2]
    if name not in CONFIG_SOURCES:
        return default
    section, key = CONFIG_SOURCES[name]
    return config.get(section, {}).get(key, default)
