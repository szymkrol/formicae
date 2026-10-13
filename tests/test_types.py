from antsim_ui.types import ANT_DTYPE, COLONY_DTYPE


def test_record_sizes():
    assert ANT_DTYPE.itemsize == 40
    assert COLONY_DTYPE.itemsize == 32


def test_ant_offsets_match_spec():
    assert ANT_DTYPE.fields["health"][1] == 24
    assert ANT_DTYPE.fields["move_acc"][1] == 36
    assert COLONY_DTYPE.fields["x"][1] == 20
