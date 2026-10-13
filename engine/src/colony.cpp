// colony.cpp - colony lifecycle (spec sections 7.2, 7.3). Owner: P3 (M2).
#include "antsim/colony.hpp"

#include "antsim/engine.hpp"

namespace antsim {

void colony_update(Engine& e, int colony) {
  (void)e;
  (void)colony;
  // TODO(P3): if cooldown == 0, stored_energy >= cost, population < max_population:
  //   pick a caste from caste_ratio with e.rng(), find a free footprint cell (random start offset,
  //   first free), e.spawn_ant(colony, caste, cell); pay cost; cooldown = cfg.colony.spawn_cooldown.
  //   Otherwise decrement the cooldown.
}

void on_colony_destroyed(Engine& e, int colony) {
  (void)e;
  (void)colony;
  // TODO(P3): alive = 0, clear hill_id on the footprint, turn stored_energy into food on the center
  //   cell (volume += E / loot_density, density = loot_density), colonies_alive[species]--.
}

}  // namespace antsim
