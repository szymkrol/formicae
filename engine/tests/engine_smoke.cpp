// engine_smoke.cpp - minimal C++ checks without a test framework. Owner: P1; extend as needed.
#include <cassert>
#include <cstdio>

#include "formicae/engine.hpp"

using namespace formicae;

int main() {
  static_assert(sizeof(Ant) == 40 && sizeof(ColonyRecord) == 32);

  Config cfg;
  cfg.species = {{"Swarmer", SpeciesStats{}}};
  Engine engine(cfg);

  MapData map;
  map.width = 32;
  map.height = 32;
  const size_t n = 32u * 32u;
  map.terrain.assign(n, static_cast<uint8_t>(Terrain::Grass));
  map.food_volume.assign(n, 0.0f);
  map.food_density.assign(n, 0.0f);
  map.colonies.push_back({16, 16, 0});
  engine.initialize(map);

  // Slot storage: spawn an ant on a free footprint cell, kill it, run the pipeline.
  const int cell = engine.grid().idx(16, 16);
  const int slot = engine.spawn_ant(0, 0, cell);
  assert(slot >= 0 && engine.grid().occupant(cell) == slot);
  engine.kill_ant(slot, DeathCause::Age);
  assert(engine.grid().occupant(cell) == NO_ANT);
  engine.step(10);
  assert(engine.tick() == 10);

  // Pheromone cap and decay.
  engine.deposit(0, Channel::Food, 0, 5.0f);
  assert(engine.grid().pher_at(0, static_cast<int>(Channel::Food), 0) == P_MAX);
  engine.step(1);
  assert(engine.grid().pher_at(0, static_cast<int>(Channel::Food), 0) < P_MAX);

  // Determinism: same seed, same random numbers.
  Rng a(7), b(7);
  for (int i = 0; i < 100; ++i) assert(a.next_u32() == b.next_u32());

  std::puts("engine_smoke: OK");
  return 0;
}
