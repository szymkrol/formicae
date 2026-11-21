// module.cpp - pybind11 bindings: Python module `formicae` (spec section 9.3). Owner: P4 (M0).
#include <pybind11/numpy.h>
#include <pybind11/pybind11.h>
#include <pybind11/stl.h>

#include <algorithm>
#include <atomic>
#include <initializer_list>
#include <stdexcept>
#include <string>
#include <vector>

#include "formicae/engine.hpp"

namespace py = pybind11;
using namespace formicae;

namespace {

constexpr int API_VERSION = 2;
constexpr int MAX_STEP = 10000;

// ---- dict -> C++ conversion ------------------------------------------------------------------
// Converts the config dict (spec section 11) into a Config. Unknown keys and values of the wrong
// type are collected with their full path (e.g. "species[1].speed") and reported together; range
// checks happen afterwards in Config::validate(). Sections used only by the Python front end
// (world, time, render, analytics) are validated by load_config() and ignored here.
class ConfigReader {
  public:
    // One JSON object at `path`; keys outside `allowed` are reported as unknown.
    class Section {
      public:
        Section(ConfigReader &owner, py::handle obj, std::string path,
                std::initializer_list<const char *> allowed)
            : owner_(owner), path_(std::move(path)) {
            if (!py::isinstance<py::dict>(obj)) {
                owner_.problem(path_ + " must be an object");
                return;
            }
            dict_ = py::reinterpret_borrow<py::dict>(obj);
            for (auto item : dict_) {
                const std::string key = py::str(item.first);
                bool known = false;
                for (const char *a : allowed)
                    known = known || key == a;
                if (!known)
                    owner_.problem("unknown key '" + join(key) + "'");
            }
        }

        bool has(const char *key) const { return dict_.contains(key); }
        py::object at(const char *key) const { return dict_[key]; }
        std::string join(const std::string &key) const {
            return path_.empty() ? key : path_ + "." + key;
        }

        // Leaves `out` unchanged when the key is absent or has the wrong type.
        template <class T> void get(const char *key, T &out) const {
            if (!has(key))
                return;
            try {
                out = dict_[key].template cast<T>();
            } catch (const py::cast_error &) {
                owner_.problem(join(key) + " has the wrong type");
            }
        }

      private:
        ConfigReader &owner_;
        std::string path_;
        py::dict dict_;
    };

    void problem(std::string msg) { problems_.push_back(std::move(msg)); }

    void throw_if_problems() const {
        if (problems_.empty())
            return;
        std::string msg = "invalid config:";
        for (const auto &p : problems_)
            msg += "\n  " + p;
        throw std::invalid_argument(msg);
    }

