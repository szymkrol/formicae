// invariant_checks.cpp - whole-engine invariants, determinism, long-run stability and the stretch
// features (castes, heatmaps, friendly swap). Owners: P1 (invariants, determinism), P4 (CI).
// Same style as engine_smoke.cpp.
#undef NDEBUG  // keep assert() active in Release builds, the checks are the whole point
#include <cassert>
#include <cmath>
#include <cstdio>
#include <cstring>
#include <filesystem>
#include <vector>

#include "formicae/ai.hpp"
#include "formicae/engine.hpp"

using namespace formicae;

namespace {

Config base_config(uint64_t seed = 7) {
  Config cfg;
  SpeciesStats swarmer;
  SpeciesStats tank;
  tank.max_health = 60; tank.speed = 0.5f; tank.damage = 6; tank.armor = 2; tank.cost = 400;
  tank.flee_threshold = 0; tank.defend_while_carrying = true; tank.carry_capacity = 6;
  SpeciesStats nomad;
  nomad.max_health = 20; nomad.speed = 0.9f; nomad.random_move_prob = 0.2f; nomad.cost = 200;
  nomad.flee_threshold = 0.5f; nomad.carry_capacity = 4; nomad.danger_k = 2.0f;
  cfg.species = {{"Swarmer", swarmer}, {"Tank", tank}, {"Nomad", nomad}};
  cfg.colony.initial_energy = 3000;
  cfg.sim_seed = seed;
  return cfg;
}

// The castes planned in spec 5.2, for every species.
std::vector<CasteDef> planned_castes() {
  CasteDef standard;
  CasteDef explorer;
  explorer.name = "EXPLORER"; explorer.random_move_prob_add = 0.15f; explorer.a_home_mul = 0.5f;
  explorer.a_food_mul = 0.5f; explorer.max_health_mul = 0.8f; explorer.carry_mul = 0.5f;
  explorer.cost_mul = 0.8f;
  CasteDef gatherer;
  gatherer.name = "GATHERER"; gatherer.carry_mul = 1.5f; gatherer.speed_mul = 0.9f;
  gatherer.damage_mul = 0.5f; gatherer.defend_while_carrying = 0;
  CasteDef fighter;
  fighter.name = "FIGHTER"; fighter.carry_mul = 0.0f; fighter.damage_mul = 1.5f;
  fighter.max_health_mul = 1.5f; fighter.danger_k_add = -1.0f; fighter.cost_mul = 1.5f;
  return {standard, explorer, gatherer, fighter};
}

Config stress_config() {
  Config cfg = base_config();
  cfg.castes.assign(cfg.species.size(), planned_castes());
  for (auto& s : cfg.species) s.caste_ratio = {0.4f, 0.2f, 0.25f, 0.15f};
  cfg.enable_heatmaps = true;
  cfg.movement.friendly_swap = true;
  return cfg;
}

// 96 x 96 world with a rock border, a water lake, a thorn strip and food fields. The hills are
// placed so that the three species meet and fight within a few thousand ticks.
MapData world_map(int w = 96, int h = 96) {
  MapData m;
  m.width = w; m.height = h;
  const size_t n = static_cast<size_t>(w) * h;
  m.terrain.assign(n, static_cast<uint8_t>(Terrain::Grass));
  m.food_volume.assign(n, 0.0f);
  m.food_density.assign(n, 0.0f);
  for (int y = 0; y < h; ++y)
    for (int x = 0; x < w; ++x) {
      const size_t i = static_cast<size_t>(y) * w + x;
      auto set = [&](Terrain t) { m.terrain[i] = static_cast<uint8_t>(t); };
      if (x == 0 || y == 0 || x == w - 1 || y == h - 1) set(Terrain::Rock);
      else if ((x - w / 2) * (x - w / 2) + (y - h / 2) * (y - h / 2) < 36) set(Terrain::Water);
      else if (x == w / 3 && y > 10 && y < h - 30) set(Terrain::Thorns);
      else if (y == h - 12) set(Terrain::Path);
      else if (x > w - 25 && y < 20) set(Terrain::Mud);
      else if (x < 18 && y > h - 25) set(Terrain::Sand);
      if (m.terrain[i] == static_cast<uint8_t>(Terrain::Grass) && (x * 7 + y * 3) % 23 == 0) {
        m.food_volume[i] = 150.0f;
        m.food_density[i] = 10.0f + static_cast<float>((x + y) % 40);
      }
    }
  m.colonies = {{w / 4, h * 5 / 12, 0}, {w * 3 / 4, h * 5 / 12, 1}, {w / 2, h * 73 / 100, 2}};
  return m;
}

void check_invariants(const Engine& e) {
  const Grid& g = e.grid();
  const Metrics& m = e.metrics();
  const int S = g.S;
  const auto& ants = e.ants();
  const auto& colonies = e.colonies();

  std::vector<int64_t> live(S, 0), live_caste(static_cast<size_t>(S) * MAX_CASTES, 0);
  std::vector<uint32_t> live_colony(colonies.size(), 0);
  int alive = 0;
  for (size_t slot = 0; slot < ants.size(); ++slot) {
    const Ant& a = ants[slot];
    if (!is_alive(a)) continue;
    ++alive;
    assert(a.species < S && a.colony < colonies.size());
    assert(a.caste < e.species_table().caste_count(a.species));
    assert(g.in_bounds(a.x, a.y) && g.is_passable(g.idx(a.x, a.y)));
    assert(g.occupant(g.idx(a.x, a.y)) == static_cast<int>(slot));
    const int hill = g.hill_at(g.idx(a.x, a.y));
    assert(hill == NO_HILL || colonies[hill].species == a.species);  // never inside an enemy hill
    const ResolvedStats& st = e.stats_of(a);
    assert(a.health > 0.0f && a.health <= st.max_health);
    assert(a.carried_volume >= 0.0f && a.carried_volume <= st.carry_capacity + 1e-4f);
    assert(a.state <= static_cast<uint8_t>(AntState::Fleeing));
    assert(a.move_acc >= 0.0f && a.move_acc <= 2.0f);
    assert(a.age < st.max_age);
    ++live[a.species];
    ++live_caste[static_cast<size_t>(a.species) * MAX_CASTES + a.caste];
    ++live_colony[a.colony];
  }

  int occupied = 0;
  for (int i = 0; i < g.cells(); ++i) {
    const int o = g.occupant(i);
    if (o != NO_ANT) {
      ++occupied;
      assert(o < static_cast<int>(ants.size()) && is_alive(ants[o]));
    }
    assert(std::isfinite(g.food_volume[i]) && g.food_volume[i] >= 0.0f);
    assert(std::isfinite(g.food_density[i]) && g.food_density[i] >= 0.0f);
    const int h = g.hill_at(i);
    assert(h == NO_HILL || colonies[h].alive);  // destroyed colonies leave no footprint
  }
  assert(occupied == alive);
  for (float p : g.pher) assert(std::isfinite(p) && p >= 0.0f && p <= P_MAX);

  for (int s = 0; s < S; ++s) {
    const int64_t deaths = m.deaths_combat[s] + m.deaths_hazard[s] + m.deaths_age[s] +
                           m.deaths_orphan[s];
    assert(m.population[s] == live[s]);
    assert(m.births[s] - deaths == m.population[s]);
    int64_t by_caste = 0;
    for (int c = 0; c < MAX_CASTES; ++c) {
      const size_t k = static_cast<size_t>(s) * MAX_CASTES + c;
      assert(m.population_caste[k] == live_caste[k]);
      by_caste += m.population_caste[k];
    }
    assert(by_caste == m.population[s]);
    int64_t alive_colonies = 0;
    for (const ColonyRecord& c : colonies) alive_colonies += c.alive && c.species == s;
    assert(m.colonies_alive[s] == alive_colonies);
    for (const auto* v : {&m.births, &m.kills, &m.deaths_combat, &m.deaths_hazard, &m.deaths_age,
                          &m.deaths_orphan, &m.deliveries, &m.return_steps_sum})
      assert((*v)[s] >= 0);
  }
  for (size_t c = 0; c < colonies.size(); ++c) {
    assert(colonies[c].population == live_colony[c]);
    assert(colonies[c].stored_energy >= 0.0);
    assert(!colonies[c].alive || colonies[c].health > 0.0f);
  }
  assert(std::isfinite(m.food_total_volume) && m.food_total_volume >= 0.0);
}

void test_invariants_hold_throughout_a_run() {
  for (const Config& cfg : {base_config(), stress_config()}) {
    Engine e(cfg);
    e.initialize(world_map());
    check_invariants(e);
    int64_t fights = 0;
    for (int k = 0; k < 60; ++k) {
      e.step(50);
      check_invariants(e);
    }
    for (int s = 0; s < 3; ++s) fights += e.metrics().deaths_combat[s];
    assert(e.metrics().births[0] > 0 && fights > 0);  // the run really exercises combat
  }
}

void test_same_seed_same_hash() {
  Engine a(stress_config()), b(stress_config());
  Config other_seed = stress_config();
  other_seed.sim_seed = 8;
  Engine c(other_seed);
  for (Engine* e : {&a, &b, &c}) e->initialize(world_map());
  const uint64_t start = a.state_hash();
  for (int k = 0; k < 10; ++k) {
    a.step(100);
    b.step(100);
    c.step(100);
    assert(a.state_hash() == b.state_hash());
    assert(a.state_hash() != c.state_hash());
  }
  a.reset();
  assert(a.state_hash() == start);  // reset() restores the initial state exactly

  const std::string path = (std::filesystem::temp_directory_path() / "formicae_hash.ants").string();
  b.save(path);
  Engine loaded = Engine::load(path);
  assert(loaded.state_hash() == b.state_hash());
  loaded.step(250);
  b.step(250);
  assert(loaded.state_hash() == b.state_hash());
  std::filesystem::remove(path);

  b.set_param("grad_beta", 3.0);  // runtime parameters are part of the state
  assert(loaded.state_hash() != b.state_hash());
}

template <class T> bool same(const std::vector<T>& x, const std::vector<T>& y) {
  return x.size() == y.size() && std::memcmp(x.data(), y.data(), x.size() * sizeof(T)) == 0;
}

// Spec 5.2 acceptance: castes defined but the default ratio [1, 0, 0, 0] give a bit-identical run.
// Heatmap counters must not influence the simulation either.
void test_castes_and_heatmaps_do_not_change_default_runs() {
  Config plain = base_config();
  Config with_castes = base_config();
  with_castes.castes.assign(with_castes.species.size(), planned_castes());
  with_castes.enable_heatmaps = true;
  Engine a(plain), b(with_castes);
  a.initialize(world_map());
  b.initialize(world_map());
  a.step(1500);
  b.step(1500);
  assert(same(a.ants(), b.ants()) && same(a.grid().pher, b.grid().pher));
  assert(same(a.colonies(), b.colonies()) && same(a.metrics().deaths_combat, b.metrics().deaths_combat));
  assert(a.grid().traffic.empty() && !b.grid().traffic.empty());
}

void test_castes_spawn_by_ratio() {
  Engine e(stress_config());
  e.initialize(world_map());
  e.step(400);
  const Metrics& m = e.metrics();
  for (int c = 0; c < MAX_CASTES; ++c) assert(m.population_caste[c] > 0);  // Swarmers: all four
  // FIGHTERs never carry food (carry_mul = 0).
  for (const Ant& a : e.ants())
    if (is_alive(a) && a.caste == 3) assert(a.carried_volume == 0.0f);
}

void test_heatmaps_count_traffic_and_hits() {
  Engine e(stress_config());
  e.initialize(world_map());
  e.step(3000);
  uint64_t traffic = 0, hits = 0;
  for (uint32_t v : e.grid().traffic) traffic += v;
  for (uint32_t v : e.grid().combat) hits += v;
  assert(traffic > 0 && hits > 0);
  // Water is never entered.
  const Grid& g = e.grid();
  for (int i = 0; i < g.cells(); ++i)
    if (g.terrain[i] == static_cast<uint8_t>(Terrain::Water)) assert(g.traffic[i] == 0);
  e.reset();
  for (uint32_t v : e.grid().traffic) assert(v == 0);
}

// Two Swarmers meet head-on in a 1-cell corridor; the first one is boxed in from behind.
void test_friendly_swap() {
  for (bool swap : {false, true}) {
    Config cfg = base_config();
    cfg.movement.friendly_swap = swap;
    Engine e(cfg);
    MapData m = world_map(32, 32);
    for (int y = 3; y <= 7; ++y)
      for (int x = 1; x <= 12; ++x)
        m.terrain[static_cast<size_t>(y) * 32 + x] =
            static_cast<uint8_t>(y == 5 ? Terrain::Grass : Terrain::Rock);
    for (float& v : m.food_volume) v = 0.0f;
    for (float& d : m.food_density) d = 0.0f;
    e.initialize(m);
    Grid& g = e.grid();
    const int behind = e.spawn_ant(0, 0, g.idx(3, 5));
    const int a = e.spawn_ant(0, 0, g.idx(4, 5));
    const int b = e.spawn_ant(0, 0, g.idx(5, 5));
    e.ants()[behind].last_dir = static_cast<int8_t>(Dir::E);
    e.ants()[a].last_dir = static_cast<int8_t>(Dir::E);
    e.ants()[b].last_dir = static_cast<int8_t>(Dir::W);
    for (int s : {a, b}) e.ants()[s].move_acc = 1.0f;

    ant_update(e, a);
    if (swap) {
      assert(e.ants()[a].x == 5 && e.ants()[b].x == 4);
      assert(g.occupant(g.idx(5, 5)) == a && g.occupant(g.idx(4, 5)) == b);
      assert(e.ants()[a].last_dir == static_cast<int8_t>(Dir::E));
    } else {
      assert(e.ants()[a].x == 4 && e.ants()[b].x == 5);  // stuck: waits for space
    }
    check_invariants(e);
  }
}

// Spec 13.2 (P1): no growth over long runs. Ant storage never reallocates (reserved at
// initialize), the slot array stays bounded and compaction keeps it tight.
void test_long_run_is_bounded() {
  Config cfg = stress_config();
  cfg.max_ants_total = 3000;
  Engine e(cfg);
  e.initialize(world_map(64, 64));
  const size_t capacity = e.ants().capacity();
  const Ant* storage = e.ants().data();
  size_t largest = 0;
  for (int k = 0; k < 20; ++k) {
    e.step(1000);
    check_invariants(e);
    largest = std::max(largest, e.ants().size());
    assert(e.ants().capacity() == capacity && e.ants().data() == storage);
    assert(e.ants().size() <= static_cast<size_t>(cfg.max_ants_total));
  }
  // Right after a compaction (every 1000 ticks) no dead slot is left behind the last live ant.
  assert(e.ants().empty() || is_alive(e.ants().back()));
  assert(largest > 0 && e.tick() == 20000);
}

}  // namespace

int main() {
  test_invariants_hold_throughout_a_run();
  test_same_seed_same_hash();
  test_castes_and_heatmaps_do_not_change_default_runs();
  test_castes_spawn_by_ratio();
  test_heatmaps_count_traffic_and_hits();
  test_friendly_swap();
  test_long_run_is_bounded();
  std::puts("invariant_checks: OK");
  return 0;
}
