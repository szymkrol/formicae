"""Shared constants and NumPy record layouts (spec sections 5.1, 9.3).

The layouts must match engine/include/formicae/ant.hpp and colony.hpp byte for byte.
"""
from __future__ import annotations

from enum import IntEnum

import numpy as np

S_MAX = 8
NUM_CHANNELS = 3
MAX_CASTES = 4


class Terrain(IntEnum):
    GRASS = 0
    SAND = 1
    MUD = 2
    PATH = 3
    ROCK = 4
    WATER = 5
    THORNS = 6


class Channel(IntEnum):
    HOME = 0
    FOOD = 1
    DANGER = 2


class AntState(IntEnum):
    SEARCHING = 0
    RETURNING = 1
    FIGHTING = 2
    FLEEING = 3
    DEAD = 255


ANT_DTYPE = np.dtype(
    {
        "names": ["id", "age", "x", "y", "colony", "trail_age", "species", "caste", "state",
                  "last_dir", "timer", "pad", "health", "carried_volume", "carried_density",
                  "move_acc"],
        "formats": ["<u4", "<u4", "<i2", "<i2", "<u2", "<u2", "u1", "u1", "u1", "i1", "u1",
                    ("u1", (3,)), "<f4", "<f4", "<f4", "<f4"],
        "offsets": [0, 4, 8, 10, 12, 14, 16, 17, 18, 19, 20, 21, 24, 28, 32, 36],
        "itemsize": 40,
    }
)

COLONY_DTYPE = np.dtype(
    {
        "names": ["stored_energy", "health", "max_health", "population", "x", "y", "species",
                  "alive", "pad"],
        "formats": ["<f8", "<f4", "<f4", "<u4", "<i2", "<i2", "u1", "u1", ("u1", (6,))],
        "offsets": [0, 8, 12, 16, 20, 22, 24, 25, 26],
        "itemsize": 32,
    }
)

METRIC_KEYS_PER_SPECIES = (
    "population", "births", "kills", "deaths_combat", "deaths_hazard", "deaths_age",
    "deaths_orphan", "colonies_alive",
)
