// module.cpp - pybind11 bindings: Python module `antsim` (spec section 9.3). Owner: P4 (M0).
#include <pybind11/numpy.h>
#include <pybind11/pybind11.h>
#include <pybind11/stl.h>

#include <atomic>
#include <stdexcept>
#include <string>
#include <vector>

#include "antsim/engine.hpp"

namespace py = pybind11;
using namespace antsim;

namespace {

constexpr int API_VERSION = 1;
constexpr int MAX_STEP = 10000;

// ---- dict -> C++ conversion ------------------------------------------------------------------
template <class T>
T opt(const py::dict& d, const char* key, T fallback) {
  return d.contains(key) ? d[key].cast<T>() : fallback;
}

SpeciesStats stats_from_dict(const py::dict& d) {
  SpeciesStats st;
#define OPT(f) st.f = opt(d, #f, st.f)
  OPT(max_health); OPT(max_age); OPT(flee_threshold); OPT(flee_ticks);
  OPT(speed); OPT(random_move_prob); OPT(alpha); OPT(forward_bonus);
  OPT(damage); OPT(armor); OPT(accuracy); OPT(defend_while_carrying);
  OPT(cost); OPT(carry_capacity);
  OPT(a_home); OPT(a_food); OPT(trail_len_home); OPT(trail_len_food);
  OPT(danger_k); OPT(danger_k_home); OPT(orphan_loss);
#undef OPT
  return st;
}

CasteDef caste_from_dict(const py::dict& d) {
  CasteDef c;
#define OPT(f) c.f = opt(d, #f, c.f)
  OPT(name); OPT(max_health_mul); OPT(damage_mul); OPT(armor_mul); OPT(speed_mul); OPT(carry_mul);
  OPT(cost_mul); OPT(random_move_prob_add); OPT(a_home_mul); OPT(a_food_mul); OPT(danger_k_add);
  OPT(defend_while_carrying);
#undef OPT
  return c;
}

// Converts the validated config dict produced by python/antsim_ui/config.py (spec section 11).
// TODO(P4): reject unknown keys here as well; load_config() already does it on the Python side.
Config config_from_dict(const py::dict& d) {
  Config cfg;
  if (d.contains("seeds")) cfg.sim_seed = opt<uint64_t>(d["seeds"].cast<py::dict>(), "sim_seed", cfg.sim_seed);
  cfg.max_ants_total = opt(d, "max_ants_total", cfg.max_ants_total);
  cfg.enable_heatmaps = opt(d, "enable_heatmaps", cfg.enable_heatmaps);
  if (d.contains("terrain"))
    for (auto item : d["terrain"].cast<py::list>()) {
      py::dict t = item.cast<py::dict>();
      TerrainDef def;
      def.name = opt<std::string>(t, "name", "");
      def.move_cost = opt(t, "move_cost", 1.0f);
      def.evap_mod = opt(t, "evap_mod", 1.0f);
      def.passable = opt(t, "passable", true);
      def.hazard_damage = opt(t, "hazard_damage", 0.0f);
      cfg.terrain.push_back(def);
    }
  if (d.contains("species"))
    for (auto item : d["species"].cast<py::list>()) {
      py::dict s = item.cast<py::dict>();
      cfg.species.push_back({opt<std::string>(s, "name", ""), stats_from_dict(s)});
      std::vector<CasteDef> list;
      if (s.contains("castes"))
        for (auto c : s["castes"].cast<py::list>()) list.push_back(caste_from_dict(c.cast<py::dict>()));
      cfg.castes.push_back(list);
    }
  if (d.contains("pheromone")) {
    py::dict p = d["pheromone"].cast<py::dict>();
    PheromoneParams& pp = cfg.pheromone;
    if (p.contains("decay")) {
      auto v = p["decay"].cast<std::vector<float>>();
      if (v.size() != NUM_CHANNELS) throw std::invalid_argument("pheromone.decay needs 3 values");
      for (int i = 0; i < NUM_CHANNELS; ++i) pp.decay[i] = v[i];
    }
#define OPT(f) pp.f = opt(p, #f, pp.f)
    OPT(decay_scale); OPT(diffusion); OPT(cutoff); OPT(hit_alarm); OPT(death_alarm);
    OPT(hazard_alarm); OPT(home_beacon); OPT(food_density_ref); OPT(epsilon);
#undef OPT
  }
  if (d.contains("food")) {
    py::dict f = d["food"].cast<py::dict>();
    FoodParams& fp = cfg.food;
#define OPT(n) fp.n = opt(f, #n, fp.n)
    OPT(spawn_interval); OPT(spawn_prob); OPT(max_food_cells); OPT(cluster_radius_min);
    OPT(cluster_radius_max); OPT(volume_min); OPT(volume_max); OPT(density_min); OPT(density_max);
#undef OPT
  }
  if (d.contains("colony")) {
    py::dict c = d["colony"].cast<py::dict>();
    ColonyParams& cp = cfg.colony;
#define OPT(n) cp.n = opt(c, #n, cp.n)
    OPT(hill_radius); OPT(max_health); OPT(initial_energy); OPT(max_population);
    OPT(spawn_cooldown); OPT(loot_density);
#undef OPT
  }
  if (d.contains("hostility")) {  // optional S x S matrix of 0/1
    auto m = d["hostility"].cast<std::vector<std::vector<int>>>();
    for (size_t a = 0; a < m.size() && a < static_cast<size_t>(S_MAX); ++a)
      for (size_t b = 0; b < m[a].size() && b < static_cast<size_t>(S_MAX); ++b) cfg.hostile[a][b] = m[a][b] != 0;
  }
  return cfg;
}

// Exact dtype, C-contiguous, no implicit conversion (spec 9.3 initialize()).
template <class T>
py::array_t<T> require(const py::dict& d, const char* key, int ndim) {
  if (!d.contains(key)) throw std::invalid_argument(std::string("map_data is missing key '") + key + "'");
  py::array a = py::reinterpret_borrow<py::array>(d[key]);
  if (!a.dtype().is(py::dtype::of<T>())) throw std::invalid_argument(std::string("map_data['") + key + "'] has the wrong dtype");
  if (a.ndim() != ndim) throw std::invalid_argument(std::string("map_data['") + key + "'] has the wrong number of dimensions");
  if (!(a.flags() & py::array::c_style)) throw std::invalid_argument(std::string("map_data['") + key + "'] must be C-contiguous");
  return py::reinterpret_borrow<py::array_t<T>>(a);
}

MapData map_from_dict(const py::dict& d) {
  MapData m;
  m.width = d["width"].cast<int>();
  m.height = d["height"].cast<int>();
  auto terrain = require<uint8_t>(d, "terrain", 2);
  auto fv = require<float>(d, "food_volume", 2);
  auto fd = require<float>(d, "food_density", 2);
  auto col = require<int32_t>(d, "colonies", 2);
  if (terrain.shape(0) != m.height || terrain.shape(1) != m.width) throw std::invalid_argument("terrain shape must be [height, width]");
  m.terrain.assign(terrain.data(), terrain.data() + terrain.size());
  m.food_volume.assign(fv.data(), fv.data() + fv.size());
  m.food_density.assign(fd.data(), fd.data() + fd.size());
  if (col.ndim() != 2 || col.shape(1) != 3) throw std::invalid_argument("colonies must have shape [K, 3]");
  for (py::ssize_t k = 0; k < col.shape(0); ++k) m.colonies.push_back({col.at(k, 0), col.at(k, 1), col.at(k, 2)});
  return m;
}

// ---- the Python-facing class ---------------------------------------------------------------
class Simulation {
 public:
  explicit Simulation(const py::dict& config) : engine_(config_from_dict(config)) {}

