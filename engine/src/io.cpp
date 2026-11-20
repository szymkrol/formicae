// io.cpp - binary save/load (spec 9.3, priority P2). Owner: P4 (M0) with P1.
//
// File layout (native byte order, little-endian on all supported platforms):
//   "ANTS" | u32 format version | config | initial map (for reset) | grid layers (incl. heatmap
//   counters) | RNG state | tick, next ant id | ant slots + free list | colonies + extras | metrics
// state_hash() hashes exactly the bytes after the header, so equal hashes mean equal snapshots.
// Derived layers (move_cost, evap_mod, hazard, passable), the species table and the decay factor
// planes are rebuilt from the saved config and terrain, so a loaded run continues bit-identically.
#include <array>
#include <cstdint>
#include <cstring>
#include <filesystem>
#include <fstream>
#include <limits>
#include <stdexcept>
#include <string>
#include <type_traits>
#include <vector>

#include "formicae/engine.hpp"

namespace formicae {

namespace {

constexpr char MAGIC[4] = {'A', 'N', 'T', 'S'};
constexpr uint32_t FORMAT_VERSION = 1;

class Writer {
  public:
    explicit Writer(const std::string &path) : out_(path, std::ios::binary | std::ios::trunc) {
        if (!out_)
            throw std::invalid_argument("save: cannot open '" + path + "' for writing");
    }

    template <class T> void operator()(const T &v) {
        static_assert(std::is_trivially_copyable_v<T>);
        out_.write(reinterpret_cast<const char *>(&v), sizeof(T));
    }
    void operator()(const bool &b) { (*this)(static_cast<uint8_t>(b ? 1 : 0)); }
    void operator()(const std::string &s) {
        (*this)(static_cast<uint64_t>(s.size()));
        out_.write(s.data(), static_cast<std::streamsize>(s.size()));
    }
    template <class T> void operator()(const std::vector<T> &v) {
        static_assert(std::is_trivially_copyable_v<T>);
        (*this)(static_cast<uint64_t>(v.size()));
        out_.write(reinterpret_cast<const char *>(v.data()),
                   static_cast<std::streamsize>(v.size() * sizeof(T)));
    }
    template <class T> void list(const std::vector<T> &v, auto &&each) {
        (*this)(static_cast<uint64_t>(v.size()));
        for (const T &item : v)
            each(item);
    }

    void finish(const std::string &path) {
        out_.flush();
        if (!out_)
            throw std::invalid_argument("save: writing '" + path + "' failed");
        out_.close();
    }

  private:
    std::ofstream out_;
};

// FNV-1a (64 bit) over the same byte stream the Writer would produce.
class Hasher {
  public:
    template <class T> void operator()(const T &v) {
        static_assert(std::is_trivially_copyable_v<T>);
        bytes(&v, sizeof(T));
    }
    void operator()(const bool &b) { (*this)(static_cast<uint8_t>(b ? 1 : 0)); }
    void operator()(const std::string &s) {
        (*this)(static_cast<uint64_t>(s.size()));
        bytes(s.data(), s.size());
    }
    template <class T> void operator()(const std::vector<T> &v) {
        static_assert(std::is_trivially_copyable_v<T>);
        (*this)(static_cast<uint64_t>(v.size()));
        bytes(v.data(), v.size() * sizeof(T));
    }
    template <class T> void list(const std::vector<T> &v, auto &&each) {
        (*this)(static_cast<uint64_t>(v.size()));
        for (const T &item : v)
            each(item);
    }
    uint64_t value() const { return hash_; }

  private:
    void bytes(const void *data, size_t n) {
        const auto *p = static_cast<const unsigned char *>(data);
        for (size_t i = 0; i < n; ++i)
            hash_ = (hash_ ^ p[i]) * 0x100000001b3ULL;
    }
    uint64_t hash_ = 0xcbf29ce484222325ULL;
};

class Reader {
  public:
    explicit Reader(const std::string &path) : path_(path), in_(path, std::ios::binary) {
        if (!in_)
            throw std::invalid_argument("load: cannot open '" + path + "'");
        in_.seekg(0, std::ios::end);
        remaining_ = static_cast<uint64_t>(in_.tellg());
        in_.seekg(0, std::ios::beg);
    }

