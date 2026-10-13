// pheromones.cpp - pheromone update, pipeline step 5 (spec section 4). Owner: P1 (M1).
#include "formicae/engine.hpp"

namespace formicae {

void Engine::pheromone_update() {
  const PheromoneParams& pp = cfg_.pheromone;
  const int n = grid_.cells();

  // TODO(P1): optional diffusion when pp.diffusion > 0 (double-buffered, spec section 4).

  // Baseline decay: p *= (1 - rho_c * decay_scale * evap_mod[cell]); values below cutoff become 0.
  // TODO(P1): precompute per-channel factor planes when decay_scale changes, vectorize, and
  // optionally apply every k ticks with (1 - r)^k (spec section 3).
  for (int s = 0; s < grid_.S; ++s) {
    for (int c = 0; c < NUM_CHANNELS; ++c) {
      float* p = grid_.plane(s, c);
      const float rho = pp.decay[c] * pp.decay_scale;
      for (int i = 0; i < n; ++i) {
        float f = 1.0f - rho * grid_.evap_mod[i];
        if (f < 0.0f) f = 0.0f;
        p[i] *= f;
        if (p[i] < pp.cutoff) p[i] = 0.0f;
      }
    }
  }

  // Hill beacon (after decay, so it stays at its maximum): HOME of the owning species is kept at its maximum on all footprint cells.
  for (int i = 0; i < n; ++i) {
    const int h = grid_.hill_id[i];
    if (h != NO_HILL && colonies_[h].alive) grid_.plane(colonies_[h].species, static_cast<int>(Channel::Home))[i] = pp.home_beacon;
  }

}

}  // namespace formicae
