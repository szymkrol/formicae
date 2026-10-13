// combat.cpp - combat, hazards, death handling (spec section 6). Owner: P3 (M2).
#include "formicae/combat.hpp"

#include "formicae/engine.hpp"

namespace formicae {

Target find_target(const Engine& e, int attacker_slot) {
  (void)e;
  (void)attacker_slot;
  // TODO(P3): look at the 4 neighbors: lowest-health enemy ant (hostile species), ties random;
  //   otherwise an adjacent cell with hill_at() of a hostile species.
  return Target{};
}

void resolve_attack(Engine& e, int attacker_slot, const Target& target) {
  (void)e;
  (void)attacker_slot;
  (void)target;
  // TODO(P3): roll < accuracy; damage = max(0.5, damage * (0.75 + 0.5 * rng) - armor);
  //   deposit hit_alarm on both species' DANGER layers at the target cell; on health <= 0 call
  //   e.kill_ant(slot, DeathCause::Combat, attacker species) or on_colony_destroyed().
}

void on_ant_death(Engine& e, int slot, DeathCause cause, int killer_species) {
  (void)e;
  (void)slot;
  (void)cause;
  (void)killer_species;
  // TODO(P3): e.add_food() for the carried load, death_alarm on the victim's DANGER layer,
  //   metrics: deaths_<cause>[species]++, kills[killer_species]++ when killer_species >= 0.
}

}  // namespace formicae
