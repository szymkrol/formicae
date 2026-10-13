// grid.hpp - structure-of-arrays world layers and the grid API (spec sections 2 and 9.4).
// Owner: P1 (M1). M2 uses only the accessors below (the spec's free functions are Grid methods).
#pragma once
#include <array>
#include <cstdint>
#include <vector>

#include "formicae/types.hpp"

namespace formicae {

struct Neighbors4 {
  std::array<int, 4> cell{-1, -1, -1, -1};  // N, E, S, W cell indices; -1 if outside the map
};

struct Grid {
  int W = 0, H = 0, S = 0;  // width, height, number of species

  // Layers, flat and row-major: index i = y * W + x.
  std::vector<uint8_t> terrain;
  std::vector<float> move_cost, evap_mod, hazard;  // derived from terrain table
  std::vector<uint8_t> passable;                   // derived from terrain table
  std::vector<float> food_volume, food_density;
  std::vector<int32_t> occupancy;                  // ant slot index or NO_ANT
  std::vector<int16_t> hill_id;                    // colony index or NO_HILL
  std::vector<float> pher;                         // [S][3][H][W]

  void allocate(int width, int height, int species_count);  // sizes all layers, clears them

  int cells() const { return W * H; }
  int idx(int x, int y) const { return y * W + x; }
  int x_of(int i) const { return i % W; }
  int y_of(int i) const { return i / W; }
  bool in_bounds(int x, int y) const { return x >= 0 && y >= 0 && x < W && y < H; }
  bool is_passable(int i) const { return passable[i] != 0; }  // hazards count as passable
  int occupant(int i) const { return occupancy[i]; }
  int hill_at(int i) const { return hill_id[i]; }
  float cost_at(int i) const { return move_cost[i]; }

  Neighbors4 neighbors4(int i) const {
    Neighbors4 n;
    const int x = x_of(i), y = y_of(i);
    for (int d = 0; d < 4; ++d) {
      const int nx = x + DX[d], ny = y + DY[d];
      n.cell[d] = in_bounds(nx, ny) ? idx(nx, ny) : -1;
    }
    return n;
  }

  // Pheromone plane for (species, channel): H*W floats.
  float* plane(int species, int channel) {
    return pher.data() + (static_cast<size_t>(species) * NUM_CHANNELS + channel) * cells();
  }
  const float* plane(int species, int channel) const {
    return pher.data() + (static_cast<size_t>(species) * NUM_CHANNELS + channel) * cells();
  }
  float pher_at(int species, int channel, int i) const { return plane(species, channel)[i]; }
  void deposit(int species, int channel, int i, float amount) {  // capped at P_MAX
    float& p = plane(species, channel)[i];
    p = p + amount > P_MAX ? P_MAX : p + amount;
  }
};

}  // namespace formicae
