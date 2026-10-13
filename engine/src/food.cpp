// food.cpp - food spawning and runtime food/terrain controls (spec sections 7.4, 9.3). Owner: P3 (M2).
#include <algorithm>
#include <stdexcept>

#include "antsim/engine.hpp"

namespace antsim {

void Engine::add_food(int cell, float volume, float density) {
  float& v = grid_.food_volume[cell];
  float& d = grid_.food_density[cell];
  const float total = v + volume;
  if (total <= 0.0f) return;
  d = (v * d + volume * density) / total;  // volume-weighted merge
  v = total;
}

int Engine::spawn_food(int x, int y, int radius, float volume, float density) {
  if (!grid_.in_bounds(x, y)) throw std::invalid_argument("spawn_food: cell out of bounds");
  if (radius < 0 || radius > 10) throw std::invalid_argument("spawn_food: radius must be 0..10");
  if (volume <= 0.0f || density <= 0.0f || density > 100.0f)
    throw std::invalid_argument("spawn_food: volume > 0 and 0 < density <= 100 required");
  int changed = 0;
  for (int dy = -radius; dy <= radius; ++dy)
    for (int dx = -radius; dx <= radius; ++dx) {
      if (dx * dx + dy * dy > radius * radius || !grid_.in_bounds(x + dx, y + dy)) continue;
      const int i = grid_.idx(x + dx, y + dy);
      if (!grid_.is_passable(i) || grid_.hill_at(i) != NO_HILL) continue;
      add_food(i, volume, density);
      ++changed;
    }
  return changed;
}

void Engine::set_terrain(int x, int y, Terrain t) {
  if (!grid_.in_bounds(x, y)) throw std::invalid_argument("set_terrain: cell out of bounds");
  const int i = grid_.idx(x, y);
  if (grid_.hill_at(i) != NO_HILL) throw std::invalid_argument("set_terrain: hill cell");
  const TerrainDef& def = cfg_.terrain[static_cast<int>(t)];
  if (!def.passable && grid_.occupancy[i] != NO_ANT) throw std::invalid_argument("set_terrain: cell is occupied");
  grid_.terrain[i] = static_cast<uint8_t>(t);
  grid_.move_cost[i] = def.move_cost;
  grid_.evap_mod[i] = def.evap_mod;
  grid_.hazard[i] = def.hazard_damage;
  grid_.passable[i] = def.passable ? 1 : 0;
}

void Engine::set_param(const std::string& name, double value) {
  auto in = [&](double lo, double hi) { if (value < lo || value > hi) throw std::invalid_argument("set_param: " + name + " out of range"); };
  if (name == "decay_scale") { in(0, 10); cfg_.pheromone.decay_scale = static_cast<float>(value); }
  else if (name == "diffusion") { in(0, 0.2); cfg_.pheromone.diffusion = static_cast<float>(value); }
  else if (name == "food_spawn_prob") { in(0, 1); cfg_.food.spawn_prob = static_cast<float>(value); }
  else if (name == "food_spawn_interval") { in(1, 10000); cfg_.food.spawn_interval = static_cast<int>(value); }
  else throw std::invalid_argument("set_param: unknown parameter " + name);
}

void Engine::spawn_food_step() {
  // TODO(P3): every cfg_.food.spawn_interval ticks, with probability cfg_.food.spawn_prob, place a
  // cluster (radius, volume, density per spec 7.4) at a random passable non-hill cell, respecting
  // cfg_.food.max_food_cells. Use rng_ only, so runs stay deterministic.
}

}  // namespace antsim
