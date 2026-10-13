// engine.hpp - the simulation engine: tick pipeline, ant slots, runtime controls (spec sections 3, 9).
// Owner: P1 (M1). M2 code receives an Engine& and may only use the public API below.
#pragma once
#include <cstdint>
#include <string>
#include <vector>

#include "formicae/ant.hpp"
#include "formicae/colony.hpp"
#include "formicae/config.hpp"
#include "formicae/grid.hpp"
#include "formicae/rng.hpp"
#include "formicae/species.hpp"
#include "formicae/types.hpp"

namespace formicae {

// Input of Engine::initialize (spec 8.3). Arrays are row-major [H, W].
struct MapData {
  struct Hill { int x, y, species; };
  int width = 0, height = 0;
  std::vector<uint8_t> terrain;
  std::vector<float> food_volume, food_density;
  std::vector<Hill> colonies;
};

// Counters exposed as metrics() (spec 9.3). All vectors have one entry per species.
struct Metrics {
  uint64_t tick = 0;
  std::vector<int64_t> population, births, kills;
  std::vector<int64_t> deaths_combat, deaths_hazard, deaths_age, deaths_orphan;
  std::vector<int64_t> colonies_alive;
  double food_total_volume = 0, food_total_energy = 0;
  void resize(int species);
};

class Engine {
 public:
  explicit Engine(Config cfg);

  // --- lifecycle (I1) -----------------------------------------------------------------------
  void initialize(const MapData& map);      // copies the map, builds derived layers, places hills
  void reset();                             // back to the state right after initialize()
  uint64_t step(int n = 1);                 // runs n ticks, returns the new tick number
  uint64_t tick() const { return tick_; }
  bool initialized() const { return initialized_; }

  // --- runtime controls (I4); throw std::invalid_argument on bad input -----------------------
  void set_param(const std::string& name, double value);  // decay_scale, diffusion, food_spawn_prob, food_spawn_interval
  int spawn_food(int x, int y, int radius, float volume, float density);  // returns cells changed
  void set_terrain(int x, int y, Terrain t);

  // --- state access (I2/I3) ------------------------------------------------------------------
  const Config& config() const { return cfg_; }
  Grid& grid() { return grid_; }
  const Grid& grid() const { return grid_; }
  std::vector<Ant>& ants() { return ants_; }                  // all slots; state == Dead marks free ones
  const std::vector<Ant>& ants() const { return ants_; }
  std::vector<ColonyRecord>& colonies() { return colonies_; }
  const std::vector<ColonyRecord>& colonies() const { return colonies_; }
  ColonyExtra& colony_extra(int i) { return colony_extra_[i]; }
  const SpeciesTable& species_table() const { return species_table_; }
  const ResolvedStats& stats_of(const Ant& a) const { return species_table_.get(a.species, a.caste); }
  Rng& rng() { return rng_; }
  Metrics& metrics() { return metrics_; }
  const Metrics& metrics() const { return metrics_; }
  bool hostile(int species_a, int species_b) const { return cfg_.hostile[species_a][species_b]; }

  // --- ant and food helpers used by M2 -------------------------------------------------------
  // Creates an ant of `colony` on free cell `cell`; returns its slot or -1 (cap reached / cell taken).
  int spawn_ant(int colony, int caste, int cell);
  // Marks the ant dead now (state = Dead, cell freed) and queues on_ant_death() for pipeline step 4.
  void kill_ant(int slot, DeathCause cause, int killer_species = -1);
  // Adds food to a cell, merging density volume-weighted.
  void add_food(int cell, float volume, float density);
  void deposit(int species, Channel ch, int cell, float amount) { grid_.deposit(species, static_cast<int>(ch), cell, amount); }

 private:
  struct PendingDeath { int slot; DeathCause cause; int killer_species; };

  // Pipeline steps of spec section 3.
  void spawn_food_step();      // 1  P3: dynamic food spawning (7.4)
  void colony_phase();         // 2  calls colony_update() for every live colony
  void ant_phase();            // 3  calls ant_update() for every live ant, direction alternates
  void cleanup_dead();         // 4  calls on_ant_death(), frees slots
  void pheromone_update();     // 5  P1: optional diffusion, then decay
  void update_metrics();       // 6

  void build_derived_layers();
  void place_hills(const std::vector<MapData::Hill>& hills);

  Config cfg_;
  Grid grid_;
  SpeciesTable species_table_;
  Rng rng_;
  Metrics metrics_;
  std::vector<Ant> ants_;
  std::vector<int> free_slots_;
  std::vector<PendingDeath> pending_deaths_;
  std::vector<ColonyRecord> colonies_;
  std::vector<ColonyExtra> colony_extra_;
  MapData initial_map_;        // kept for reset()
  uint64_t tick_ = 0;
  uint32_t next_ant_id_ = 0;
  bool initialized_ = false;
};

}  // namespace formicae
