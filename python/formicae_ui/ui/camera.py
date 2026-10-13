"""Zoom and pan (spec section 10). Owner: P6."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Camera:
    """Maps world cells to screen pixels. `zoom` = pixels per cell; (x0, y0) = world cell at the
    top-left corner of the viewport (fractional)."""

    viewport_w: int
    viewport_h: int
    zoom: float = 2.0
    x0: float = 0.0
    y0: float = 0.0
    min_zoom: float = 0.25
    max_zoom: float = 32.0

    def world_to_screen(self, wx: float, wy: float) -> tuple[float, float]:
        return (wx - self.x0) * self.zoom, (wy - self.y0) * self.zoom

    def screen_to_world(self, sx: float, sy: float) -> tuple[float, float]:
        return sx / self.zoom + self.x0, sy / self.zoom + self.y0

    def zoom_at(self, sx: float, sy: float, factor: float) -> None:
        """Zoom toward the cursor so the cell under (sx, sy) stays under it."""
        wx, wy = self.screen_to_world(sx, sy)
        self.zoom = max(self.min_zoom, min(self.max_zoom, self.zoom * factor))
        self.x0 = wx - sx / self.zoom
        self.y0 = wy - sy / self.zoom

    def pan(self, dx_pixels: float, dy_pixels: float) -> None:
        self.x0 -= dx_pixels / self.zoom
        self.y0 -= dy_pixels / self.zoom

    def visible_cells(self, world_w: int, world_h: int) -> tuple[int, int, int, int]:
        """Integer crop (x_min, y_min, x_max, y_max), clamped to the map, end exclusive."""
        x_min = max(0, int(self.x0))
        y_min = max(0, int(self.y0))
        x_max = min(world_w, int(self.x0 + self.viewport_w / self.zoom) + 2)
        y_max = min(world_h, int(self.y0 + self.viewport_h / self.zoom) + 2)
        return x_min, y_min, x_max, y_max
