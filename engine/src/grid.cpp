// grid.cpp - layer allocation. Owner: P1 (M1).
#include "formicae/grid.hpp"

namespace formicae {

void Grid::allocate(int width, int height, int species_count) {
  W = width;
  H = height;
  S = species_count;
  const size_t n = static_cast<size_t>(W) * H;
  terrain.assign(n, 0);
  move_cost.assign(n, 1.0f);
  evap_mod.assign(n, 1.0f);
  hazard.assign(n, 0.0f);
  passable.assign(n, 1);
  food_volume.assign(n, 0.0f);
  food_density.assign(n, 0.0f);
  occupancy.assign(n, NO_ANT);
  hill_id.assign(n, static_cast<int16_t>(NO_HILL));
  pher.assign(n * NUM_CHANNELS * static_cast<size_t>(S), 0.0f);
}

}  // namespace formicae
