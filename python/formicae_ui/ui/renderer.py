"""Map rendering (spec section 10). Owner: P6.

Pipeline per frame: take the visible cell crop -> build an RGB array with NumPy (terrain palette
LUT, food tint, ants colored by species, optional pheromone overlay) -> blit_array -> scale.
Never process all cells each frame; always work on the crop.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from formicae_ui.types import Channel
from formicae_ui.ui.camera import Camera

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
# HOME, FOOD, DANGER
OVERLAY_COLORS = np.array(
    [(60, 120, 255), (60, 255, 120), (255, 60, 60)], dtype=np.float32
)

# Above this zoom, ants are drawn as screen-space sprites instead of scaled pixels.
ANT_SPRITE_ZOOM = 8.0
ANT_SPRITE_RADIUS = 3


@dataclass
class OverlayState:
    show_pheromones: bool = False
    channel: Channel = Channel.FOOD
    species: int = 0
    show_heatmap: bool = False  # stretch (P5)


class Renderer:
    def __init__(self, screen, camera: Camera, hill_radius: int = 2):
        self.screen = screen
        self.camera = camera
        self.hill_radius = hill_radius
        self._terrain_rgb: np.ndarray | None = None
        self._terrain_key: tuple[int, int, int] | None = None

    def invalidate_caches(self) -> None:
        """Drop the terrain RGB cache (call after reset or in-place terrain edits)."""
        self._terrain_rgb = None
        self._terrain_key = None

    def _terrain_crop(self, terrain: np.ndarray, x0: int, y0: int, x1: int, y1: int) -> np.ndarray:
        """Return a writable RGB crop; reuse a full-map LUT so pan/zoom avoids reindexing."""
        key = (int(terrain.ctypes.data), int(terrain.shape[0]), int(terrain.shape[1]))
        if self._terrain_rgb is None or self._terrain_key != key:
            self._terrain_rgb = TERRAIN_COLORS[terrain]
            self._terrain_key = key
        return self._terrain_rgb[y0:y1, x0:x1].copy()

    def render(self, views: SimViews, overlay: OverlayState) -> None:
        """Draw terrain, food, hills, ants and the optional pheromone overlay into the viewport."""
        import pygame

        cam = self.camera
        h, w = views.terrain.shape
        x0, y0, x1, y1 = cam.visible_cells(w, h)
        self.screen.fill((20, 20, 24))
        if x1 <= x0 or y1 <= y0:
            return

        img = self._terrain_crop(views.terrain, x0, y0, x1, y1)
        img[views.food_volume[y0:y1, x0:x1] > 0] = FOOD_COLOR

        r = self.hill_radius
        for c in views.colonies:
            if not c["alive"]:
                continue
            cx, cy = int(c["x"]) - x0, int(c["y"]) - y0
            xs, xe = max(cx - r, 0), min(cx + r + 1, x1 - x0)
            ys, ye = max(cy - r, 0), min(cy + r + 1, y1 - y0)
            if xs < xe and ys < ye:
                img[ys:ye, xs:xe] = SPECIES_COLORS[int(c["species"])] // 2 + 40

        if overlay.show_pheromones and views.pheromones.shape[0] > overlay.species:
            p = views.pheromones[overlay.species, int(overlay.channel), y0:y1, x0:x1]
            tint = OVERLAY_COLORS[int(overlay.channel)]
            a = np.clip(p, 0.0, 1.0)[..., None]
            img = (img.astype(np.float32) * (1.0 - a) + tint * a).astype(np.uint8)

        ants = views.ants
        ants = ants[ants["state"] != 255]
        ax = ants["x"].astype(np.int32) - x0
        ay = ants["y"].astype(np.int32) - y0
        inside = (ax >= 0) & (ay >= 0) & (ax < x1 - x0) & (ay < y1 - y0)
        use_sprites = cam.zoom >= ANT_SPRITE_ZOOM
        if not use_sprites:
            img[ay[inside], ax[inside]] = SPECIES_COLORS[ants["species"][inside]]

        surf = pygame.surfarray.make_surface(img.swapaxes(0, 1))
        size = (max(1, int((x1 - x0) * cam.zoom)), max(1, int((y1 - y0) * cam.zoom)))
        surf = pygame.transform.scale(surf, size)
        origin = ((x0 - cam.x0) * cam.zoom, (y0 - cam.y0) * cam.zoom)
        self.screen.blit(surf, origin)

        if use_sprites and inside.any():
            self._draw_ant_sprites(ants["species"][inside], ax[inside], ay[inside], origin)

    def _draw_ant_sprites(
        self, species: np.ndarray, ax: np.ndarray, ay: np.ndarray, origin: tuple[float, float]
    ) -> None:
        """Draw ants as small filled circles in screen space (readable at high zoom)."""
        import pygame

        cam = self.camera
        ox, oy = origin
        r = max(2, int(ANT_SPRITE_RADIUS * min(2.0, cam.zoom / ANT_SPRITE_ZOOM)))
        for i in range(len(species)):
            sx = int(ox + (ax[i] + 0.5) * cam.zoom)
            sy = int(oy + (ay[i] + 0.5) * cam.zoom)
            color = tuple(int(c) for c in SPECIES_COLORS[int(species[i])])
            pygame.draw.circle(self.screen, color, (sx, sy), r)

    def cell_at(self, sx: int, sy: int) -> tuple[int, int]:
        """Cell under a screen position, for the inspector / spawn-food mode."""
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
    def from_sim(cls, sim) -> SimViews:
        return cls(sim.terrain(), sim.food_volume(), sim.food_density(), sim.pheromones(),
                   sim.ants(), sim.colonies())
