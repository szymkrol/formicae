"""Main window and loop (spec section 10). Owner: P6; hotkeys wired together with P4 and P5."""
from __future__ import annotations

import time
from pathlib import Path

from formicae_ui.analytics import Analytics
from formicae_ui.types import Channel
from formicae_ui.ui.camera import Camera
from formicae_ui.ui.panels import ControlPanel, InspectorPanel
from formicae_ui.ui.renderer import (
    SPECIES_CASTE_COLORS,
    SPECIES_COLORS,
    STATE_COLORS,
    OverlayState,
    Renderer,
    SimViews,
)
from formicae_ui.ui.timecontrol import TimeControl

WINDOW_SIZE = (1280, 800)
SIDEBAR_WIDTH = 280
TARGET_FPS = 60
ANALYTICS_EVERY_TICKS = 10
ANALYTICS_REDRAW_SECONDS = 1.0
ANALYTICS_PANEL_SIZE = (640, 440)
ANALYTICS_PANEL_MARGIN = 12
CHANNEL_NAMES = {Channel.HOME: "HOME", Channel.FOOD: "FOOD", Channel.DANGER: "DANGER"}
CONTROL_PANEL_MARGIN = 12
CONTROL_PANEL_WIDTH = 300
STATUS_SECONDS = 4.0
HEATMAP_CYCLE = (None, "traffic", "combat")  # key T
MAX_COLONY_ROWS = 8
COLONY_BAR_WIDTH = 60
HEADING_COLOR = (180, 180, 190)
TEXT_COLOR = (220, 220, 220)
DIM_COLOR = (160, 160, 170)
HELP_LINES = (
    "Space   pause / resume        N   single step",
    "+ / -   speed                 R   reset",
    "P       pheromone overlay     1/2/3  channel",
    "[ ]     overlay species       T   heatmap (traffic/combat)",
    "A       ant colors: species/caste or state",
    "F       spawn-food mode (left click spawns)",
    "C       parameter sliders     Tab analytics",
    "S       save snapshot         E   export CSV",
    "left click  inspect cell      wheel  zoom",
    "right / middle drag  pan      H   close this help",
)

# Manual spawn-food defaults (mid-range of config food.volume/density/radius).
SPAWN_FOOD_RADIUS = 2
SPAWN_FOOD_VOLUME = 100.0
SPAWN_FOOD_DENSITY = 30.0


