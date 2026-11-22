from formicae_ui.types import ANT_DTYPE, COLONY_DTYPE


def test_ant_record_layout():
    assert ANT_DTYPE.itemsize == 44
    assert COLONY_DTYPE.itemsize == 32


def test_ant_field_offsets():
    assert ANT_DTYPE.fields["health"][1] == 24
    assert ANT_DTYPE.fields["move_acc"][1] == 36
    assert ANT_DTYPE.fields["explore_timer"][1] == 21
    assert ANT_DTYPE.fields["fidelity_fail"][1] == 22
    assert ANT_DTYPE.fields["pad"][1] == 23
    assert ANT_DTYPE.fields["food_x"][1] == 40
    assert ANT_DTYPE.fields["food_y"][1] == 42
    assert COLONY_DTYPE.fields["x"][1] == 20
