// species.hpp - resolved [species][caste] stats table (spec section 5.2). Owner: P2 (M2).
#pragma once
#include <cstdint>
#include <vector>

#include "formicae/config.hpp"

namespace formicae {

// Species stats with the caste multipliers already applied. The tick loop does one lookup per ant.
using ResolvedStats = SpeciesStats;

class SpeciesTable {
 public:
  // Combines every species with each of its castes (STANDARD only when none are configured).
  void build(const Config& cfg);

  const ResolvedStats& get(uint8_t species, uint8_t caste) const {
    return data_[static_cast<size_t>(species) * MAX_CASTES + caste];
  }
  int species_count() const { return species_count_; }
  int caste_count(int species) const { return caste_counts_[species]; }

 private:
  std::vector<ResolvedStats> data_;  // [species * MAX_CASTES + caste]
  std::vector<int> caste_counts_;
  int species_count_ = 0;
};

}  // namespace formicae