  private:
    std::vector<std::string> problems_;
};

using Section = ConfigReader::Section;

SpeciesStats stats_from_dict(const Section &s) {
    SpeciesStats st;
#define OPT(f) s.get(#f, st.f)
    OPT(max_health);
    OPT(max_age);
    OPT(flee_threshold);
    OPT(flee_ticks);
    OPT(speed);
    OPT(random_move_prob);
    OPT(alpha);
    OPT(forward_bonus);
    OPT(nav_beta);
    OPT(noise_damp);
    OPT(damage);
    OPT(armor);
    OPT(accuracy);
    OPT(defend_while_carrying);
    OPT(cost);
    OPT(carry_capacity);
    OPT(a_home);
    OPT(a_food);
    OPT(trail_len_home);
    OPT(trail_len_food);
    OPT(danger_k);
    OPT(danger_k_home);
    OPT(orphan_loss);
    OPT(nav_beta);
    OPT(noise_damp);
    OPT(p_fid);
    OPT(goal_beta);
    OPT(goal_random_move_frac);
    OPT(explore_ticks);
    OPT(food_erase_factor);
    OPT(food_erase_tau);
    OPT(food_erase_delta);
    OPT(deposit_home_while_searching);
    OPT(lost_mult);
#undef OPT
    return st;
}

CasteDef caste_from_dict(const Section &s) {
    CasteDef c;
#define OPT(f) s.get(#f, c.f)
    OPT(name);
    OPT(max_health_mul);
    OPT(damage_mul);
    OPT(armor_mul);
    OPT(speed_mul);
    OPT(carry_mul);
    OPT(cost_mul);
    OPT(random_move_prob_add);
    OPT(a_home_mul);
    OPT(a_food_mul);
    OPT(danger_k_add);
    OPT(defend_while_carrying);
#undef OPT
    return c;
}

// Calls each(item, path) for every element of the array `parent.key`; reports a non-array value.
template <class F>
void for_each_item(ConfigReader &reader, const Section &parent, const char *key, F &&each) {
    if (!parent.has(key))
        return;
    py::object list = parent.at(key);
    if (!py::isinstance<py::list>(list)) {
        reader.problem(parent.join(key) + " must be an array");
        return;
    }
    size_t index = 0;
    for (auto item : py::reinterpret_borrow<py::list>(list))
        each(item, parent.join(key) + "[" + std::to_string(index++) + "]");
}

Config config_from_dict(const py::dict &d) {
    ConfigReader reader;
    Config cfg;
    const Section root(reader, d, "",
                       {"world", "time", "pheromone", "movement", "food", "terrain", "species",
                        "colony", "hostility", "render", "analytics", "seeds", "max_ants_total",
                        "enable_heatmaps"});
    root.get("max_ants_total", cfg.max_ants_total);
    root.get("enable_heatmaps", cfg.enable_heatmaps);
    if (root.has("seeds"))
        Section(reader, root.at("seeds"), "seeds", {"sim_seed"}).get("sim_seed", cfg.sim_seed);

    for_each_item(reader, root, "terrain", [&](py::handle item, const std::string &path) {
        const Section t(reader, item, path,
                        {"name", "move_cost", "evap_mod", "passable", "hazard_damage"});
        TerrainDef def;
        t.get("name", def.name);
        t.get("move_cost", def.move_cost);
        t.get("evap_mod", def.evap_mod);
        t.get("passable", def.passable);
        t.get("hazard_damage", def.hazard_damage);
        cfg.terrain.push_back(def);
    });

    for_each_item(reader, root, "species", [&](py::handle item, const std::string &path) {
        const Section s(reader, item, path,
                        {"name",           "castes",         "max_health",
                         "max_age",        "flee_threshold", "flee_ticks",
                         "speed",          "random_move_prob", "alpha",
                         "forward_bonus",  "nav_beta",       "noise_damp",
                         "damage",         "armor",          "accuracy",
                         "defend_while_carrying", "cost",    "carry_capacity",
                         "a_home",         "a_food",         "trail_len_home",
                         "trail_len_food", "danger_k",       "danger_k_home",
                         "orphan_loss",    "lost_mult",      "p_fid",
                         "goal_beta",      "goal_random_move_frac", "explore_ticks",
                         "food_erase_factor", "food_erase_tau", "food_erase_delta",
                         "deposit_home_while_searching", "caste_ratio"});
        SpeciesDef def;
        s.get("name", def.name);
        def.stats = stats_from_dict(s);
        if (s.has("caste_ratio")) {
            std::vector<float> ratio;
            s.get("caste_ratio", ratio);
            if (ratio.empty() || ratio.size() > static_cast<size_t>(MAX_CASTES))
                reader.problem(s.join("caste_ratio") + " needs 1.." + std::to_string(MAX_CASTES) +
                               " weights");
            else {
                def.caste_ratio.fill(0.0f);
                std::copy(ratio.begin(), ratio.end(), def.caste_ratio.begin());
            }
        }
        cfg.species.push_back(def);
        std::vector<CasteDef> castes;
        for_each_item(reader, s, "castes", [&](py::handle c, const std::string &caste_path) {
            castes.push_back(caste_from_dict(
                Section(reader, c, caste_path,
                        {"name", "max_health_mul", "damage_mul", "armor_mul", "speed_mul",
                         "carry_mul", "cost_mul", "random_move_prob_add", "a_home_mul",
                         "a_food_mul", "danger_k_add", "defend_while_carrying"})));
        });
        cfg.castes.push_back(castes);
    });

    if (root.has("movement")) {
        const Section m(reader, root.at("movement"), "movement",
                        {"nav_min", "nav_max", "noise_tau_ref", "friendly_swap"});
        m.get("friendly_swap", cfg.movement.friendly_swap);
        m.get("nav_min", cfg.movement.nav_min);
        m.get("nav_max", cfg.movement.nav_max);
        m.get("noise_tau_ref", cfg.movement.noise_tau_ref);
    }

    if (root.has("pheromone")) {
        const Section p(reader, root.at("pheromone"), "pheromone",
                        {"decay", "decay_scale", "diffusion", "cutoff", "hit_alarm", "death_alarm",
                         "hazard_alarm", "home_beacon", "food_density_ref", "epsilon",
                         "grad_beta", "tau_cap"});
        PheromoneParams &pp = cfg.pheromone;
        std::vector<float> decay(pp.decay.begin(), pp.decay.end());
        p.get("decay", decay);
        if (decay.size() == NUM_CHANNELS)
            std::copy(decay.begin(), decay.end(), pp.decay.begin());
        else
            reader.problem("pheromone.decay needs 3 values (HOME, FOOD, DANGER)");
#define OPT(f) p.get(#f, pp.f)
        OPT(decay_scale);
        OPT(diffusion);
        OPT(cutoff);
        OPT(hit_alarm);
        OPT(death_alarm);
        OPT(hazard_alarm);
        OPT(home_beacon);
        OPT(food_density_ref);
        OPT(epsilon);
        OPT(grad_beta);
        OPT(tau_cap);
#undef OPT
    }

    if (root.has("food")) {
        const Section f(reader, root.at("food"), "food",
                        {"spawn_interval", "spawn_prob", "max_food_cells", "cluster_radius_min",
                         "cluster_radius_max", "volume_min", "volume_max", "density_min",
                         "density_max"});
        FoodParams &fp = cfg.food;
#define OPT(n) f.get(#n, fp.n)
        OPT(spawn_interval);
        OPT(spawn_prob);
        OPT(max_food_cells);
        OPT(cluster_radius_min);
        OPT(cluster_radius_max);
        OPT(volume_min);
        OPT(volume_max);
        OPT(density_min);
        OPT(density_max);
#undef OPT
    }

    if (root.has("colony")) {
        const Section c(reader, root.at("colony"), "colony",
                        {"hill_radius", "max_health", "initial_energy", "max_population",
                         "spawn_cooldown", "loot_density"});
        ColonyParams &cp = cfg.colony;
#define OPT(n) c.get(#n, cp.n)
        OPT(hill_radius);
        OPT(max_health);
        OPT(initial_energy);
        OPT(max_population);
        OPT(spawn_cooldown);
        OPT(loot_density);
#undef OPT
    }

    if (root.has("hostility")) { // optional S x S matrix of 0/1
        std::vector<std::vector<int>> m;
        root.get("hostility", m);
        const size_t n = std::min(cfg.species.size(), static_cast<size_t>(S_MAX));
        bool square = m.size() == n;
        for (const auto &row : m)
            square = square && row.size() == n;
        if (!square)
            reader.problem("hostility must be a " + std::to_string(n) + " x " + std::to_string(n) +
                           " matrix (one row and one column per species)");
        else
            for (size_t a = 0; a < n; ++a)
                for (size_t b = 0; b < n; ++b) {
                    if (m[a][b] != 0 && m[a][b] != 1)
                        reader.problem("hostility[" + std::to_string(a) + "][" +
                                       std::to_string(b) + "] must be 0 or 1");
                    cfg.hostile[a][b] = m[a][b] != 0;
                }
    }

    reader.throw_if_problems();
    return cfg;
}

// Exact dtype, C-contiguous, no implicit conversion (spec 9.3 initialize()).
template <class T> py::array_t<T> require(const py::dict &d, const char *key, int ndim) {
    if (!d.contains(key))
        throw std::invalid_argument(std::string("map_data is missing key '") + key + "'");
    py::array a = py::reinterpret_borrow<py::array>(d[key]);
    if (!a.dtype().is(py::dtype::of<T>()))
        throw std::invalid_argument(std::string("map_data['") + key + "'] has the wrong dtype");
    if (a.ndim() != ndim)
        throw std::invalid_argument(std::string("map_data['") + key +
                                    "'] has the wrong number of dimensions");
    if (!(a.flags() & py::array::c_style))
        throw std::invalid_argument(std::string("map_data['") + key + "'] must be C-contiguous");
    return py::reinterpret_borrow<py::array_t<T>>(a);
}

MapData map_from_dict(const py::dict &d) {
    MapData m;
    m.width = d["width"].cast<int>();
    m.height = d["height"].cast<int>();
    auto terrain = require<uint8_t>(d, "terrain", 2);
    auto fv = require<float>(d, "food_volume", 2);
    auto fd = require<float>(d, "food_density", 2);
    auto col = require<int32_t>(d, "colonies", 2);
    if (terrain.shape(0) != m.height || terrain.shape(1) != m.width)
        throw std::invalid_argument("terrain shape must be [height, width]");
    m.terrain.assign(terrain.data(), terrain.data() + terrain.size());
    m.food_volume.assign(fv.data(), fv.data() + fv.size());
    m.food_density.assign(fd.data(), fd.data() + fd.size());
    if (col.ndim() != 2 || col.shape(1) != 3)
        throw std::invalid_argument("colonies must have shape [K, 3]");
    for (py::ssize_t k = 0; k < col.shape(0); ++k)
        m.colonies.push_back({col.at(k, 0), col.at(k, 1), col.at(k, 2)});
    return m;
}

// ---- the Python-facing class ---------------------------------------------------------------
class Simulation {
  public:
    explicit Simulation(const py::dict &config) : engine_(config_from_dict(config)) {}

