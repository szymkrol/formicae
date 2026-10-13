"""Main window and loop (spec section 10). Owner: P6; hotkeys wired together with P4 and P5."""
from __future__ import annotations

import time

from formicae_ui.analytics import Analytics
from formicae_ui.ui.camera import Camera
from formicae_ui.ui.renderer import OverlayState, Renderer, SimViews
from formicae_ui.ui.timecontrol import TimeControl

WINDOW_SIZE = (1280, 800)
SIDEBAR_WIDTH = 280
TARGET_FPS = 60
ANALYTICS_EVERY_TICKS = 10


class App:
    """Owns the window, camera, time control and the simulation object (real engine or mock)."""

    def __init__(self, sim, config: dict, map_data: dict):
        self.sim = sim
        self.config = config
        self.map_data = map_data
        self.time = TimeControl()
        self.overlay = OverlayState()
        self.analytics = Analytics(n_species=len(config["species"]), n_colonies=len(map_data["colonies"]))
        self._last_recorded_tick = -1

    def run(self, max_frames: int | None = None) -> None:
        """Open the window and loop until closed (or for `max_frames` frames, used by smoke tests)."""
        import pygame  # imported here so that tests and tools can import the package without pygame

        pygame.display.init()  # not pygame.init(): no audio needed, avoids ALSA warnings
        pygame.font.init()
        screen = pygame.display.set_mode(WINDOW_SIZE)
        pygame.display.set_caption("Ant simulation")
        clock = pygame.time.Clock()
        camera = Camera(WINDOW_SIZE[0] - SIDEBAR_WIDTH, WINDOW_SIZE[1])
        map_h, map_w = self.map_data["terrain"].shape
        camera.zoom = max(camera.min_zoom, min(camera.viewport_w / map_w, camera.viewport_h / map_h))
        renderer = Renderer(screen, camera)
        font = pygame.font.Font(None, 22)
        frames = 0

        running = True
        while running:
            dt = clock.tick(TARGET_FPS) / 1000.0
            for event in pygame.event.get():
                running = self._handle_event(event, camera, renderer) and running
            self._advance(dt)
            renderer.render(SimViews.from_sim(self.sim), self.overlay)
            self._draw_hud(screen, font, clock)
            # TODO(P4): inspector and control panels; TODO(P5): analytics panel on Tab
            # (self.analytics.render(size) at most once per second).
            pygame.display.flip()
            frames += 1
            if max_frames is not None and frames >= max_frames:
                running = False
        pygame.quit()

    def _draw_hud(self, screen, font, clock) -> None:
        """Basic sidebar text. TODO(P6): real layout, actual ticks/s, species legend."""
        import pygame

        x = WINDOW_SIZE[0] - SIDEBAR_WIDTH + 12
        pygame.draw.rect(screen, (32, 32, 38), (WINDOW_SIZE[0] - SIDEBAR_WIDTH, 0, SIDEBAR_WIDTH, WINDOW_SIZE[1]))
        speed = "MAX" if self.time.multiplier == float("inf") else f"{self.time.multiplier:g}x"
        lines = [f"tick {self.sim.tick}", f"speed {speed}" + ("  (paused)" if self.time.paused else ""),
                 f"fps {clock.get_fps():.0f}", "",
                 "Space pause   N step", "+/-  speed   P pheromones", "wheel zoom   drag pan", "E export CSV"]
        for i, text in enumerate(lines):
            screen.blit(font.render(text, True, (220, 220, 220)), (x, 12 + 24 * i))

    def _advance(self, dt: float) -> None:
        """Run the engine for this frame within the simulation budget (spec section 10)."""
        n = self.time.ticks_for_frame(dt)
        deadline = time.perf_counter() + self.time.budget_ms / 1000.0
        done = 0
        while done < n and (done == 0 or time.perf_counter() < deadline):
            self.sim.step(1)  # TODO(P6): batch with step(k) once timing per tick is known
            done += 1
            tick = self.sim.tick
            if tick - self._last_recorded_tick >= ANALYTICS_EVERY_TICKS:
                self.analytics.record(self.sim.metrics(), self.sim.colonies())
                self._last_recorded_tick = tick

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
            elif event.key in (pygame.K_PLUS, pygame.K_EQUALS):
                self.time.faster()
            elif event.key == pygame.K_MINUS:
                self.time.slower()
            elif event.key == pygame.K_p:
                self.overlay.show_pheromones = not self.overlay.show_pheromones
            elif event.key == pygame.K_e:
                self.analytics.export_csv("metrics.csv")
            # TODO(P6): 1/2/3 channel, [ ] species, F spawn-food mode, R reset, Tab analytics, S save
        elif event.type == pygame.MOUSEWHEEL:
            mx, my = pygame.mouse.get_pos()
            camera.zoom_at(mx, my, 1.25 if event.y > 0 else 0.8)
        elif event.type == pygame.MOUSEMOTION and (event.buttons[1] or event.buttons[2]):
            camera.pan(*event.rel)
        # TODO(P4/P6): left click -> InspectorPanel.select(self.sim, *renderer.cell_at(...))
        return True
