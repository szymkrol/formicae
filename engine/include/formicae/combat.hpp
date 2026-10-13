// combat.hpp - combat, death and hazard rules (spec section 6). Owner: P3 (M2).
#pragma once
#include "formicae/types.hpp"

namespace formicae {
class Engine;

struct Target {
  enum class Kind : uint8_t { None, Ant, Hill } kind = Kind::None;
  int index = -1;  // ant slot or colony index
};

// Picks the attack target for `attacker_slot` (lowest-health adjacent enemy ant, else adjacent
// enemy hill footprint). Returns Kind::None when there is nothing to attack.
Target find_target(const Engine& e, int attacker_slot);

// Hit roll, damage after armour, hit-event alarm on both species' DANGER layers (section 6).
// May call Engine::kill_ant() or on_colony_destroyed().
void resolve_attack(Engine& e, int attacker_slot, const Target& target);

// Pipeline step 4, once per ant that died this tick: drop carried food, victim's death alarm,
// counters by cause, kill credit to killer_species (-1 if none). The engine frees the slot after.
void on_ant_death(Engine& e, int slot, DeathCause cause, int killer_species);

}  // namespace formicae
