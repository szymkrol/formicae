// p3_checks.cpp - checks for M2 combat, colonies and food. Owner: P3. Same style as engine_smoke.cpp.
#undef NDEBUG  // keep assert() active in Release builds, the checks are the whole point
#include <cassert>
#include <cstdio>

#include "formicae/combat.hpp"
#include "formicae/engine.hpp"

using namespace formicae;

namespace {

Config two_species_config() {
  Config cfg;
  SpeciesStats swarmer;  // defaults = Swarmer
  SpeciesStats tank;
  tank.max_health = 60; tank.damage = 6; tank.armor = 2; tank.accuracy = 0.6f; tank.cost = 400;
  cfg.species = {{"Swarmer", swarmer}, {"Tank", tank}};
  return cfg;
}

MapData open_map(int w, int h) {
  MapData m;
  m.width = w; m.height = h;
  const size_t n = static_cast<size_t>(w) * h;
  m.terrain.assign(n, static_cast<uint8_t>(Terrain::Grass));
  m.food_volume.assign(n, 0.0f);
  m.food_density.assign(n, 0.0f);
  return m;
}

int food_cells(const Engine& e) {
  int n = 0;
  for (float v : e.grid().food_volume) n += v > 0.0f;
  return n;
}

void test_spawning() {
  Engine e(two_species_config());
  MapData m = open_map(64, 64);
  m.colonies = {{10, 10, 0}, {50, 50, 1}};
  e.initialize(m);

  // Swarmer: 600 energy / 60 cost, one ant every spawn_cooldown + 1 ticks, stops when energy is gone.
  e.step(200);
  assert(e.colonies()[0].population == 10);
  assert(e.colonies()[0].stored_energy < 60.0);
  // Tank: cost 400, only one affordable from 600.
  assert(e.colonies()[1].population == 1);
  assert(e.metrics().births[0] == 10 && e.metrics().births[1] == 1);
  // Spawned ants stand on their own footprint.
  for (const Ant& a : e.ants()) assert(e.grid().hill_at(e.grid().idx(a.x, a.y)) == a.colony);
}

void test_hill_full_postpones() {
  Config cfg = two_species_config();
  cfg.colony.hill_radius = 0;  // 1-cell footprint
  cfg.colony.initial_energy = 10000;
  Engine e(cfg);
  MapData m = open_map(16, 16);
  m.colonies = {{8, 8, 0}};
  e.initialize(m);
  e.step(50);
  assert(e.colonies()[0].population == 1);  // cell stays occupied -> no further spawn, energy kept
  assert(e.colonies()[0].stored_energy == 10000 - 60);
}

void test_combat_and_counters() {
  Engine e(two_species_config());
  MapData m = open_map(32, 32);
  m.colonies = {{4, 4, 0}, {28, 28, 1}};
  e.initialize(m);
  Grid& g = e.grid();

  const int a = e.spawn_ant(0, 0, g.idx(15, 15));  // swarmer
  const int w1 = e.spawn_ant(1, 0, g.idx(16, 15)); // wounded tank
  const int w2 = e.spawn_ant(1, 0, g.idx(15, 16)); // healthier tank
  e.ants()[w1].health = 5;
  e.ants()[w2].health = 20;
  Target t = find_target(e, a);
  assert(t.kind == Target::Kind::Ant && t.index == w1);  // lowest health wins

  // A friend and nothing else adjacent -> no target.
  const int friend_slot = e.spawn_ant(0, 0, g.idx(10, 10));
  (void)e.spawn_ant(0, 0, g.idx(11, 10));
  assert(find_target(e, friend_slot).kind == Target::Kind::None);

  // Keep hitting the wounded tank until dead. Armor 2 vs damage 2 -> min damage 0.5, so this is slow.
  int hits_guard = 0;
  while (is_alive(e.ants()[w1]) && hits_guard++ < 1000) resolve_attack(e, a, t);
  assert(!is_alive(e.ants()[w1]));
  assert(g.occupant(g.idx(16, 15)) == NO_ANT);

  e.ants()[w2].carried_volume = 3.0f;  // death drops the load
  e.ants()[w2].carried_density = 20.0f;
  e.kill_ant(w2, DeathCause::Hazard);
  const float danger_before = g.pher_at(1, static_cast<int>(Channel::Danger), g.idx(15, 16));
  e.step(1);
  assert(e.metrics().deaths_combat[1] == 1 && e.metrics().deaths_hazard[1] == 1);
  assert(e.metrics().kills[0] == 1);
  assert(g.food_volume[g.idx(15, 16)] == 3.0f && g.food_density[g.idx(15, 16)] == 20.0f);
  assert(g.pher_at(1, static_cast<int>(Channel::Danger), g.idx(15, 16)) > danger_before);
  (void)danger_before;
}

void test_hill_destruction() {
  Engine e(two_species_config());
  MapData m = open_map(32, 32);
  m.colonies = {{4, 4, 0}, {20, 20, 1}};
  e.initialize(m);
  Grid& g = e.grid();
  e.colonies()[1].stored_energy = 500;

  // Attacker on the edge of the enemy footprint (radius 2 -> footprint x in [18,22]).
  const int a = e.spawn_ant(0, 0, g.idx(17, 20));
  Target t = find_target(e, a);
  assert(t.kind == Target::Kind::Hill && t.index == 1);
  int guard = 0;
  while (e.colonies()[1].alive && guard++ < 100000) resolve_attack(e, a, t);
  assert(!e.colonies()[1].alive);
  assert(e.metrics().colonies_alive[1] == 0 && e.metrics().colonies_alive[0] == 1);
  assert(g.hill_at(g.idx(20, 20)) == NO_HILL && g.hill_at(g.idx(18, 18)) == NO_HILL);
  assert(g.food_volume[g.idx(20, 20)] == 500.0f / 25.0f && g.food_density[g.idx(20, 20)] == 25.0f);
  assert(e.colonies()[1].stored_energy == 0.0);
  assert(find_target(e, a).kind == Target::Kind::None);  // destroyed hill is no longer a target
  // Own species never targets its own hill.
  const int b = e.spawn_ant(0, 0, g.idx(7, 4));
  assert(find_target(e, b).kind == Target::Kind::None);
}

void test_food_spawning() {
  Config cfg = two_species_config();
  cfg.food.spawn_interval = 5;
  cfg.food.spawn_prob = 1.0f;
  cfg.food.max_food_cells = 300;
  auto run = [&](uint64_t seed) {
    cfg.sim_seed = seed;
    Engine e(cfg);
    MapData m = open_map(128, 128);
    m.colonies = {{10, 10, 0}};
    e.initialize(m);
    return e;
  };
  Engine a = run(5), b = run(5), c = run(6);
  a.step(500); b.step(500); c.step(500);
  assert(food_cells(a) > 0 && food_cells(a) <= 300);  // cap is strict
  assert(a.grid().food_volume == b.grid().food_volume && a.grid().food_density == b.grid().food_density);
  assert(a.grid().food_volume != c.grid().food_volume);  // different seed, different food
  for (int y = 8; y <= 12; ++y)
    for (int x = 8; x <= 12; ++x) assert(a.grid().food_volume[a.grid().idx(x, y)] == 0.0f);  // never on hills
  for (int i = 0; i < a.grid().cells(); ++i)
    if (a.grid().food_volume[i] > 0.0f) assert(a.grid().food_volume[i] >= 50.f && a.grid().food_density[i] >= 10.f && a.grid().food_density[i] <= 50.f);
}

}  // namespace

int main() {
  test_spawning();
  test_hill_full_postpones();
  test_combat_and_counters();
  test_hill_destruction();
  test_food_spawning();
  std::puts("p3_checks: OK");
  return 0;
}