    template <class T> void operator()(T &v) {
        static_assert(std::is_trivially_copyable_v<T>);
        raw(&v, sizeof(T));
    }
    void operator()(bool &b) {
        uint8_t v = 0;
        (*this)(v);
        if (v > 1)
            fail("invalid boolean");
        b = v != 0;
    }
    void operator()(std::string &s) {
        s.resize(count(1));
        raw(s.data(), s.size());
    }
    template <class T> void operator()(std::vector<T> &v) {
        static_assert(std::is_trivially_copyable_v<T>);
        v.resize(count(sizeof(T)));
        raw(v.data(), v.size() * sizeof(T));
    }
    template <class T> void list(std::vector<T> &v, auto &&each) {
        v.resize(count(1));
        for (T &item : v)
            each(item);
    }

    void finish() const {
        if (remaining_ != 0)
            fail("trailing data after the snapshot");
    }
    [[noreturn]] void fail(const std::string &why) const {
        throw std::invalid_argument("load: '" + path_ + "' is not a valid snapshot (" + why + ")");
    }

  private:
    // Element count of the next container; bounded by the bytes left so a corrupt file cannot
    // trigger a huge allocation.
    size_t count(size_t min_element_bytes) {
        uint64_t n = 0;
        (*this)(n);
        if (n > remaining_ / min_element_bytes)
            fail("container size exceeds file size");
        return static_cast<size_t>(n);
    }
    void raw(void *dst, size_t bytes) {
        if (bytes > remaining_)
            fail("unexpected end of file");
        in_.read(static_cast<char *>(dst), static_cast<std::streamsize>(bytes));
        if (!in_)
            fail("read error");
        remaining_ -= bytes;
    }

