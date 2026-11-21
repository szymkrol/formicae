// ant.hpp - the 44-byte Ant record (spec section 5.1). Owner: P2 (M2).
// Field layout is mirrored by ANT_DTYPE in python/formicae_ui/types.py - change both together.
#pragma once
#include <cstdint>

#include "formicae/types.hpp"

namespace formicae {

struct Ant {
  uint32_t id;               //   0  unique id, never reused within a run
  uint32_t age;              //   4  ticks alive
  int16_t x, y;              //   8  cell coordinates
  uint16_t colony;           //  12  index of the colony that spawned it
  uint16_t trail_age;        //  14  steps since last home visit / last pickup
  uint8_t species;           //  16
  uint8_t caste;             //  17  index into the resolved caste table
  uint8_t state;             //  18  AntState
  int8_t last_dir;           //  19  Dir, -1 = none
  uint8_t timer;             //  20  remaining flee ticks
  uint8_t explore_timer;     //  21  ticks remaining ignoring FOOD after failed/erased visit
  uint8_t fidelity_fail;     //  22  reserved counter for failed remembered visits
  uint8_t pad;               //  23  zeroed/reserved
  float health;              //  24
  float carried_volume;      //  28
  float carried_density;     //  32
  float move_acc;            //  36  accumulated movement points
  int16_t food_x;            //  40  remembered food cell x, -1 = none
  int16_t food_y;            //  42  remembered food cell y, -1 = none
};
static_assert(sizeof(Ant) == 44, "Ant must stay 44 bytes (NumPy dtype relies on it)");

inline bool is_alive(const Ant& a) { return a.state != static_cast<uint8_t>(AntState::Dead); }

}  // namespace formicae
