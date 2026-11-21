// io_checks.cpp - save/load round trips and corrupt-file handling (spec 9.3). Owner: P4.
// Same style as engine_smoke.cpp.
#undef NDEBUG  // keep assert() active in Release builds, the checks are the whole point
#include <cassert>
#include <cstdio>
#include <cstring>
#include <filesystem>
#include <fstream>
#include <iterator>
#include <stdexcept>
#include <string>
#include <vector>

#include "formicae/engine.hpp"

using namespace formicae;

namespace {

Config three_species_config() {
  Config cfg;
  SpeciesStats swarmer;
  SpeciesStats tank;
  tank.max_health = 60; tank.speed = 0.5f; tank.damage = 6; tank.armor = 2; tank.cost = 400;
  SpeciesStats nomad;
  nomad.max_health = 20; nomad.speed = 0.9f; nomad.random_move_prob = 0.2f; nomad.cost = 200;
  cfg.species = {{"Swarmer", swarmer}, {"Tank", tank}, {"Nomad", nomad}};
  cfg.sim_seed = 7;
  return cfg;
}

MapData test_map() {
  const int w = 64, h = 64;
  MapData m;
  m.width = w; m.height = h;
  const size_t n = static_cast<size_t>(w) * h;
  m.terrain.assign(n, static_cast<uint8_t>(Terrain::Grass));
  m.food_volume.assign(n, 0.0f);
  m.food_density.assign(n, 0.0f);
  for (int y = 0; y < h; ++y)
    for (int x = 0; x < w; ++x) {
      const size_t i = static_cast<size_t>(y) * w + x;
      if (x == 0 || y == 0 || x == w - 1 || y == h - 1) m.terrain[i] = static_cast<uint8_t>(Terrain::Rock);
      else if (x == 32 && y > 20 && y < 44) m.terrain[i] = static_cast<uint8_t>(Terrain::Thorns);
      else if ((x + y) % 17 == 0) { m.food_volume[i] = 120.0f; m.food_density[i] = 30.0f; }
    }
  m.colonies = {{12, 12, 0}, {50, 14, 1}, {30, 52, 2}};
  return m;
}

template <class T> bool same(const std::vector<T>& a, const std::vector<T>& b) {
  return a.size() == b.size() && (a.empty() || std::memcmp(a.data(), b.data(), a.size() * sizeof(T)) == 0);
}

// Bitwise comparison of everything observable through the public API.
bool same_state(const Engine& a, const Engine& b) {
  const Metrics& ma = a.metrics();
  const Metrics& mb = b.metrics();
  return a.tick() == b.tick() && same(a.ants(), b.ants()) && same(a.colonies(), b.colonies()) &&
         same(a.grid().terrain, b.grid().terrain) && same(a.grid().food_volume, b.grid().food_volume) &&
         same(a.grid().food_density, b.grid().food_density) && same(a.grid().occupancy, b.grid().occupancy) &&
         same(a.grid().hill_id, b.grid().hill_id) && same(a.grid().pher, b.grid().pher) &&
         same(ma.population, mb.population) && same(ma.births, mb.births) && same(ma.kills, mb.kills) &&
         same(ma.deaths_combat, mb.deaths_combat) && same(ma.deaths_hazard, mb.deaths_hazard) &&
         same(ma.deaths_age, mb.deaths_age) && same(ma.deaths_orphan, mb.deaths_orphan) &&
         same(ma.colonies_alive, mb.colonies_alive) && same(ma.deliveries, mb.deliveries) &&
         same(ma.return_steps_sum, mb.return_steps_sum) &&
         ma.food_total_volume == mb.food_total_volume && ma.food_total_energy == mb.food_total_energy;
}

std::string temp_path(const char* name) {
  return (std::filesystem::temp_directory_path() / name).string();
}

bool load_fails(const std::string& path) {
  try {
    (void)Engine::load(path);
  } catch (const std::invalid_argument&) {
    return true;
  }
  return false;
}

void write_bytes(const std::string& path, const std::vector<char>& bytes) {
  std::ofstream out(path, std::ios::binary | std::ios::trunc);
  out.write(bytes.data(), static_cast<std::streamsize>(bytes.size()));
}

void test_round_trip_continues_identically() {
  const std::string path = temp_path("formicae_io_round_trip.ants");
  Engine a(three_species_config());
  a.initialize(test_map());
  a.set_param("decay_scale", 1.5);  // runtime parameters belong to the snapshot as well
  a.set_param("nav_scale", 0.5);
  a.step(1100);  // past a compaction at tick 1000, so free slots and compacted storage are exercised
  assert(!a.ants().empty());
  a.save(path);

  Engine b = Engine::load(path);
  assert(same_state(a, b));
  assert(b.config().pheromone.decay_scale == 1.5f && b.config().movement.nav_scale == 0.5f);

  a.step(900);
  b.step(900);
  assert(same_state(a, b));
  Engine c = Engine::load(path);
  c.step(901);
  assert(!same_state(a, c));  // the comparison does detect a diverged run

  // reset() of a loaded engine goes back to the original map, like reset() of the saved one.
  a.reset();
  b.reset();
  assert(b.tick() == 0 && same_state(a, b));
  std::filesystem::remove(path);
}

void test_save_requires_initialize() {
  Engine e(three_species_config());
  bool threw = false;
  try {
    e.save(temp_path("formicae_io_uninitialized.ants"));
  } catch (const std::logic_error&) {
    threw = true;
  }
  assert(threw);
}

void test_rejects_bad_files() {
  const std::string good = temp_path("formicae_io_good.ants");
  const std::string bad = temp_path("formicae_io_bad.ants");
  Engine e(three_species_config());
  e.initialize(test_map());
  e.step(50);
  e.save(good);

  std::ifstream in(good, std::ios::binary);
  const std::vector<char> bytes{std::istreambuf_iterator<char>(in), std::istreambuf_iterator<char>()};
  in.close();

  assert(load_fails(temp_path("formicae_io_does_not_exist.ants")));

  std::vector<char> wrong_magic = bytes;
  wrong_magic[0] = 'X';
  write_bytes(bad, wrong_magic);
  assert(load_fails(bad));

  std::vector<char> wrong_version = bytes;
  wrong_version[4] = 99;
  write_bytes(bad, wrong_version);
  assert(load_fails(bad));

  write_bytes(bad, std::vector<char>(bytes.begin(), bytes.begin() + static_cast<long>(bytes.size() / 2)));
  assert(load_fails(bad));

  std::vector<char> trailing = bytes;
  trailing.push_back(0);
  write_bytes(bad, trailing);
  assert(load_fails(bad));

  // A failed save must not leave a temporary file behind or touch an existing snapshot.
  assert(!std::filesystem::exists(good + ".tmp"));
  std::filesystem::remove(good);
  std::filesystem::remove(bad);
}

}  // namespace

int main() {
  test_round_trip_continues_identically();
  test_save_requires_initialize();
  test_rejects_bad_files();
  std::puts("io_checks: OK");
  return 0;
}
