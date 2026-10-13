"""Side panels: cell inspector and parameter controls (spec section 10). Owner: P4 with P6."""
from __future__ import annotations

# Runtime-tunable parameters and their ranges (spec section 9.3, set_param).
TUNABLE_PARAMS = {
    "decay_scale": (0.0, 10.0, 1.0),
    "diffusion": (0.0, 0.2, 0.0),
    "food_spawn_prob": (0.0, 1.0, 0.5),
    "food_spawn_interval": (1, 10000, 50),
}


class InspectorPanel:
    """Shows sim.cell_info(x, y) for the clicked cell."""

    def __init__(self, rect):
        self.rect = rect
        self.info: dict | None = None

    def select(self, sim, x: int, y: int) -> None:
        self.info = sim.cell_info(x, y)

    def draw(self, surface) -> None:
        raise NotImplementedError("TODO(P4): draw terrain, food, pheromones per species/channel, ant, colony")


class ControlPanel:
    """Sliders for TUNABLE_PARAMS; each change calls sim.set_param(name, value)."""

    def __init__(self, rect, sim):
        self.rect = rect
        self.sim = sim

    def handle_event(self, event) -> None:
        raise NotImplementedError("TODO(P4): sliders for TUNABLE_PARAMS")

    def draw(self, surface) -> None:
        raise NotImplementedError("TODO(P4)")
