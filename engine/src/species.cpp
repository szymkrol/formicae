// species.cpp - resolved [species][caste] table. Owner: P2 (M2).
#include <algorithm>

#include "antsim/species.hpp"

namespace antsim {

void SpeciesTable::build(const Config& cfg) {
  species_count_ = static_cast<int>(cfg.species.size());
  data_.assign(static_cast<size_t>(species_count_) * MAX_CASTES, ResolvedStats{});
  caste_counts_.assign(species_count_, 1);
  for (int s = 0; s < species_count_; ++s) {
    const SpeciesStats& base = cfg.species[s].stats;
    const std::vector<CasteDef> standard{CasteDef{}};
    const std::vector<CasteDef>& list =
        (s < static_cast<int>(cfg.castes.size()) && !cfg.castes[s].empty()) ? cfg.castes[s] : standard;
    caste_counts_[s] = std::min<int>(static_cast<int>(list.size()), MAX_CASTES);
    for (int c = 0; c < MAX_CASTES; ++c) {
      const CasteDef& cd = list[std::min<size_t>(c, list.size() - 1)];
      ResolvedStats r = base;
      r.max_health *= cd.max_health_mul;
      r.damage *= cd.damage_mul;
      r.armor *= cd.armor_mul;
      r.speed = std::min(1.0f, r.speed * cd.speed_mul);
      r.carry_capacity *= cd.carry_mul;
      r.cost *= cd.cost_mul;
      r.random_move_prob = std::clamp(r.random_move_prob + cd.random_move_prob_add, 0.0f, 1.0f);
      r.a_home *= cd.a_home_mul;
      r.a_food *= cd.a_food_mul;
      r.danger_k += cd.danger_k_add;
      r.danger_k_home += cd.danger_k_add;
      if (cd.defend_while_carrying >= 0) r.defend_while_carrying = cd.defend_while_carrying != 0;
      data_[static_cast<size_t>(s) * MAX_CASTES + c] = r;
    }
  }
}

}  // namespace antsim
