// combat.cpp - combat, hazards, death handling (spec section 6). Owner: P3 (M2).
#include "formicae/combat.hpp"

#include <algorithm>
#include <limits>

#include "formicae/engine.hpp"

namespace formicae {

namespace {

constexpr float MIN_DAMAGE = 0.5f;

// Deterministic rotation of the N,E,S,W scan order. find_target() only sees a const Engine, so it
// cannot draw from the shared RNG; rotating the start direction by tick and slot breaks ties
// without consuming random numbers and without any fixed directional bias.
int scan_start(const Engine& e, int attacker_slot) {
  return static_cast<int>((e.tick() + static_cast<uint64_t>(attacker_slot)) & 3u);
}

// Which of the attacker's 4 neighbours belongs to the footprint of `colony` (-1 if none).
int adjacent_hill_cell(const Grid& g, const Ant& attacker, int colony) {
  const Neighbors4 nb = g.neighbors4(g.idx(attacker.x, attacker.y));
  for (int cell : nb.cell)
    if (cell >= 0 && g.hill_at(cell) == colony) return cell;
  return -1;
}

}  // namespace

Target find_target(const Engine& e, int attacker_slot) {
  const Ant& attacker = e.ants()[attacker_slot];
  const Grid& g = e.grid();
  const Neighbors4 nb = g.neighbors4(g.idx(attacker.x, attacker.y));
  const int start = scan_start(e, attacker_slot);

  Target best;
  float best_health = std::numeric_limits<float>::max();
  int hill_colony = -1;

  for (int k = 0; k < 4; ++k) {
    const int cell = nb.cell[(start + k) & 3];
    if (cell < 0) continue;

    const int occupant = g.occupant(cell);
    if (occupant != NO_ANT) {
      const Ant& other = e.ants()[occupant];
      // Strict '<': among equally wounded enemies the first one in rotated order wins.
      if (is_alive(other) && e.hostile(attacker.species, other.species) && other.health < best_health) {
        best = Target{Target::Kind::Ant, occupant};
        best_health = other.health;
      }
    }

    const int hill = g.hill_at(cell);
    if (hill_colony < 0 && hill != NO_HILL) {
      const ColonyRecord& colony = e.colonies()[hill];
      if (colony.alive && e.hostile(attacker.species, colony.species)) hill_colony = hill;
    }
  }

  if (best.kind == Target::Kind::Ant) return best;  // ants take priority over hills
  if (hill_colony >= 0) return Target{Target::Kind::Hill, hill_colony};
  return Target{};
}

void resolve_attack(Engine& e, int attacker_slot, const Target& target) {
  if (target.kind == Target::Kind::None) return;

  Grid& g = e.grid();
  Rng& rng = e.rng();
  const Ant& attacker = e.ants()[attacker_slot];
  const ResolvedStats& st = e.stats_of(attacker);

  // Resolve the target before rolling, so a stale target costs no random numbers.
  float armor = 0.0f;
  int cell = -1;
  int victim_species = -1;
  if (target.kind == Target::Kind::Ant) {
    const Ant& victim = e.ants()[target.index];
    if (!is_alive(victim)) return;
    armor = e.stats_of(victim).armor;
    cell = g.idx(victim.x, victim.y);
    victim_species = victim.species;
  } else {
    const ColonyRecord& colony = e.colonies()[target.index];
    if (!colony.alive) return;
    cell = adjacent_hill_cell(g, attacker, target.index);
    if (cell < 0) cell = g.idx(colony.x, colony.y);  // attacker is not next to the hill anymore
    victim_species = colony.species;
  }

  if (rng.next_float() >= st.accuracy) return;  // miss
  const float damage = std::max(MIN_DAMAGE, st.damage * (0.75f + 0.5f * rng.next_float()) - armor);

  // Hit event: alarm on the DANGER layer of both species involved.
  const float alarm = e.config().pheromone.hit_alarm;
  e.deposit(attacker.species, Channel::Danger, cell, alarm);
  if (victim_species != attacker.species) e.deposit(victim_species, Channel::Danger, cell, alarm);

  if (target.kind == Target::Kind::Ant) {
    Ant& victim = e.ants()[target.index];
    victim.health -= damage;
    if (victim.health <= 0.0f) e.kill_ant(target.index, DeathCause::Combat, attacker.species);
  } else {
    ColonyRecord& colony = e.colonies()[target.index];
    colony.health -= damage;
    if (colony.health <= 0.0f) on_colony_destroyed(e, target.index);
  }
}

void on_ant_death(Engine& e, int slot, DeathCause cause, int killer_species) {
  // kill_ant() left x, y, species and the carried load untouched for exactly this call.
  Ant& a = e.ants()[slot];
  const int cell = e.grid().idx(a.x, a.y);

  if (a.carried_volume > 0.0f) e.add_food(cell, a.carried_volume, a.carried_density);
  a.carried_volume = 0.0f;
  a.carried_density = 0.0f;

  e.deposit(a.species, Channel::Danger, cell, e.config().pheromone.death_alarm);

  Metrics& m = e.metrics();
  switch (cause) {
    case DeathCause::Combat: ++m.deaths_combat[a.species]; break;
    case DeathCause::Hazard: ++m.deaths_hazard[a.species]; break;
    case DeathCause::Age:    ++m.deaths_age[a.species]; break;
    case DeathCause::Orphan: ++m.deaths_orphan[a.species]; break;
  }
  if (killer_species >= 0 && killer_species < static_cast<int>(m.kills.size())) ++m.kills[killer_species];
}

}  // namespace formicae
