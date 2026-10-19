// colony.cpp - colony lifecycle (spec sections 7.2, 7.3). Owner: P3 (M2).
#include "formicae/colony.hpp"

#include <algorithm>

#include "formicae/engine.hpp"

namespace formicae {

namespace {

// Picks a caste index according to caste_ratio, restricted to the castes the species really has.
// Draws from the RNG only when there is an actual choice, so single-caste runs stay unaffected.
int pick_caste(Engine& e, const ColonyRecord& colony, const ColonyExtra& extra) {
  const int castes = e.species_table().caste_count(colony.species);
  if (castes <= 1) return 0;

  float total = 0.0f;
  for (int c = 0; c < castes; ++c) total += std::max(0.0f, extra.caste_ratio[c]);
  if (total <= 0.0f) return 0;

  float roll = e.rng().next_float() * total;
  for (int c = 0; c < castes; ++c) {
    roll -= std::max(0.0f, extra.caste_ratio[c]);
    if (roll < 0.0f) return c;
  }
  return castes - 1;  // float rounding at the upper edge
}

// First free footprint cell, scanning from a random offset (spec 7.2). -1 when the hill is full.
int find_free_footprint_cell(Engine& e, int colony_index) {
  const Grid& g = e.grid();
  const ColonyRecord& colony = e.colonies()[colony_index];
  const int r = e.config().colony.hill_radius;
  const int side = 2 * r + 1;
  const int total = side * side;

  const int offset = e.rng().next_int(total);
  for (int k = 0; k < total; ++k) {
    const int n = (offset + k) % total;
    const int x = colony.x - r + n % side;
    const int y = colony.y - r + n / side;
    if (!g.in_bounds(x, y)) continue;
    const int cell = g.idx(x, y);
    // hill_at() check: footprints of two colonies may overlap or be clipped by the map edge.
    if (g.hill_at(cell) == colony_index && g.is_passable(cell) && g.occupant(cell) == NO_ANT) return cell;
  }
  return -1;
}

}  // namespace

void colony_update(Engine& e, int colony) {
  ColonyExtra& extra = e.colony_extra(colony);
  if (extra.spawn_cooldown > 0) {
    --extra.spawn_cooldown;
    return;
  }

  ColonyRecord& c = e.colonies()[colony];
  const ColonyParams& params = e.config().colony;
  if (c.population >= params.max_population) return;

  const int caste = pick_caste(e, c, extra);
  const float cost = e.species_table().get(c.species, static_cast<uint8_t>(caste)).cost;
  if (c.stored_energy < cost) return;

  const int cell = find_free_footprint_cell(e, colony);
  if (cell < 0) return;  // hill is full: postpone, no cooldown is started

  if (e.spawn_ant(colony, caste, cell) < 0) return;  // global ant cap reached: postpone
  c.stored_energy -= cost;
  extra.spawn_cooldown = static_cast<uint8_t>(std::clamp(params.spawn_cooldown, 0, 255));
}

void on_colony_destroyed(Engine& e, int colony) {
  Grid& g = e.grid();
  ColonyRecord& c = e.colonies()[colony];
  if (!c.alive) return;  // already handled (two attackers killing it in the same tick)

  c.alive = 0;
  c.health = 0.0f;

  // Clear only cells that still belong to this colony (footprints may overlap).
  const int r = e.config().colony.hill_radius;
  for (int dy = -r; dy <= r; ++dy)
    for (int dx = -r; dx <= r; ++dx) {
      if (!g.in_bounds(c.x + dx, c.y + dy)) continue;
      const int cell = g.idx(c.x + dx, c.y + dy);
      if (g.hill_at(cell) == colony) g.hill_id[cell] = NO_HILL;
    }

  // Stored energy becomes loot on the center cell for the enemy to carry away.
  const float loot_density = e.config().colony.loot_density;
  if (c.stored_energy > 0.0 && loot_density > 0.0f)
    e.add_food(g.idx(c.x, c.y), static_cast<float>(c.stored_energy / loot_density), loot_density);
  c.stored_energy = 0.0;

  --e.metrics().colonies_alive[c.species];
}

}  // namespace formicae
