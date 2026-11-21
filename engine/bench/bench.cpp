// bench.cpp - headless engine benchmark (spec 3 performance targets, 13.2 P1). Owner: P1.
//
//   formicae_bench                       both reference presets
//   formicae_bench --preset small        10k ants on 512 x 512   (target >= 300 ticks/s)
//   formicae_bench --preset large        100k ants on 1024 x 1024 (target >= 30 ticks/s)
//   formicae_bench --width 256 --height 256 --ants 5000 --ticks 2000 [--diffusion 0.03]
//                  [--heatmaps] [--seed 7]
//
// Targets are for planning, not pass/fail: the exit code is 0 whenever the run completes. The
// report also shows peak memory and whether the ant storage reallocated (it never should).
#include <chrono>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <string>
#include <vector>

#if defined(__unix__) || defined(__APPLE__)
#include <sys/resource.h>
#endif

#include "formicae/engine.hpp"

using namespace formicae;

namespace {

struct Options {
  const char* name = "custom";
  int width = 512, height = 512, ants = 10000, ticks = 1000;
  float diffusion = 0.03f;
  bool heatmaps = false;
  uint64_t seed = 7;
  double target_tps = 0.0;  // 0 = no reference target
};

Options preset(const std::string& name) {
  Options o;
  if (name == "small") {
    o.name = "small"; o.width = o.height = 512; o.ants = 10000; o.ticks = 1000; o.target_tps = 300;
  } else if (name == "large") {
    o.name = "large"; o.width = o.height = 1024; o.ants = 100000; o.ticks = 200; o.target_tps = 30;
  } else {
    std::fprintf(stderr, "unknown preset '%s' (small, large)\n", name.c_str());
    std::exit(2);
  }
  return o;
}

long peak_rss_kb() {
#if defined(__unix__) || defined(__APPLE__)
  rusage usage{};
  getrusage(RUSAGE_SELF, &usage);
#if defined(__APPLE__)
  return usage.ru_maxrss / 1024;  // bytes on macOS
#else
  return usage.ru_maxrss;         // kilobytes on Linux
#endif
#else
  return -1;
#endif
}

// Open grassland with a rock border, scattered rock and mud patches, food fields and one hill per
// species in each quadrant (3 species, 4 hills).
MapData bench_map(int w, int h) {
  MapData m;
  m.width = w; m.height = h;
  const size_t n = static_cast<size_t>(w) * h;
  m.terrain.assign(n, static_cast<uint8_t>(Terrain::Grass));
  m.food_volume.assign(n, 0.0f);
  m.food_density.assign(n, 0.0f);
  for (int y = 0; y < h; ++y)
    for (int x = 0; x < w; ++x) {
      const size_t i = static_cast<size_t>(y) * w + x;
      if (x == 0 || y == 0 || x == w - 1 || y == h - 1 || (x / 16 + y / 16) % 13 == 0)
        m.terrain[i] = static_cast<uint8_t>(Terrain::Rock);
      else if ((x / 32 + 3 * (y / 32)) % 7 == 0)
        m.terrain[i] = static_cast<uint8_t>(Terrain::Mud);
      else if ((x * 13 + y * 7) % 97 == 0) {
        m.food_volume[i] = 150.0f;
        m.food_density[i] = 30.0f;
      }
    }
  const int qx = w / 4, qy = h / 4;
  m.colonies = {{qx, qy, 0}, {3 * qx, qy, 1}, {qx, 3 * qy, 2}, {3 * qx, 3 * qy, 0}};
  for (const auto& hill : m.colonies)
    for (int dy = -4; dy <= 4; ++dy)
      for (int dx = -4; dx <= 4; ++dx)
        m.terrain[static_cast<size_t>(hill.y + dy) * w + hill.x + dx] =
            static_cast<uint8_t>(Terrain::Grass);
  return m;
}

Config bench_config(const Options& o) {
  Config cfg;
  SpeciesStats swarmer;
  SpeciesStats tank;
  tank.max_health = 60; tank.speed = 0.5f; tank.damage = 6; tank.armor = 2; tank.cost = 400;
  SpeciesStats nomad;
  nomad.max_health = 20; nomad.speed = 0.9f; nomad.random_move_prob = 0.2f; nomad.cost = 200;
  for (SpeciesStats* s : {&swarmer, &tank, &nomad}) s->max_age = 1000000;  // keep the count stable
  cfg.species = {{"Swarmer", swarmer}, {"Tank", tank}, {"Nomad", nomad}};
  cfg.sim_seed = o.seed;
  cfg.pheromone.diffusion = o.diffusion;
  cfg.enable_heatmaps = o.heatmaps;
  cfg.max_ants_total = o.ants + 1000;
  return cfg;
}

// Places `count` ants on random free passable cells, assigned to the colonies round robin.
void populate(Engine& e, int count) {
  Rng rng(12345);
  const Grid& g = e.grid();
  const int colonies = static_cast<int>(e.colonies().size());
  for (int placed = 0, tries = 0; placed < count && tries < count * 20; ++tries) {
    const int cell = rng.next_int(g.cells());
    if (!g.is_passable(cell) || g.occupant(cell) != NO_ANT || g.hill_at(cell) != NO_HILL) continue;
    if (e.spawn_ant(placed % colonies, 0, cell) >= 0) ++placed;
  }
}

int live_ants(const Engine& e) {
  int n = 0;
  for (const Ant& a : e.ants()) n += is_alive(a);
  return n;
}

void run(const Options& o) {
  Engine e(bench_config(o));
  e.initialize(bench_map(o.width, o.height));
  populate(e, o.ants);
  const int start_ants = live_ants(e);
  const size_t capacity = e.ants().capacity();
  e.step(20);  // warm-up: caches, first trails

  const auto t0 = std::chrono::steady_clock::now();
  e.step(o.ticks);
  const double seconds = std::chrono::duration<double>(std::chrono::steady_clock::now() - t0).count();
  const double tps = o.ticks / seconds;
  const int end_ants = live_ants(e);

  std::printf("[%s] %dx%d, ants %d -> %d, diffusion %.3f, heatmaps %s\n", o.name, o.width, o.height,
              start_ants, end_ants, o.diffusion, o.heatmaps ? "on" : "off");
  std::printf("  %d ticks in %.3f s: %.1f ticks/s, %.1f ns per ant-tick\n", o.ticks, seconds, tps,
              seconds * 1e9 / (static_cast<double>(o.ticks) * (start_ants + end_ants) / 2.0));
  if (o.target_tps > 0)
    std::printf("  spec target %.0f ticks/s: %s\n", o.target_tps,
                tps >= o.target_tps ? "met" : "NOT met");
  std::printf("  peak RSS %ld MB, ant storage %s\n", peak_rss_kb() / 1024,
              e.ants().capacity() == capacity ? "never reallocated" : "REALLOCATED");
}

}  // namespace

