// types.hpp - shared constants and enums (spec sections 2, 4, 5). Owner: P1 (M1).
#pragma once
#include <cstdint>

namespace formicae {

constexpr int S_MAX = 8;        // maximum number of species
constexpr int NUM_CHANNELS = 3; // HOME, FOOD, DANGER
constexpr int MAX_CASTES = 4;   // castes per species (v1 uses only STANDARD = 0)
constexpr float P_MAX = 1.0f;   // pheromone cap

constexpr int NO_ANT = -1;  // value of occupancy[] for a free cell
constexpr int NO_HILL = -1; // value of hill_id[] outside any footprint

enum class Channel : uint8_t { Home = 0, Food = 1, Danger = 2 };

enum class Terrain : uint8_t {
    Grass = 0,
    Sand = 1,
    Mud = 2,
    Path = 3,
    Rock = 4,
    Water = 5,
    Thorns = 6
};

enum class AntState : uint8_t {
    Searching = 0,
    Returning = 1,
    Fighting = 2,
    Fleeing = 3,
    Dead = 255
};

// Directions: y grows downwards (origin top-left), so N is y - 1.
enum class Dir : int8_t { None = -1, N = 0, E = 1, S = 2, W = 3 };
constexpr int DX[4] = {0, 1, 0, -1};
constexpr int DY[4] = {-1, 0, 1, 0};
constexpr Dir opposite(Dir d) {
    return d == Dir::None ? Dir::None : static_cast<Dir>((static_cast<int>(d) + 2) & 3);
}

enum class DeathCause : uint8_t { Combat = 0, Hazard = 1, Age = 2, Orphan = 3 };

} // namespace formicae