    void initialize(const py::dict &map) {
        guard();
        engine_.initialize(map_from_dict(map));
    }

    uint64_t step(int n) {
        guard();
        if (n < 1 || n > MAX_STEP)
            throw std::invalid_argument("step: n must be in 1..10000");
        if (!engine_.initialized())
            throw std::runtime_error("step: call initialize() first");
        busy_ = true;
        try {
            py::gil_scoped_release
                release; // the UI thread may redraw meanwhile; other calls see "busy"
            engine_.step(n);
        } catch (...) {
            busy_ = false;
            throw;
        }
        busy_ = false;
        return engine_.tick();
    }

    void reset() {
        guard();
        engine_.reset();
    }
    uint64_t tick() const { return engine_.tick(); }
    void save(const std::string &path) const {
        guard();
        if (!engine_.initialized())
            throw std::runtime_error("save: call initialize() first");
        engine_.save(path);
    }
    uint64_t state_hash() const {
        guard();
        if (!engine_.initialized())
            throw std::runtime_error("state_hash: call initialize() first");
        return engine_.state_hash();
    }
    // Replaces the whole engine state, including the config; existing views become invalid.
    void load(const std::string &path) {
        guard();
        engine_ = Engine::load(path);
    }

    // controls
    int spawn_food(int x, int y, int r, float v, float d) {
        guard();
        return engine_.spawn_food(x, y, r, v, d);
    }
    void set_terrain(int x, int y, int id) {
        guard();
        if (id < 0 || id > 6)
            throw std::invalid_argument("set_terrain: unknown terrain id");
        engine_.set_terrain(x, y, static_cast<Terrain>(id));
    }
    void set_param(const std::string &name, double value) {
        guard();
        engine_.set_param(name, value);
    }