  void initialize(const py::dict& map) { guard(); engine_.initialize(map_from_dict(map)); }

  uint64_t step(int n) {
    guard();
    if (n < 1 || n > MAX_STEP) throw std::invalid_argument("step: n must be in 1..10000");
    if (!engine_.initialized()) throw std::runtime_error("step: call initialize() first");
    busy_ = true;
    try {
      py::gil_scoped_release release;  // the UI thread may redraw meanwhile; other calls see "busy"
      engine_.step(n);
    } catch (...) { busy_ = false; throw; }
    busy_ = false;
    return engine_.tick();
  }

  void reset() { guard(); engine_.reset(); }
  uint64_t tick() const { return engine_.tick(); }
  void save(const std::string&) { throw py::value_error("save: not implemented yet (P4, priority P2)"); }
  void load(const std::string&) { throw py::value_error("load: not implemented yet (P4, priority P2)"); }

  // controls
  int spawn_food(int x, int y, int r, float v, float d) { guard(); return engine_.spawn_food(x, y, r, v, d); }
  void set_terrain(int x, int y, int id) {
    guard();
    if (id < 0 || id > 6) throw std::invalid_argument("set_terrain: unknown terrain id");
    engine_.set_terrain(x, y, static_cast<Terrain>(id));
  }
  void set_param(const std::string& name, double value) { guard(); engine_.set_param(name, value); }