int main(int argc, char** argv) {
  std::vector<Options> runs;
  Options custom;
  bool use_custom = false;
  for (int i = 1; i < argc; ++i) {
    const std::string arg = argv[i];
    auto value = [&]() -> const char* {
      if (i + 1 >= argc) {
        std::fprintf(stderr, "%s needs a value\n", arg.c_str());
        std::exit(2);
      }
      return argv[++i];
    };
    if (arg == "--preset") runs.push_back(preset(value()));
    else if (arg == "--width") { custom.width = std::atoi(value()); use_custom = true; }
    else if (arg == "--height") { custom.height = std::atoi(value()); use_custom = true; }
    else if (arg == "--ants") { custom.ants = std::atoi(value()); use_custom = true; }
    else if (arg == "--ticks") { custom.ticks = std::atoi(value()); use_custom = true; }
    else if (arg == "--diffusion") { custom.diffusion = std::strtof(value(), nullptr); use_custom = true; }
    else if (arg == "--heatmaps") { custom.heatmaps = true; use_custom = true; }
    else if (arg == "--seed") { custom.seed = std::strtoull(value(), nullptr, 10); use_custom = true; }
    else {
      std::fprintf(stderr, "usage: %s [--preset small|large] [--width N --height N --ants N "
                           "--ticks N --diffusion D --heatmaps --seed S]\n", argv[0]);
      return 2;
    }
  }
  if (use_custom) {
    if (custom.width < 64 || custom.height < 64 || custom.width > 2048 || custom.height > 2048 ||
        custom.ants < 0 || custom.ticks < 1) {
      std::fprintf(stderr, "width/height must be 64..2048, ants >= 0, ticks >= 1\n");
      return 2;
    }
    runs.push_back(custom);
  }
  if (runs.empty()) runs = {preset("small"), preset("large")};
  for (const Options& o : runs) run(o);
  return 0;
}