    // snapshot getters: zero-copy, read-only views valid until the next step/reset/load
    py::array terrain(py::object self) {
        return view(engine_.grid().terrain.data(), {H(), W()}, self);
    }
    py::array food_volume(py::object self) {
        return view(engine_.grid().food_volume.data(), {H(), W()}, self);
    }
    py::array food_density(py::object self) {
        return view(engine_.grid().food_density.data(), {H(), W()}, self);
    }
    py::array pheromones(py::object self) {
        return view(engine_.grid().pher.data(),
                    {static_cast<py::ssize_t>(engine_.grid().S), NUM_CHANNELS, H(), W()}, self);
    }
    py::array ants(py::object self) {
        return view(engine_.ants().data(), {static_cast<py::ssize_t>(engine_.ants().size())}, self);
    }
    // Heatmap counters (stretch); RuntimeError unless the config sets enable_heatmaps.
    py::array traffic(py::object self) { return heatmap(engine_.grid().traffic, "traffic", self); }
    py::array combat_map(py::object self) {
        return heatmap(engine_.grid().combat, "combat_map", self);
    }
    py::array colonies(py::object self) {
        return view(engine_.colonies().data(),
                    {static_cast<py::ssize_t>(engine_.colonies().size())}, self);
    }

    py::dict metrics() const {
        guard();
        const Metrics &m = engine_.metrics();
        py::dict d;
        d["tick"] = m.tick;
        auto copy = [](const std::vector<int64_t> &v) {
            return py::array_t<int64_t>(static_cast<py::ssize_t>(v.size()), v.data());
        };
        d["population"] = copy(m.population);
        d["births"] = copy(m.births);
        d["kills"] = copy(m.kills);
        d["deaths_combat"] = copy(m.deaths_combat);
        d["deaths_hazard"] = copy(m.deaths_hazard);
        d["deaths_age"] = copy(m.deaths_age);
        d["deaths_orphan"] = copy(m.deaths_orphan);
        d["colonies_alive"] = copy(m.colonies_alive);
        d["deliveries"] = copy(m.deliveries);
        d["return_steps_sum"] = copy(m.return_steps_sum);
        py::array_t<int64_t> by_caste({static_cast<py::ssize_t>(m.population.size()),
                                       static_cast<py::ssize_t>(MAX_CASTES)});
        std::copy(m.population_caste.begin(), m.population_caste.end(), by_caste.mutable_data());
        d["population_caste"] = by_caste;
        d["food_total_volume"] = m.food_total_volume;
        d["food_total_energy"] = m.food_total_energy;
        return d;
    }

