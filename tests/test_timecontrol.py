"""Unit tests for TimeControl (spec section 10)."""
from formicae_ui.ui.timecontrol import SPEED_STEPS, TimeControl


def test_ticks_for_frame_respects_speed_and_pause():
    tc = TimeControl(base_tps=30.0)
    assert tc.ticks_for_frame(1.0) == 30  # 1.0x
    tc.faster()
    assert tc.multiplier == 2.0
    assert tc.ticks_for_frame(1.0) == 60
    tc.toggle_pause()
    assert tc.ticks_for_frame(1.0) == 0


def test_single_step_ignores_pause():
    tc = TimeControl()
    tc.toggle_pause()
    tc.request_single_step()
    assert tc.ticks_for_frame(0.0) == 1
    assert tc.ticks_for_frame(0.0) == 0


def test_max_speed_caps_at_max_ticks_per_frame():
    tc = TimeControl(max_ticks_per_frame=100)
    tc._speed_index = len(SPEED_STEPS) - 1
    assert tc.multiplier == float("inf")
    assert tc.ticks_for_frame(1.0) == 100


def test_record_ticks_updates_actual_tps():
    tc = TimeControl()
    tc._tps_window_start -= 1.0  # force window close
    tc.record_ticks(40)
    assert abs(tc.actual_tps - 40.0) < 0.01
