// colony.hpp - colony records (spec section 7.1). Owner: P3 (M2).
#pragma once
#include <array>
#include <cstdint>

#include "antsim/types.hpp"

namespace antsim {

// Exposed to Python as colonies() (32 bytes, see COLONY_DTYPE in python/antsim_ui/types.py).
struct ColonyRecord {
  double stored_energy;   //  0
  float health;           //  8
  float max_health;       // 12
  uint32_t population;    // 16
  int16_t x, y;           // 20, 22  center cell
  uint8_t species;        // 24
  uint8_t alive;          // 25
  uint8_t pad[6];         // 26
};
static_assert(sizeof(ColonyRecord) == 32, "ColonyRecord must stay 32 bytes");

// Engine-internal colony data, parallel array to ColonyRecord.
struct ColonyExtra {
  uint8_t spawn_cooldown = 0;
  std::array<float, MAX_CASTES> caste_ratio{1.f, 0.f, 0.f, 0.f};
};

}  // namespace antsim

// ---------------------------------------------------------------------------------------------
// Entry points implemented by M2 (P3) and called by the engine (spec section 9.4).
// ---------------------------------------------------------------------------------------------
namespace antsim {
class Engine;

// Pipeline step 2, once per live colony: spawn rule, cost, cooldown, free footprint cell (7.2).
void colony_update(Engine& e, int colony);

// Called when a colony's health drops to 0 or below: loot food, clear footprint (7.3).
void on_colony_destroyed(Engine& e, int colony);
}  // namespace antsim