  // snapshot getters: zero-copy, read-only views valid until the next step/reset/load
  py::array terrain(py::object self) { return view(engine_.grid().terrain.data(), {H(), W()}, self); }
  py::array food_volume(py::object self) { return view(engine_.grid().food_volume.data(), {H(), W()}, self); }
  py::array food_density(py::object self) { return view(engine_.grid().food_density.data(), {H(), W()}, self); }
  py::array pheromones(py::object self) {
    return view(engine_.grid().pher.data(), {static_cast<py::ssize_t>(engine_.grid().S), NUM_CHANNELS, H(), W()}, self);
  }
  py::array ants(py::object self) {
    return view(engine_.ants().data(), {static_cast<py::ssize_t>(engine_.ants().size())}, self);
  }
  py::array colonies(py::object self) {
    return view(engine_.colonies().data(), {static_cast<py::ssize_t>(engine_.colonies().size())}, self);
  }

  py::dict metrics() const {
    guard();
    const Metrics& m = engine_.metrics();
    py::dict d;
    d["tick"] = m.tick;
    auto copy = [](const std::vector<int64_t>& v) { return py::array_t<int64_t>(static_cast<py::ssize_t>(v.size()), v.data()); };
    d["population"] = copy(m.population);  d["births"] = copy(m.births);  d["kills"] = copy(m.kills);
    d["deaths_combat"] = copy(m.deaths_combat);  d["deaths_hazard"] = copy(m.deaths_hazard);
    d["deaths_age"] = copy(m.deaths_age);  d["deaths_orphan"] = copy(m.deaths_orphan);
    d["colonies_alive"] = copy(m.colonies_alive);
    d["food_total_volume"] = m.food_total_volume;  d["food_total_energy"] = m.food_total_energy;
    return d;
  }

