// engine.cpp - lifecycle, tick pipeline, ant slots. Owner: P1 (M1).
#include "antsim/engine.hpp"

#include <algorithm>
#include <stdexcept>

#include "antsim/ai.hpp"
#include "antsim/colony.hpp"
#include "antsim/combat.hpp"

namespace antsim {

void Metrics::resize(int species) {
  for (auto* v : {&population, &births, &kills, &deaths_combat, &deaths_hazard, &deaths_age,
                  &deaths_orphan, &colonies_alive})
    v->assign(species, 0);
}

Engine::Engine(Config cfg) : cfg_(std::move(cfg)) {
  cfg_.apply_defaults();
  cfg_.validate();
  species_table_.build(cfg_);
  rng_.reseed(cfg_.sim_seed);
  metrics_.resize(static_cast<int>(cfg_.species.size()));
}

void Engine::initialize(const MapData& map) {
  if (map.width <= 0 || map.height <= 0) throw std::invalid_argument("map size must be positive");
  const size_t n = static_cast<size_t>(map.width) * map.height;
  if (map.terrain.size() != n || map.food_volume.size() != n || map.food_density.size() != n)
    throw std::invalid_argument("map arrays must have width * height elements");
  initial_map_ = map;

  grid_.allocate(map.width, map.height, static_cast<int>(cfg_.species.size()));
  grid_.terrain = map.terrain;
  grid_.food_volume = map.food_volume;
  grid_.food_density = map.food_density;
  build_derived_layers();

  ants_.clear();
  ants_.reserve(static_cast<size_t>(cfg_.max_ants_total));
  free_slots_.clear();
  pending_deaths_.clear();
  next_ant_id_ = 0;
  tick_ = 0;
  rng_.reseed(cfg_.sim_seed);
  metrics_.resize(static_cast<int>(cfg_.species.size()));
  place_hills(map.colonies);
  update_metrics();
  initialized_ = true;
}

void Engine::reset() {
  if (!initialized_) throw std::logic_error("engine is not initialized");
  const MapData copy = initial_map_;
  initialize(copy);
}

void Engine::build_derived_layers() {
  const int n = grid_.cells();
  for (int i = 0; i < n; ++i) {
    const TerrainDef& t = cfg_.terrain[grid_.terrain[i]];
    grid_.move_cost[i] = t.move_cost;
    grid_.evap_mod[i] = t.evap_mod;
    grid_.hazard[i] = t.hazard_damage;
    grid_.passable[i] = t.passable ? 1 : 0;
  }
}

void Engine::place_hills(const std::vector<MapData::Hill>& hills) {
  colonies_.clear();
  colony_extra_.clear();
  const int r = cfg_.colony.hill_radius;
  for (const auto& h : hills) {
    ColonyRecord c{};
    c.stored_energy = cfg_.colony.initial_energy;
    c.health = c.max_health = cfg_.colony.max_health;
    c.population = 0;
    c.x = static_cast<int16_t>(h.x);
    c.y = static_cast<int16_t>(h.y);
    c.species = static_cast<uint8_t>(h.species);
    c.alive = 1;
    const int idx = static_cast<int>(colonies_.size());
    colonies_.push_back(c);
    colony_extra_.emplace_back();
    metrics_.colonies_alive[h.species] += 1;
    for (int dy = -r; dy <= r; ++dy)
      for (int dx = -r; dx <= r; ++dx)
        if (grid_.in_bounds(h.x + dx, h.y + dy))
          grid_.hill_id[grid_.idx(h.x + dx, h.y + dy)] = static_cast<int16_t>(idx);
  }
}

uint64_t Engine::step(int n) {
  if (!initialized_) throw std::logic_error("engine is not initialized");
  for (int k = 0; k < n; ++k) {
    spawn_food_step();    // 1
    colony_phase();       // 2
    ant_phase();          // 3
    cleanup_dead();       // 4
    pheromone_update();   // 5
    update_metrics();     // 6
    ++tick_;
  }
  return tick_;
}

void Engine::colony_phase() {
  for (int c = 0; c < static_cast<int>(colonies_.size()); ++c)
    if (colonies_[c].alive) colony_update(*this, c);
}

void Engine::ant_phase() {
  // Sequential, in place; direction alternates every tick to avoid order bias (spec section 3).
  const int count = static_cast<int>(ants_.size());
  if (tick_ % 2 == 0) {
    for (int s = 0; s < count; ++s)
      if (is_alive(ants_[s])) ant_update(*this, s);
  } else {
    for (int s = count - 1; s >= 0; --s)
      if (is_alive(ants_[s])) ant_update(*this, s);
  }
}

void Engine::cleanup_dead() {
  for (const PendingDeath& d : pending_deaths_) {
    on_ant_death(*this, d.slot, d.cause, d.killer_species);
    free_slots_.push_back(d.slot);
  }
  pending_deaths_.clear();
  // TODO(P1): every 1000 ticks compact the slot array and rebuild occupancy (spec section 3).
}

void Engine::update_metrics() {
  metrics_.tick = tick_;
  // TODO(P1): food_total_volume / food_total_energy (sum over the map, maybe every 10 ticks).
}

int Engine::spawn_ant(int colony, int caste, int cell) {
  if (grid_.occupancy[cell] != NO_ANT || !grid_.is_passable(cell)) return -1;
  int slot;
  if (!free_slots_.empty()) {
    slot = free_slots_.back();
    free_slots_.pop_back();
  } else {
    if (static_cast<int>(ants_.size()) >= cfg_.max_ants_total) return -1;
    slot = static_cast<int>(ants_.size());
    ants_.emplace_back();
  }
  const ColonyRecord& col = colonies_[colony];
  Ant& a = ants_[slot];
  a = Ant{};
  a.id = next_ant_id_++;
  a.x = static_cast<int16_t>(grid_.x_of(cell));
  a.y = static_cast<int16_t>(grid_.y_of(cell));
  a.colony = static_cast<uint16_t>(colony);
  a.species = col.species;
  a.caste = static_cast<uint8_t>(caste);
  a.state = static_cast<uint8_t>(AntState::Searching);
  a.last_dir = static_cast<int8_t>(Dir::None);
  a.health = species_table_.get(a.species, a.caste).max_health;
  grid_.occupancy[cell] = slot;
  colonies_[colony].population += 1;
  metrics_.population[a.species] += 1;
  metrics_.births[a.species] += 1;
  return slot;
}

void Engine::kill_ant(int slot, DeathCause cause, int killer_species) {
  Ant& a = ants_[slot];
  if (!is_alive(a)) return;
  grid_.occupancy[grid_.idx(a.x, a.y)] = NO_ANT;
  colonies_[a.colony].population -= 1;
  metrics_.population[a.species] -= 1;
  // The ant keeps x, y, species, carried_* until on_ant_death() ran (pipeline step 4).
  a.state = static_cast<uint8_t>(AntState::Dead);
  pending_deaths_.push_back({slot, cause, killer_species});
}

}  // namespace antsim
