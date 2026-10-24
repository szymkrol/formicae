"""Main window and loop (spec section 10). Owner: P6; hotkeys wired together with P4 and P5."""
from __future__ import annotations

import time

from formicae_ui.analytics import Analytics
from formicae_ui.types import Channel
from formicae_ui.ui.camera import Camera
from formicae_ui.ui.renderer import SPECIES_COLORS, OverlayState, Renderer, SimViews
from formicae_ui.ui.timecontrol import TimeControl

WINDOW_SIZE = (1280, 800)
SIDEBAR_WIDTH = 280
TARGET_FPS = 60
ANALYTICS_EVERY_TICKS = 10
CHANNEL_NAMES = {Channel.HOME: "HOME", Channel.FOOD: "FOOD", Channel.DANGER: "DANGER"}

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
        self.analytics = Analytics(n_species=self.n_species, n_colonies=len(map_data["colonies"]))
        self._last_recorded_tick = -1
        self.spawn_food_mode = False
        self._renderer: Renderer | None = None

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
            renderer.render(SimViews.from_sim(self.sim), self.overlay)
            self._draw_hud(screen, font, font_small, clock)
            # TODO(P4): inspector and control panels; TODO(P5): analytics panel on Tab
            # (self.analytics.render(size) at most once per second).
            pygame.display.flip()
            frames += 1
            if max_frames is not None and frames >= max_frames:
                running = False
        self._renderer = None
        pygame.quit()

    def _draw_hud(self, screen, font, font_small, clock) -> None:
        """Sidebar: status, overlay state, species legend and key bindings (spec section 10)."""
        import pygame

        x = WINDOW_SIZE[0] - SIDEBAR_WIDTH + 12
        sidebar = (WINDOW_SIZE[0] - SIDEBAR_WIDTH, 0, SIDEBAR_WIDTH, WINDOW_SIZE[1])
        pygame.draw.rect(screen, (32, 32, 38), sidebar)
        speed = "MAX" if self.time.multiplier == float("inf") else f"{self.time.multiplier:g}x"
        if self.time.paused:
            speed += "  (paused)"
        channel = CHANNEL_NAMES[self.overlay.channel]
        species_label = self.species_names[self.overlay.species] if self.n_species else "-"
        pher = "on" if self.overlay.show_pheromones else "off"
        mode = "SPAWN FOOD" if self.spawn_food_mode else "view"

        y = 12
        lines = [
            ("Status", True),
            (f"tick  {self.sim.tick}", False),
            (f"speed {speed}", False),
            (f"fps   {clock.get_fps():.0f}", False),
            (f"tps   {self.time.actual_tps:.0f}", False),
            (f"mode  {mode}", False),
            ("", False),
            ("Overlay", True),
            (f"pheromones  {pher}", False),
            (f"channel     {channel}  (1/2/3)", False),
            (f"species     {species_label}  ([ ])", False),
            ("", False),
            ("Species", True),
        ]
        for text, heading in lines:
            if not text and not heading:
                y += 10
                continue
            color = (180, 180, 190) if heading else (220, 220, 220)
            use_font = font_small if heading else font
            screen.blit(use_font.render(text, True, color), (x, y))
            y += 18 if heading else 22

        for i, name in enumerate(self.species_names):
            color = tuple(int(c) for c in SPECIES_COLORS[i % len(SPECIES_COLORS)])
            pygame.draw.rect(screen, color, (x, y + 4, 12, 12))
            label = f"{i}  {name}"
            if i == self.overlay.species and self.overlay.show_pheromones:
                label += "  *"
            screen.blit(font_small.render(label, True, (220, 220, 220)), (x + 18, y))
            y += 18

        y += 12
        screen.blit(font_small.render("Keys", True, (180, 180, 190)), (x, y))
        y += 18
        help_lines = [
            "Space pause    N step",
            "+/- speed      P pheromones",
            "1/2/3 channel  [ ] species",
            "F spawn food   R reset",
            "wheel zoom     drag pan",
            "E export CSV",
            "click: spawn food when F on",
        ]
        for text in help_lines:
            screen.blit(font_small.render(text, True, (160, 160, 170)), (x, y))
            y += 16

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
        if self._renderer is not None:
            self._renderer.invalidate_caches()

    def _spawn_food_at(self, renderer: Renderer, sx: int, sy: int) -> None:
        if sx >= WINDOW_SIZE[0] - SIDEBAR_WIDTH:
            return
        cx, cy = renderer.cell_at(sx, sy)
        h, w = self.map_data["terrain"].shape
        if not (0 <= cx < w and 0 <= cy < h):
            return
        self.sim.spawn_food(cx, cy, SPAWN_FOOD_RADIUS, SPAWN_FOOD_VOLUME, SPAWN_FOOD_DENSITY)

    def _handle_event(self, event, camera: Camera, renderer: Renderer) -> bool:
        """Hotkeys of spec section 10. Returns False to quit."""
        import pygame

        if event.type == pygame.QUIT:
            return False
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
            # TODO(P4): S save snapshot; TODO(P5): Tab analytics panel
        elif event.type == pygame.MOUSEWHEEL:
            mx, my = pygame.mouse.get_pos()
            if mx < WINDOW_SIZE[0] - SIDEBAR_WIDTH:
                camera.zoom_at(mx, my, 1.25 if event.y > 0 else 0.8)
        elif event.type == pygame.MOUSEMOTION and (event.buttons[1] or event.buttons[2]):
            camera.pan(*event.rel)
        elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if self.spawn_food_mode:
                self._spawn_food_at(renderer, *event.pos)
            # else TODO(P4): InspectorPanel.select(self.sim, *renderer.cell_at(...))
        return True