class App:
    """Owns the window, camera, time control and the simulation object (real engine or mock)."""

    def __init__(self, sim, config: dict, map_data: dict):
        self.sim = sim
        self.config = config
        self.map_data = map_data
        time_cfg = config.get("time", {})
        self.time = TimeControl(
            base_tps=float(time_cfg.get("base_tps", 30)),
            budget_ms=float(time_cfg.get("frame_budget_ms", 10)),
        )
        self.overlay = OverlayState()
        self.n_species = len(config["species"])
        self.species_names = [
            s.get("name", f"species {i}") for i, s in enumerate(config["species"])
        ]
        self.caste_names = [
            [c.get("name", f"caste {k}") for k, c in enumerate(s.get("castes", []))] or ["STANDARD"]
            for s in config["species"]
        ]
        self.analytics = Analytics(n_species=self.n_species, n_colonies=len(map_data["colonies"]))
        self._last_recorded_tick = -1
        self.show_analytics = False
        self._analytics_surface = None
        self._analytics_drawn_at = float("-inf")
        self.spawn_food_mode = False
        self._renderer: Renderer | None = None
        self.inspector = InspectorPanel(
            (0, 0, 0, 0), self.species_names, SPECIES_COLORS, self.caste_names
        )
        controls_rect = (
            CONTROL_PANEL_MARGIN, CONTROL_PANEL_MARGIN, CONTROL_PANEL_WIDTH, ControlPanel.height()
        )
        self.controls = ControlPanel(controls_rect, sim, config)
        self.show_controls = False
        self.show_help = False
        self._status = ""
        self._status_until = 0.0

    def run(self, max_frames: int | None = None) -> None:
        """Open the window and loop until closed (or `max_frames` for smoke tests)."""
        import pygame  # imported here so that tests and tools can import the package without pygame

        pygame.display.init()  # not pygame.init(): no audio needed, avoids ALSA warnings
        pygame.font.init()
        screen = pygame.display.set_mode(WINDOW_SIZE)
        pygame.display.set_caption("Ant simulation")
        clock = pygame.time.Clock()
        camera = Camera(WINDOW_SIZE[0] - SIDEBAR_WIDTH, WINDOW_SIZE[1])
        map_h, map_w = self.map_data["terrain"].shape
        fit = min(camera.viewport_w / map_w, camera.viewport_h / map_h)
        camera.zoom = max(camera.min_zoom, fit)
        hill_radius = int(self.config.get("colony", {}).get("hill_radius", 2))
        renderer = Renderer(screen, camera, hill_radius=hill_radius)
        self._renderer = renderer
        font = pygame.font.Font(None, 22)
        font_small = pygame.font.Font(None, 18)
        frames = 0

        running = True
        while running:
            dt = clock.tick(TARGET_FPS) / 1000.0
            for event in pygame.event.get():
                running = self._handle_event(event, camera, renderer) and running
            self._advance(dt)
            renderer.render(self._views(), self.overlay)
            hud_bottom = self._draw_hud(screen, font, font_small, clock)
            self._draw_inspector(screen, hud_bottom)
            if self.show_analytics:
                self._draw_analytics(screen)
            if self.show_controls:
                self.controls.draw(screen)
            if self.show_help:
                self._draw_help(screen, font_small)
            pygame.display.flip()
            frames += 1
            if max_frames is not None and frames >= max_frames:
                running = False
        self._renderer = None
        pygame.quit()

    def _views(self) -> SimViews:
        """Views for this frame; turns the heatmap overlay off if the engine has no counters."""
        try:
            return SimViews.from_sim(self.sim, self.overlay.heatmap)
        except RuntimeError:
            self.overlay.heatmap = None
            self._show_status("heatmaps off: set enable_heatmaps")
            return SimViews.from_sim(self.sim)

    def _draw_hud(self, screen, font, font_small, clock) -> int:
        """Sidebar: status, overlays, ant color legend and colonies (spec section 10).

        Returns the y coordinate below the last line, where the inspector starts.
        """
        import pygame

        x = WINDOW_SIZE[0] - SIDEBAR_WIDTH + 12
        sidebar = (WINDOW_SIZE[0] - SIDEBAR_WIDTH, 0, SIDEBAR_WIDTH, WINDOW_SIZE[1])
        pygame.draw.rect(screen, (32, 32, 38), sidebar)
        speed = "MAX" if self.time.multiplier == float("inf") else f"{self.time.multiplier:g}x"
        if self.time.paused:
            speed += "  (paused)"
        channel = CHANNEL_NAMES[self.overlay.channel]
        species_label = self.species_names[self.overlay.species] if self.n_species else "-"
        pher = f"{channel} of {species_label}" if self.overlay.show_pheromones else "off"
        heat = self.overlay.heatmap or "off"
        mode = "SPAWN FOOD" if self.spawn_food_mode else "view"

        y = 10
        lines = [
            ("Status", True),
            (f"tick {self.sim.tick}   {speed}", False),
            (f"fps {clock.get_fps():.0f}   tps {self.time.actual_tps:.0f}   {mode}", False),
            (self._current_status(), True),  # small font: file names are long
            ("", False),
            ("Overlay   (P, 1/2/3, [ ], T)", True),
            (f"pheromones  {pher}", False),
            (f"heatmap     {heat}", False),
            ("", False),
        ]
        for text, heading in lines:
            if text is None:
                continue
            if not text and not heading:
                y += 8
                continue
            color = HEADING_COLOR if heading else TEXT_COLOR
            use_font = font_small if heading else font
            screen.blit(use_font.render(text, True, color), (x, y))
            y += 18 if heading else 21

        y = self._draw_ant_legend(screen, font_small, x, y)
        y = self._draw_colonies(screen, font_small, x, y + 8)
        screen.blit(font_small.render("H  keys and help", True, DIM_COLOR), (x, y + 6))
        return y + 22

    def _draw_ant_legend(self, screen, font_small, x: int, y: int) -> int:
        """Species (with caste shades) or state legend, matching the A key mode."""
        import pygame

        if self.overlay.color_by_state:
            screen.blit(font_small.render("Ants by state   (A)", True, HEADING_COLOR), (x, y))
            y += 18
            for state, color in STATE_COLORS.items():
                pygame.draw.rect(screen, color, (x, y + 3, 10, 10))
                screen.blit(font_small.render(state.name, True, TEXT_COLOR), (x + 18, y))
                y += 16
            return y

        has_castes = any(len(names) > 1 for names in self.caste_names)
        title = "Ants by species, caste shades   (A)" if has_castes else "Ants by species   (A)"
        screen.blit(font_small.render(title, True, HEADING_COLOR), (x, y))
        y += 18
        for i, name in enumerate(self.species_names):
            color = tuple(int(c) for c in SPECIES_COLORS[i % len(SPECIES_COLORS)])
            pygame.draw.rect(screen, color, (x, y + 3, 10, 10))
            label = f"{i}  {name}"
            if i == self.overlay.species and self.overlay.show_pheromones:
                label += "  *"
            screen.blit(font_small.render(label, True, TEXT_COLOR), (x + 18, y))
            if len(self.caste_names[i]) > 1:
                for k in range(len(self.caste_names[i])):
                    shade = SPECIES_CASTE_COLORS[i % len(SPECIES_COLORS), k]
                    swatch = (x + 150 + 14 * k, y + 3, 10, 10)
                    pygame.draw.rect(screen, tuple(int(c) for c in shade), swatch)
            y += 16
        if has_castes:
            longest = max(self.caste_names, key=len)
            abbrev = " ".join(name[:3] for name in longest)
            screen.blit(font_small.render(f"castes: {abbrev}", True, DIM_COLOR), (x + 18, y))
            y += 16
        return y

    def _draw_colonies(self, screen, font_small, x: int, y: int) -> int:
        """Health bar, stored energy and population of every colony (spec 7.1)."""
        import pygame

        screen.blit(font_small.render("Colonies", True, HEADING_COLOR), (x, y))
        y += 18
        colonies = self.sim.colonies()
        shown = colonies[:MAX_COLONY_ROWS]
        for index, c in enumerate(shown):
            species = int(c["species"])
            color = tuple(int(v) for v in SPECIES_COLORS[species % len(SPECIES_COLORS)])
            pygame.draw.rect(screen, color, (x, y + 3, 10, 10))
            screen.blit(font_small.render(f"#{index}", True, TEXT_COLOR), (x + 16, y))
            if not c["alive"]:
                screen.blit(font_small.render("destroyed", True, DIM_COLOR), (x + 44, y))
            else:
                health = float(c["health"]) / max(float(c["max_health"]), 1.0)
                fraction = max(0.0, min(1.0, health))
                bar_x, bar_y = x + 44, y + 4
                pygame.draw.rect(screen, (70, 70, 80), (bar_x, bar_y, COLONY_BAR_WIDTH, 8))
                filled = (bar_x, bar_y, int(COLONY_BAR_WIDTH * fraction), 8)
                pygame.draw.rect(screen, _health_color(fraction), filled)
                text = f"E {float(c['stored_energy']):.0f}  pop {int(c['population'])}"
                text_x = bar_x + COLONY_BAR_WIDTH + 6
                screen.blit(font_small.render(text, True, TEXT_COLOR), (text_x, y))
            y += 16
        if len(colonies) > len(shown):
            more = f"+{len(colonies) - len(shown)} more (inspect a hill)"
            screen.blit(font_small.render(more, True, DIM_COLOR), (x + 16, y))
            y += 16
        return y

    def _draw_help(self, screen, font_small) -> None:
        """Key reference (H), drawn over the map so the sidebar keeps room for live data."""
        import pygame

        mono = pygame.font.SysFont("monospace", 14)
        width = 24 + max(mono.size(line)[0] for line in HELP_LINES)
        height = 36 + 18 * len(HELP_LINES)
        left = (WINDOW_SIZE[0] - SIDEBAR_WIDTH - width) // 2
        top = (WINDOW_SIZE[1] - height) // 2
        pygame.draw.rect(screen, (32, 32, 38), (left, top, width, height))
        pygame.draw.rect(screen, (90, 90, 100), (left, top, width, height), width=2)
        screen.blit(font_small.render("Keys", True, HEADING_COLOR), (left + 12, top + 8))
        for i, line in enumerate(HELP_LINES):
            screen.blit(mono.render(line, True, TEXT_COLOR), (left + 12, top + 28 + 18 * i))

    def _draw_inspector(self, screen, top: int) -> None:
        x = WINDOW_SIZE[0] - SIDEBAR_WIDTH + 12
        top += 12
        self.inspector.rect = (x, top, SIDEBAR_WIDTH - 24, WINDOW_SIZE[1] - top - 8)
        self.inspector.refresh(self.sim)
        self.inspector.draw(screen)

    def _show_status(self, message: str) -> None:
        self._status = message
        self._status_until = time.perf_counter() + STATUS_SECONDS

    def _current_status(self) -> str | None:
        """Transient message (e.g. the saved snapshot name), or None once it has expired."""
        if self._status and time.perf_counter() < self._status_until:
            return self._status
        return None

    def _save_snapshot(self) -> Path | None:
        """S key: binary snapshot (spec 9.3 save) in the working directory, never overwriting."""
        stamp = time.strftime("%Y%m%d_%H%M%S")
        path = Path.cwd() / f"snap_{stamp}_t{self.sim.tick}.ants"
        suffix = 1
        while path.exists():
            path = Path.cwd() / f"snap_{stamp}_t{self.sim.tick}_{suffix}.ants"
            suffix += 1
        try:
            self.sim.save(str(path))
        except (ValueError, RuntimeError) as err:
            self._show_status(f"save failed: {err}")
            return None
        self._show_status(f"saved {path.stem}")
        return path

    def _draw_analytics(self, screen) -> None:
        """Analytics panel (Tab): graphs re-rendered at most once per second (spec 9.5)."""
        import pygame

        now = time.perf_counter()
        if self._analytics_surface is None or now - self._analytics_drawn_at >= (
            ANALYTICS_REDRAW_SECONDS
        ):
            self._analytics_surface = self.analytics.render(ANALYTICS_PANEL_SIZE)
            self._analytics_drawn_at = now
        x = ANALYTICS_PANEL_MARGIN
        y = WINDOW_SIZE[1] - ANALYTICS_PANEL_MARGIN - self._analytics_surface.get_height()
        frame = self._analytics_surface.get_rect(topleft=(x, y)).inflate(4, 4)
        pygame.draw.rect(screen, (90, 90, 100), frame, width=2)
        screen.blit(self._analytics_surface, (x, y))

    def _advance(self, dt: float) -> None:
        """Run the engine for this frame within the simulation budget (spec section 10)."""
        n = self.time.ticks_for_frame(dt)
        if n <= 0:
            self.time.record_ticks(0)
            return

        deadline = time.perf_counter() + self.time.budget_ms / 1000.0
        done = 0
        batch = 1
        while done < n:
            if done > 0 and time.perf_counter() >= deadline:
                break
            k = min(batch, n - done)
            t0 = time.perf_counter()
            self.sim.step(k)
            elapsed = time.perf_counter() - t0
            done += k

            tick = self.sim.tick
            if tick - self._last_recorded_tick >= ANALYTICS_EVERY_TICKS:
                self.analytics.record(self.sim.metrics(), self.sim.colonies())
                self._last_recorded_tick = tick

            remaining_budget = deadline - time.perf_counter()
            if remaining_budget <= 0:
                break
            if elapsed > 0:
                # Grow the next batch to fill the remaining frame budget.
                batch = max(1, min(n - done, max(k, int(k * remaining_budget / elapsed))))
            else:
                batch = min(n - done, max(k * 2, 1))

        self.time.record_ticks(done)

    def _cycle_species(self, delta: int) -> None:
        if self.n_species <= 0:
            return
        self.overlay.species = (self.overlay.species + delta) % self.n_species

    def _reset_simulation(self) -> None:
        self.sim.reset()
        self.time.reset_stats()
        self._last_recorded_tick = -1
        self.analytics.clear()
        self._analytics_surface = None
        if self._renderer is not None:
            self._renderer.invalidate_caches()

    def _map_cell_at(self, renderer: Renderer, sx: int, sy: int) -> tuple[int, int] | None:
        """Map cell under a screen position, or None outside the viewport or the map."""
        if sx >= WINDOW_SIZE[0] - SIDEBAR_WIDTH:
            return None
        cx, cy = renderer.cell_at(sx, sy)
        h, w = self.map_data["terrain"].shape
        if not (0 <= cx < w and 0 <= cy < h):
            return None
        return cx, cy

    def _spawn_food_at(self, renderer: Renderer, sx: int, sy: int) -> None:
        cell = self._map_cell_at(renderer, sx, sy)
        if cell is not None:
            self.sim.spawn_food(*cell, SPAWN_FOOD_RADIUS, SPAWN_FOOD_VOLUME, SPAWN_FOOD_DENSITY)

    def _inspect_at(self, renderer: Renderer, sx: int, sy: int) -> None:
        cell = self._map_cell_at(renderer, sx, sy)
        if cell is not None:
            self.inspector.select(self.sim, *cell)

    def _handle_event(self, event, camera: Camera, renderer: Renderer) -> bool:
        """Hotkeys of spec section 10. Returns False to quit."""
        import pygame

        if event.type == pygame.QUIT:
            return False
        if self.show_controls and self.controls.handle_event(event):
            return True
        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_SPACE:
                self.time.toggle_pause()
            elif event.key == pygame.K_n:
                self.time.request_single_step()
            elif event.key in (pygame.K_PLUS, pygame.K_EQUALS, pygame.K_KP_PLUS):
                self.time.faster()
            elif event.key in (pygame.K_MINUS, pygame.K_KP_MINUS):
                self.time.slower()
            elif event.key == pygame.K_p:
                self.overlay.show_pheromones = not self.overlay.show_pheromones
            elif event.key == pygame.K_e:
                self.analytics.export_csv("metrics.csv")
            elif event.key in (pygame.K_1, pygame.K_KP1):
                self.overlay.channel = Channel.HOME
                self.overlay.show_pheromones = True
            elif event.key in (pygame.K_2, pygame.K_KP2):
                self.overlay.channel = Channel.FOOD
                self.overlay.show_pheromones = True
            elif event.key in (pygame.K_3, pygame.K_KP3):
                self.overlay.channel = Channel.DANGER
                self.overlay.show_pheromones = True
            elif event.key == pygame.K_LEFTBRACKET:
                self._cycle_species(-1)
            elif event.key == pygame.K_RIGHTBRACKET:
                self._cycle_species(1)
            elif event.key == pygame.K_f:
                self.spawn_food_mode = not self.spawn_food_mode
            elif event.key == pygame.K_r:
                self._reset_simulation()
            elif event.key == pygame.K_TAB:
                self.show_analytics = not self.show_analytics
                self._analytics_surface = None
            elif event.key == pygame.K_s:
                self._save_snapshot()
            elif event.key == pygame.K_c:
                self.show_controls = not self.show_controls
            elif event.key == pygame.K_a:
                self.overlay.color_by_state = not self.overlay.color_by_state
            elif event.key == pygame.K_t:
                position = HEATMAP_CYCLE.index(self.overlay.heatmap)
                self.overlay.heatmap = HEATMAP_CYCLE[(position + 1) % len(HEATMAP_CYCLE)]
            elif event.key == pygame.K_h:
                self.show_help = not self.show_help
        elif event.type == pygame.MOUSEWHEEL:
            mx, my = pygame.mouse.get_pos()
            if mx < WINDOW_SIZE[0] - SIDEBAR_WIDTH:
                camera.zoom_at(mx, my, 1.25 if event.y > 0 else 0.8)
        elif event.type == pygame.MOUSEMOTION and (event.buttons[1] or event.buttons[2]):
            camera.pan(*event.rel)
        elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if self.spawn_food_mode:
                self._spawn_food_at(renderer, *event.pos)
            else:
                self._inspect_at(renderer, *event.pos)
        return True


def _health_color(fraction: float) -> tuple[int, int, int]:
    """Green above half health, amber above a quarter, red below."""
    if fraction > 0.5:
        return (80, 200, 90)
    if fraction > 0.25:
        return (230, 170, 40)
    return (230, 50, 50)