    py::dict cell_info(int x, int y) const {
        guard();
        const Grid &g = engine_.grid();
        if (!g.in_bounds(x, y))
            throw std::invalid_argument("cell_info: cell out of bounds");
        const int i = g.idx(x, y);
        py::dict d;
        d["terrain"] = static_cast<int>(g.terrain[i]);
        d["food_volume"] = g.food_volume[i];
        d["food_density"] = g.food_density[i];
        py::array_t<float> ph(
            {static_cast<py::ssize_t>(g.S), static_cast<py::ssize_t>(NUM_CHANNELS)});
        for (int s = 0; s < g.S; ++s)
            for (int c = 0; c < NUM_CHANNELS; ++c)
                ph.mutable_at(s, c) = g.pher_at(s, c, i);
        d["pheromone"] = ph;
        const int slot = g.occupant(i);
        if (slot == NO_ANT) {
            d["ant"] = py::none();
        } else {
            const Ant &a = engine_.ants()[slot];
            py::dict ad;
            ad["id"] = a.id;
            ad["age"] = a.age;
            ad["colony"] = a.colony;
            ad["species"] = a.species;
            ad["caste"] = a.caste;
            ad["state"] = a.state;
            ad["health"] = a.health;
            ad["carried_volume"] = a.carried_volume;
            ad["carried_density"] = a.carried_density;
            d["ant"] = ad;
        }
        const int h = g.hill_at(i);
        if (h == NO_HILL) {
            d["colony"] = py::none();
        } else {
            const ColonyRecord &c = engine_.colonies()[h];
            py::dict cd;
            cd["index"] = h;
            cd["species"] = c.species;
            cd["alive"] = c.alive != 0;
            cd["health"] = c.health;
            cd["max_health"] = c.max_health;
            cd["stored_energy"] = c.stored_energy;
            cd["population"] = c.population;
            d["colony"] = cd;
        }
        return d;
    }

