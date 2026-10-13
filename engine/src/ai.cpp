// ai.cpp - ant behaviour (spec sections 5.3 and 5.4). Owner: P2 (M2).
#include "antsim/ai.hpp"

#include "antsim/combat.hpp"
#include "antsim/engine.hpp"

namespace antsim {

void ant_update(Engine& e, int slot) {
  Ant& a = e.ants()[slot];
  const ResolvedStats& st = e.stats_of(a);
  (void)st;
  ++a.age;
  // TODO(P2): implement the priority table of spec 5.3 in this order:
  //   1 death (health <= 0, age >= max_age, orphan loss)  -> e.kill_ant(...)
  //   2 THORNS damage + DANGER deposit
  //   3 flee transition   4 attack via find_target()/resolve_attack()   5 end of fight
  //   6 FLEEING movement  7 pickup   8 delivery   9 normal movement (spec 5.4):
  //     candidates -> weighted choice (w = (eps + tau)^alpha * h * g) -> pay move cost -> deposit.
}

}  // namespace antsim