  py::dict cell_info(int x, int y) const {
    guard();
    const Grid& g = engine_.grid();
    if (!g.in_bounds(x, y)) throw std::invalid_argument("cell_info: cell out of bounds");
    const int i = g.idx(x, y);
    py::dict d;
    d["terrain"] = static_cast<int>(g.terrain[i]);
    d["food_volume"] = g.food_volume[i];
    d["food_density"] = g.food_density[i];
    py::array_t<float> ph({static_cast<py::ssize_t>(g.S), static_cast<py::ssize_t>(NUM_CHANNELS)});
    for (int s = 0; s < g.S; ++s)
      for (int c = 0; c < NUM_CHANNELS; ++c) ph.mutable_at(s, c) = g.pher_at(s, c, i);
    d["pheromone"] = ph;
    const int slot = g.occupant(i);
    if (slot == NO_ANT) { d["ant"] = py::none(); }
    else {
      const Ant& a = engine_.ants()[slot];
      py::dict ad;
      ad["id"] = a.id; ad["age"] = a.age; ad["colony"] = a.colony; ad["species"] = a.species;
      ad["caste"] = a.caste; ad["state"] = a.state; ad["health"] = a.health;
      ad["carried_volume"] = a.carried_volume; ad["carried_density"] = a.carried_density;
      d["ant"] = ad;
    }
    const int h = g.hill_at(i);
    if (h == NO_HILL) { d["colony"] = py::none(); }
    else {
      const ColonyRecord& c = engine_.colonies()[h];
      py::dict cd;
      cd["index"] = h; cd["species"] = c.species; cd["alive"] = c.alive != 0; cd["health"] = c.health;
      cd["max_health"] = c.max_health; cd["stored_energy"] = c.stored_energy; cd["population"] = c.population;
      d["colony"] = cd;
    }
    return d;
  }

 private:
  void guard() const { if (busy_) throw std::runtime_error("busy"); }
  py::ssize_t W() const { return engine_.grid().W; }
  py::ssize_t H() const { return engine_.grid().H; }

  template <class T>
  py::array view(const T* data, std::vector<py::ssize_t> shape, const py::object& base) const {
    guard();
    py::array a(py::dtype::of<T>(), shape, std::vector<py::ssize_t>{}, data, base);
    a.attr("setflags")(py::arg("write") = false);
    return a;
  }

  Engine engine_;
  std::atomic<bool> busy_{false};
};

}  // namespace

PYBIND11_MODULE(antsim, m) {
  m.doc() = "Ant colony simulation engine (C++20). See docs/SPEC.md, section 9.3.";
  m.attr("__version__") = "0.1.0";
  m.attr("API_VERSION") = API_VERSION;

  // NumPy dtypes of the exposed records; the layouts must match python/antsim_ui/types.py.
  PYBIND11_NUMPY_DTYPE(Ant, id, age, x, y, colony, trail_age, species, caste, state, last_dir, timer,
                       pad, health, carried_volume, carried_density, move_acc);
  PYBIND11_NUMPY_DTYPE(ColonyRecord, stored_energy, health, max_health, population, x, y, species,
                       alive, pad);

  py::class_<Simulation>(m, "Simulation")
      .def(py::init<const py::dict&>(), py::arg("config"))
      .def("initialize", &Simulation::initialize, py::arg("map_data"))
      .def("step", &Simulation::step, py::arg("n") = 1)
      .def("reset", &Simulation::reset)
      .def_property_readonly("tick", &Simulation::tick)
      .def("save", &Simulation::save, py::arg("path"))
      .def("load", &Simulation::load, py::arg("path"))
      .def("spawn_food", &Simulation::spawn_food, py::arg("x"), py::arg("y"), py::arg("radius"), py::arg("volume"), py::arg("density"))
      .def("set_terrain", &Simulation::set_terrain, py::arg("x"), py::arg("y"), py::arg("terrain_id"))
      .def("set_param", &Simulation::set_param, py::arg("name"), py::arg("value"))
      .def("cell_info", &Simulation::cell_info, py::arg("x"), py::arg("y"))
      .def("metrics", &Simulation::metrics)
      // getters receive the Python object so views can keep the simulation alive (array base)
      .def("terrain", [](py::object self) { return self.cast<Simulation&>().terrain(self); })
      .def("food_volume", [](py::object self) { return self.cast<Simulation&>().food_volume(self); })
      .def("food_density", [](py::object self) { return self.cast<Simulation&>().food_density(self); })
      .def("pheromones", [](py::object self) { return self.cast<Simulation&>().pheromones(self); })
      .def("ants", [](py::object self) { return self.cast<Simulation&>().ants(self); })
      .def("colonies", [](py::object self) { return self.cast<Simulation&>().colonies(self); });
  // TODO(P4/P1): traffic() and combat_map() when enable_heatmaps is set (stretch).
}
