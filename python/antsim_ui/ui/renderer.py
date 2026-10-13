"""Map rendering (spec section 10). Owner: P6.

Pipeline per frame: take the visible cell crop -> build an RGB array with NumPy (terrain palette
LUT, food tint, ants colored by species, optional pheromone overlay) -> blit_array -> scale.
Never process all cells each frame; always work on the crop.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from antsim_ui.types import Channel, Terrain
from antsim_ui.ui.camera import Camera

TERRAIN_COLORS = np.array(
    [
        (96, 150, 70),    # GRASS
        (220, 200, 140),  # SAND
        (110, 80, 50),    # MUD
        (190, 170, 120),  # PATH
        (90, 90, 90),     # ROCK
        (60, 110, 190),   # WATER
        (150, 60, 90),    # THORNS
    ],
    dtype=np.uint8,
)
SPECIES_COLORS = np.array(
    [(20, 20, 20), (200, 40, 40), (240, 200, 30), (140, 60, 200),
     (30, 160, 160), (240, 120, 30), (255, 255, 255), (0, 0, 160)],
    dtype=np.uint8,
)


FOOD_COLOR = np.array((235, 205, 40), dtype=np.uint8)
OVERLAY_COLORS = np.array([(60, 120, 255), (60, 255, 120), (255, 60, 60)], dtype=np.float32)  # HOME, FOOD, DANGER


@dataclass
class OverlayState:
    show_pheromones: bool = False
    channel: Channel = Channel.FOOD
    species: int = 0
    show_heatmap: bool = False  # stretch


class Renderer:
    def __init__(self, screen, camera: Camera):
        self.screen = screen
        self.camera = camera

    def render(self, views: "SimViews", overlay: OverlayState) -> None:
        """Draw terrain, food, hills, ants and the optional pheromone overlay into the viewport.

        Basic version: works on the visible crop only. TODO(P6): speed (reuse the terrain image,
        draw ants as sprites at high zoom), heatmap overlay, caste shades.
        """
        import pygame

        cam = self.camera
        h, w = views.terrain.shape
        x0, y0, x1, y1 = cam.visible_cells(w, h)
        self.screen.fill((20, 20, 24))
        if x1 <= x0 or y1 <= y0:
            return
        img = TERRAIN_COLORS[views.terrain[y0:y1, x0:x1]]  # fancy indexing returns a copy
        img[views.food_volume[y0:y1, x0:x1] > 0] = FOOD_COLOR

        for c in views.colonies:  # hill footprints (5x5 around the center; radius from config later)
            if not c["alive"]:
                continue
            cx, cy = int(c["x"]) - x0, int(c["y"]) - y0
            xs, xe = max(cx - 2, 0), min(cx + 3, x1 - x0)
            ys, ye = max(cy - 2, 0), min(cy + 3, y1 - y0)
            if xs < xe and ys < ye:
                img[ys:ye, xs:xe] = SPECIES_COLORS[int(c["species"])] // 2 + 40

        if overlay.show_pheromones and views.pheromones.shape[0] > overlay.species:
            p = views.pheromones[overlay.species, int(overlay.channel), y0:y1, x0:x1]
            tint = OVERLAY_COLORS[int(overlay.channel)]
            a = np.clip(p, 0.0, 1.0)[..., None]
            img = (img * (1 - a) + tint * a).astype(np.uint8)

        ants = views.ants
        ants = ants[ants["state"] != 255]
        ax, ay = ants["x"].astype(np.int32) - x0, ants["y"].astype(np.int32) - y0
        inside = (ax >= 0) & (ay >= 0) & (ax < x1 - x0) & (ay < y1 - y0)
        img[ay[inside], ax[inside]] = SPECIES_COLORS[ants["species"][inside]]

        surf = pygame.surfarray.make_surface(img.swapaxes(0, 1))
        size = (max(1, int((x1 - x0) * cam.zoom)), max(1, int((y1 - y0) * cam.zoom)))
        surf = pygame.transform.scale(surf, size)
        self.screen.blit(surf, ((x0 - cam.x0) * cam.zoom, (y0 - cam.y0) * cam.zoom),
                         area=None)

    def cell_at(self, sx: int, sy: int) -> tuple[int, int]:
        """Cell under a screen position, for the inspector."""
        wx, wy = self.camera.screen_to_world(sx, sy)
        return int(wx), int(wy)


@dataclass
class SimViews:
    """Read-only snapshot views of one frame (valid until the next step); see spec 9.3."""

    terrain: np.ndarray
    food_volume: np.ndarray
    food_density: np.ndarray
    pheromones: np.ndarray
    ants: np.ndarray
    colonies: np.ndarray

    @classmethod
    def from_sim(cls, sim) -> "SimViews":
        return cls(sim.terrain(), sim.food_volume(), sim.food_density(), sim.pheromones(),
                   sim.ants(), sim.colonies())
