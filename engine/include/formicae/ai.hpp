// ai.hpp - ant behaviour entry point (spec sections 5.3 and 5.4). Owner: P2 (M2).
#pragma once

namespace formicae {
class Engine;

// Pipeline step 3, once per live ant, sequential and in place. Runs the priority table of 5.3:
// death checks, hazard damage, flee/fight transitions, pickup, delivery, otherwise movement (5.4).
// Attacks are delegated to resolve_attack() (combat.hpp, P3).
void ant_update(Engine& e, int slot);

}  // namespace formicae
