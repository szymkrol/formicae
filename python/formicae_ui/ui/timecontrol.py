"""Simulation speed control (spec section 10, 'Time control'). Owner: P6."""
from __future__ import annotations

SPEED_STEPS = (0.25, 0.5, 1.0, 2.0, 5.0, 10.0, float("inf"))  # inf = MAX


class TimeControl:
    """Turns wall-clock time into a number of engine ticks per frame.

    acc += dt * base_tps * mult;  n = floor(acc);  acc -= n.  The caller runs step(n) but stops
    early when the frame's simulation budget is spent (see App._advance).
    """

    def __init__(self, base_tps: float = 30.0, budget_ms: float = 10.0, max_ticks_per_frame: int = 1000):
        self.base_tps = base_tps
        self.budget_ms = budget_ms
        self.max_ticks_per_frame = max_ticks_per_frame
        self.paused = False
        self._speed_index = 2  # 1.0x
        self._acc = 0.0
        self._single_step = False

    @property
    def multiplier(self) -> float:
        return SPEED_STEPS[self._speed_index]

    def faster(self) -> None:
        self._speed_index = min(self._speed_index + 1, len(SPEED_STEPS) - 1)

    def slower(self) -> None:
        self._speed_index = max(self._speed_index - 1, 0)

    def toggle_pause(self) -> None:
        self.paused = not self.paused

    def request_single_step(self) -> None:
        self._single_step = True

    def ticks_for_frame(self, dt: float) -> int:
        """Number of ticks to run this frame given the elapsed seconds `dt`."""
        if self._single_step:
            self._single_step = False
            return 1
        if self.paused:
            return 0
        if self.multiplier == float("inf"):
            return self.max_ticks_per_frame
        self._acc += dt * self.base_tps * self.multiplier
        n = int(self._acc)
        self._acc -= n
        return min(n, self.max_ticks_per_frame)
