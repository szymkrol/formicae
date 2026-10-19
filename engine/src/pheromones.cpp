// pheromones.cpp - pheromone update, pipeline step 5 (spec section 4). Owner: P1 (M1).
#include "formicae/engine.hpp"

namespace formicae {

void Engine::pheromone_update() {
    const PheromoneParams &pp = cfg_.pheromone;
    const int n = grid_.cells();
    const int W = grid_.W;
    const int H = grid_.H;
    const int S = static_cast<int>(cfg_.species.size());

    // Diffusion (Double-Buffered)
    if (pp.diffusion > 0.0f) {
        for (int s = 0; s < S; ++s) {
            for (int c = 0; c < NUM_CHANNELS; ++c) {
                float *p = grid_.plane(s, c);

                std::copy(p, p + n, diffusion_buffer_.begin());

                for (int y = 1; y < H - 1; ++y) {
                    for (int x = 1; x < W - 1; ++x) {
                        const int i = y * W + x;
                        const float mean4 = (diffusion_buffer_[i - W] + diffusion_buffer_[i + 1] +
                                             diffusion_buffer_[i + W] + diffusion_buffer_[i - 1]) *
                                            0.25f;
                        p[i] = diffusion_buffer_[i] + pp.diffusion * (mean4 - diffusion_buffer_[i]);
                    }
                }
            }
        }
    }
    // Baseline decay: p *= (1 - rho_c * decay_scale * evap_mod[cell]); values below cutoff become
    // 0.
    for (int s = 0; s < S; ++s) {
        for (int c = 0; c < NUM_CHANNELS; ++c) {
            float *p = grid_.plane(s, c);
            const float *f = decay_factors_[c].data();

            for (int i = 0; i < n; ++i) {
                p[i] *= f[i];
                if (p[i] < pp.cutoff)
                    p[i] = 0.0f;
            }
        }
    }

    // Hill beacon (after decay, so it stays at its maximum): HOME of the owning species is kept at
    // its maximum on all footprint cells.
    for (int i = 0; i < n; ++i) {
        const int h = grid_.hill_id[i];
        if (h != NO_HILL && colonies_[h].alive)
            grid_.plane(colonies_[h].species, static_cast<int>(Channel::Home))[i] = pp.home_beacon;
    }
}

} // namespace formicae
