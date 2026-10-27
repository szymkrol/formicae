"""Map generator (spec section 8): determinism, MapData contract and validity over many seeds."""
import numpy as np
import pytest
from formicae_ui.mapgen import MapGenError, MapGenParams, generate_map
from formicae_ui.mapgen.generator import _flood_fill, _noise_field
from formicae_ui.types import Terrain

ARRAY_KEYS = ("terrain", "food_volume", "food_density", "colonies")


def _passable(terrain):
    return (terrain != Terrain.ROCK) & (terrain != Terrain.WATER)


def test_mapdata_contract():
    md = generate_map(42, 200, 150, 3, [0, 1])
    assert md["width"] == 200 and md["height"] == 150
    assert md["terrain"].dtype == np.uint8 and md["terrain"].shape == (150, 200)
    assert md["food_volume"].dtype == np.float32 and md["food_volume"].shape == (150, 200)
    assert md["food_density"].dtype == np.float32 and md["food_density"].shape == (150, 200)
    assert md["colonies"].dtype == np.int32 and md["colonies"].shape == (3, 3)
    assert list(md["colonies"][:, 2]) == [0, 1, 0]
    for key in ARRAY_KEYS:
        assert md[key].flags.c_contiguous
    for key in ("passable_fraction", "hills_placed", "food_clusters_placed",
                "food_clusters_skipped", "corridors_carved"):
        assert key in md["stats"]


def test_same_seed_same_map():
    a = generate_map(7, 256, 256, 3, [0, 1, 2])
    b = generate_map(7, 256, 256, 3, [0, 1, 2])
    for key in ARRAY_KEYS:
        np.testing.assert_array_equal(a[key], b[key])
    c = generate_map(8, 256, 256, 3, [0, 1, 2])
    assert not np.array_equal(a["terrain"], c["terrain"])


def test_food_params_do_not_change_terrain():
    base = generate_map(3, 256, 256, 3, [0])
    other = generate_map(3, 256, 256, 3, [0], MapGenParams(food_min_hill_distance=25))
    np.testing.assert_array_equal(base["terrain"], other["terrain"])
    np.testing.assert_array_equal(base["colonies"], other["colonies"])


@pytest.mark.parametrize("seed", range(100))
def test_hundred_seeds_give_valid_maps(seed):
    md = generate_map(seed, 128, 128, 3, [0, 1, 2])
    terrain, volume, density = md["terrain"], md["food_volume"], md["food_density"]
    border = np.concatenate((terrain[0], terrain[-1], terrain[:, 0], terrain[:, -1]))
    assert np.all(border == Terrain.ROCK)
    assert md["stats"]["passable_fraction"] >= 0.5
    assert np.all((volume > 0) == (density > 0))
    assert np.all((volume == 0) | ((volume >= 50) & (volume <= 200)))
    assert np.all((density == 0) | ((density >= 10) & (density <= 50)))

    x0, y0 = md["colonies"][0, :2]
    component = _flood_fill(_passable(terrain), int(x0), int(y0))
    hills = md["colonies"]
    for x, y, _ in hills:
        assert component[y, x]
        footprint = terrain[y - 2 : y + 3, x - 2 : x + 3]
        assert np.all(footprint == Terrain.GRASS)
        assert np.all(volume[y - 2 : y + 3, x - 2 : x + 3] == 0)
    assert np.all(component[volume > 0])
    assert np.all(_passable(terrain)[volume > 0])
    min_dist = 0.2 * 128
    for i in range(len(hills)):
        for j in range(i):
            assert np.hypot(*(hills[i, :2] - hills[j, :2])) >= min_dist


def test_isolated_hills_get_corridors():
    carved = 0
    for seed in range(20):
        params = MapGenParams(water_level=0.42, rock_level=0.7)
        md = generate_map(seed, 256, 256, 5, [0, 1], params)
        carved += md["stats"]["corridors_carved"]
    assert carved > 0


def test_impossible_hill_distance_raises():
    with pytest.raises(MapGenError, match="colony 1"):
        generate_map(1, 64, 64, 2, [0], MapGenParams(min_hill_distance_factor=2.0))


def test_noise_field_range_and_shape():
    field = _noise_field(np.random.default_rng(0), 50, 70, 5, 64)
    assert field.shape == (50, 70)
    assert field.min() == 0.0 and field.max() == 1.0


def test_flood_fill_matches_four_connectivity():
    passable = np.array(
        [[1, 1, 0, 1],
         [0, 1, 0, 1],
         [1, 0, 0, 1],
         [1, 1, 1, 1]], dtype=bool)
    got = _flood_fill(passable, 0, 0)
    expected = np.zeros_like(passable)
    expected[0, 0] = expected[0, 1] = expected[1, 1] = True  # (0, 2) touches only diagonally
    np.testing.assert_array_equal(got, expected)
    assert _flood_fill(passable, 3, 0).sum() == 8