  private:
    void guard() const {
        if (busy_)
            throw std::runtime_error("busy");
    }
    py::array heatmap(const std::vector<uint32_t> &layer, const char *name,
                      const py::object &self) const {
        guard();
        if (!engine_.initialized())
            throw std::runtime_error(std::string(name) + ": call initialize() first");
        if (!engine_.config().enable_heatmaps)
            throw std::runtime_error(std::string(name) + ": enable_heatmaps is not set");
        return view(layer.data(), {H(), W()}, self);
    }
    py::ssize_t W() const { return engine_.grid().W; }
    py::ssize_t H() const { return engine_.grid().H; }

    template <class T>
    py::array view(const T *data, std::vector<py::ssize_t> shape, const py::object &base) const {
        guard();
        py::array a(py::dtype::of<T>(), shape, std::vector<py::ssize_t>{}, data, base);
        a.attr("setflags")(py::arg("write") = false);
        return a;
    }

    Engine engine_;
    std::atomic<bool> busy_{false};
};

} // namespace

PYBIND11_MODULE(formicae, m) {
    m.doc() = "Ant colony simulation engine (C++20). See docs/SPEC.md, section 9.3.";
    m.attr("__version__") = "0.1.0";
    m.attr("API_VERSION") = API_VERSION;

    // NumPy dtypes of the exposed records; the layouts must match python/formicae_ui/types.py.
    PYBIND11_NUMPY_DTYPE(Ant, id, age, x, y, colony, trail_age, species, caste, state, last_dir,
                         timer, explore_timer, fidelity_fail, pad, health, carried_volume,
                         carried_density, move_acc, food_x, food_y);
    PYBIND11_NUMPY_DTYPE(ColonyRecord, stored_energy, health, max_health, population, x, y, species,
                         alive, pad);

    py::class_<Simulation>(m, "Simulation")
        .def(py::init<const py::dict &>(), py::arg("config"))
        .def("initialize", &Simulation::initialize, py::arg("map_data"))
        .def("step", &Simulation::step, py::arg("n") = 1)
        .def("reset", &Simulation::reset)
        .def_property_readonly("tick", &Simulation::tick)
        .def("save", &Simulation::save, py::arg("path"))
        .def("load", &Simulation::load, py::arg("path"))
        .def("state_hash", &Simulation::state_hash)
        .def("spawn_food", &Simulation::spawn_food, py::arg("x"), py::arg("y"), py::arg("radius"),
             py::arg("volume"), py::arg("density"))
        .def("set_terrain", &Simulation::set_terrain, py::arg("x"), py::arg("y"),
             py::arg("terrain_id"))
        .def("set_param", &Simulation::set_param, py::arg("name"), py::arg("value"))
        .def("cell_info", &Simulation::cell_info, py::arg("x"), py::arg("y"))
        .def("metrics", &Simulation::metrics)
        // getters receive the Python object so views can keep the simulation alive (array base)
        .def("terrain", [](py::object self) { return self.cast<Simulation &>().terrain(self); })
        .def("food_volume",
             [](py::object self) { return self.cast<Simulation &>().food_volume(self); })
        .def("food_density",
             [](py::object self) { return self.cast<Simulation &>().food_density(self); })
        .def("pheromones",
             [](py::object self) { return self.cast<Simulation &>().pheromones(self); })
        .def("ants", [](py::object self) { return self.cast<Simulation &>().ants(self); })
        .def("colonies", [](py::object self) { return self.cast<Simulation &>().colonies(self); })
        .def("traffic", [](py::object self) { return self.cast<Simulation &>().traffic(self); })
        .def("combat_map",
             [](py::object self) { return self.cast<Simulation &>().combat_map(self); });
}