    std::string path_;
    std::ifstream in_;
    uint64_t remaining_ = 0;
};

// One field list per struct, shared by Writer (const objects) and Reader (mutable objects), so the
// two directions cannot drift apart.
template <class Ar, class T> void fields_terrain(Ar &ar, T &t) {
    ar(t.name);
    ar(t.move_cost);
    ar(t.evap_mod);
    ar(t.passable);
    ar(t.hazard_damage);
}

template <class Ar, class T> void fields_stats(Ar &ar, T &s) {
    ar(s.max_health);
    ar(s.max_age);
    ar(s.flee_threshold);
    ar(s.flee_ticks);
    ar(s.speed);
    ar(s.random_move_prob);
    ar(s.alpha);
    ar(s.forward_bonus);
    ar(s.nav_beta);
    ar(s.noise_damp);
    ar(s.damage);
    ar(s.armor);
    ar(s.accuracy);
    ar(s.defend_while_carrying);
    ar(s.cost);
    ar(s.carry_capacity);
    ar(s.a_home);
    ar(s.a_food);
    ar(s.trail_len_home);
    ar(s.trail_len_food);
    ar(s.danger_k);
    ar(s.danger_k_home);
    ar(s.orphan_loss);
    ar(s.lost_mult);
}

template <class Ar, class T> void fields_caste(Ar &ar, T &c) {
    ar(c.name);
    ar(c.max_health_mul);
    ar(c.damage_mul);
    ar(c.armor_mul);
    ar(c.speed_mul);
    ar(c.carry_mul);
    ar(c.cost_mul);
    ar(c.random_move_prob_add);
    ar(c.a_home_mul);
    ar(c.a_food_mul);
    ar(c.danger_k_add);
    ar(c.defend_while_carrying);
}

template <class Ar, class T> void fields_config(Ar &ar, T &cfg) {
    ar(cfg.sim_seed);
    ar(cfg.max_ants_total);
    ar(cfg.enable_heatmaps);
    ar.list(cfg.terrain, [&](auto &t) { fields_terrain(ar, t); });
    ar.list(cfg.species, [&](auto &s) {
        ar(s.name);
        fields_stats(ar, s.stats);
        ar(s.caste_ratio);
    });
    ar.list(cfg.castes,
            [&](auto &list) { ar.list(list, [&](auto &c) { fields_caste(ar, c); }); });
    for (auto &row : cfg.hostile)
        for (auto &h : row)
            ar(h);

    auto &p = cfg.pheromone;
    ar(p.decay);
    ar(p.decay_scale);
    ar(p.diffusion);
    ar(p.cutoff);
    ar(p.hit_alarm);
    ar(p.death_alarm);
    ar(p.hazard_alarm);
    ar(p.home_beacon);
    ar(p.food_density_ref);
    ar(p.epsilon);
    ar(p.grad_beta);

    auto &m = cfg.movement;
    ar(m.nav_min);
    ar(m.nav_max);
    ar(m.noise_tau_ref);
    ar(m.nav_scale);
    ar(m.noise_damp_scale);
    ar(m.friendly_swap);

    auto &f = cfg.food;
    ar(f.spawn_interval);
    ar(f.spawn_prob);
    ar(f.max_food_cells);
    ar(f.cluster_radius_min);
    ar(f.cluster_radius_max);
    ar(f.volume_min);
    ar(f.volume_max);
    ar(f.density_min);
    ar(f.density_max);

    auto &c = cfg.colony;
    ar(c.hill_radius);
    ar(c.max_health);
    ar(c.initial_energy);
    ar(c.max_population);
    ar(c.spawn_cooldown);
    ar(c.loot_density);
}

template <class Ar, class T> void fields_map(Ar &ar, T &map) {
    ar(map.width);
    ar(map.height);
    ar(map.terrain);
    ar(map.food_volume);
    ar(map.food_density);
    ar(map.colonies);
}

template <class Ar, class T> void fields_metrics(Ar &ar, T &m) {
    ar(m.tick);
    ar(m.population);
    ar(m.births);
    ar(m.kills);
    ar(m.deaths_combat);
    ar(m.deaths_hazard);
    ar(m.deaths_age);
    ar(m.deaths_orphan);
    ar(m.colonies_alive);
    ar(m.deliveries);
    ar(m.return_steps_sum);
    ar(m.population_caste);
    ar(m.food_total_volume);
    ar(m.food_total_energy);
}

template <class Ar, class T> void fields_colony_extra(Ar &ar, T &x) {
    ar(x.spawn_cooldown);
    ar(x.caste_ratio);
}

} // namespace

template <class Archive> void Engine::write_state(Archive &w) const {
    fields_config(w, cfg_);
    fields_map(w, initial_map_);
    w(grid_.W);
    w(grid_.H);
    w(grid_.terrain);
    w(grid_.food_volume);
    w(grid_.food_density);
    w(grid_.occupancy);
    w(grid_.hill_id);
    w(grid_.pher);
    w(grid_.traffic);
    w(grid_.combat);
    w(rng_.state());
    w(rng_.inc());
    w(tick_);
    w(next_ant_id_);
    w(ants_);
    w(free_slots_);
    w(colonies_);
    w.list(colony_extra_, [&](const ColonyExtra &x) { fields_colony_extra(w, x); });
    fields_metrics(w, metrics_);
}

uint64_t Engine::state_hash() const {
    if (!initialized_)
        throw std::logic_error("state_hash: engine is not initialized");
    Hasher h;
    write_state(h);
    return h.value();
}

void Engine::save(const std::string &path) const {
    if (!initialized_)
        throw std::logic_error("save: engine is not initialized");
    // Write to a temporary file first so a failed save never destroys an existing snapshot.
    const std::string tmp = path + ".tmp";
    {
        Writer w(tmp);
        w(MAGIC);
        w(FORMAT_VERSION);
        write_state(w);
        w.finish(tmp);
    }
    std::error_code ec;
    std::filesystem::rename(tmp, path, ec);
    if (ec) {
        std::filesystem::remove(tmp, ec);
        throw std::invalid_argument("save: cannot write '" + path + "'");
    }
}

Engine Engine::load(const std::string &path) {
    Reader r(path);
    char magic[4];
    r(magic);
    if (std::memcmp(magic, MAGIC, sizeof(MAGIC)) != 0)
        r.fail("missing ANTS header");
    uint32_t version = 0;
    r(version);
    if (version != FORMAT_VERSION)
        r.fail("unsupported format version " + std::to_string(version));

    Config cfg;
    fields_config(r, cfg);
    Engine e = [&] {
        try {
            return Engine(cfg); // validates the stored config like a fresh one
        } catch (const std::invalid_argument &err) {
            r.fail(std::string("bad config: ") + err.what());
        }
    }();

    fields_map(r, e.initial_map_);
    int W = 0, H = 0;
    r(W);
    r(H);
    if (W <= 0 || H <= 0 || W > std::numeric_limits<int16_t>::max() ||
        H > std::numeric_limits<int16_t>::max())
        r.fail("bad grid size");
    const size_t cells = static_cast<size_t>(W) * H;
    const int S = static_cast<int>(e.cfg_.species.size());
    e.grid_.allocate(W, H, S);
    r(e.grid_.terrain);
    r(e.grid_.food_volume);
    r(e.grid_.food_density);
    r(e.grid_.occupancy);
    r(e.grid_.hill_id);
    r(e.grid_.pher);
    r(e.grid_.traffic);
    r(e.grid_.combat);
    for (const auto *layer :
         {&e.grid_.terrain, &e.initial_map_.terrain}) // terrain ids index the terrain table
        for (uint8_t t : *layer)
            if (t >= e.cfg_.terrain.size())
                r.fail("unknown terrain id");
    if (e.grid_.terrain.size() != cells || e.grid_.food_volume.size() != cells ||
        e.grid_.food_density.size() != cells || e.grid_.occupancy.size() != cells ||
        e.grid_.hill_id.size() != cells || e.grid_.pher.size() != cells * NUM_CHANNELS * S)
        r.fail("layer sizes do not match the grid");
    const size_t heat_cells = e.cfg_.enable_heatmaps ? cells : 0;
    if (e.grid_.traffic.size() != heat_cells || e.grid_.combat.size() != heat_cells)
        r.fail("heatmap layers do not match enable_heatmaps");
    if (e.initial_map_.width != W || e.initial_map_.height != H ||
        e.initial_map_.terrain.size() != cells || e.initial_map_.food_volume.size() != cells ||
        e.initial_map_.food_density.size() != cells)
        r.fail("initial map does not match the grid");

    uint64_t rng_state = 0, rng_inc = 0;
    r(rng_state);
    r(rng_inc);
    e.rng_.restore(rng_state, rng_inc);
    r(e.tick_);
    r(e.next_ant_id_);
    r(e.ants_);
    r(e.free_slots_);
    r(e.colonies_);
    r.list(e.colony_extra_, [&](ColonyExtra &x) { fields_colony_extra(r, x); });
    fields_metrics(r, e.metrics_);
    r.finish();

    // Cross-checks: every index stored in the snapshot must point into the loaded arrays.
    const int n_ants = static_cast<int>(e.ants_.size());
    const int n_colonies = static_cast<int>(e.colonies_.size());
    if (n_ants > e.cfg_.max_ants_total)
        r.fail("more ant slots than max_ants_total");
    if (e.colony_extra_.size() != e.colonies_.size())
        r.fail("colony tables differ in size");
    for (const auto &hill : e.initial_map_.colonies)
        if (hill.species < 0 || hill.species >= S || hill.x < 0 || hill.x >= W || hill.y < 0 ||
            hill.y >= H)
            r.fail("initial map has an invalid hill");
    for (const ColonyRecord &c : e.colonies_)
        if (c.species >= S || c.x < 0 || c.x >= W || c.y < 0 || c.y >= H)
            r.fail("invalid colony record");
    for (const Ant &a : e.ants_)
        if (is_alive(a) && (a.species >= S || a.colony >= n_colonies || a.x < 0 || a.x >= W ||
                            a.y < 0 || a.y >= H ||
                            a.caste >= e.species_table_.caste_count(a.species) ||
                            e.grid_.occupancy[e.grid_.idx(a.x, a.y)] !=
                                static_cast<int32_t>(&a - e.ants_.data())))
            r.fail("invalid ant record");
    for (int32_t o : e.grid_.occupancy)
        if (o < NO_ANT || o >= n_ants || (o != NO_ANT && !is_alive(e.ants_[o])))
            r.fail("invalid occupancy layer");
    for (int16_t h : e.grid_.hill_id)
        if (h < NO_HILL || h >= n_colonies)
            r.fail("invalid hill layer");
    for (int slot : e.free_slots_)
        if (slot < 0 || slot >= n_ants || is_alive(e.ants_[slot]))
            r.fail("invalid free slot list");
    for (const auto *v :
         {&e.metrics_.population, &e.metrics_.births, &e.metrics_.kills, &e.metrics_.deaths_combat,
          &e.metrics_.deaths_hazard, &e.metrics_.deaths_age, &e.metrics_.deaths_orphan,
          &e.metrics_.colonies_alive, &e.metrics_.deliveries, &e.metrics_.return_steps_sum})
        if (v->size() != static_cast<size_t>(S))
            r.fail("metrics do not match the species count");
    if (e.metrics_.population_caste.size() != static_cast<size_t>(S) * MAX_CASTES)
        r.fail("caste metrics do not match the species count");

    e.ants_.reserve(static_cast<size_t>(e.cfg_.max_ants_total));
    e.build_derived_layers();
    e.diffusion_buffer_.resize(cells);
    e.rebuild_decay_factors();
    e.initialized_ = true;
    return e;
}

} // namespace formicae
