// config.cpp - Config defaults and validation. Owner: P1 (M1), validation rules extended by P4
// (M0).
#include <array>
#include <cmath>
#include <sstream>
#include <stdexcept>
#include <string>
#include <vector>

#include "formicae/config.hpp"

namespace formicae {

namespace {

// Terrain table order is fixed by the terrain ids of spec section 2.
constexpr std::array<const char *, 7> TERRAIN_NAMES = {"GRASS", "SAND",  "MUD",   "PATH",
                                                       "ROCK",  "WATER", "THORNS"};

std::string fmt(double v) {
    std::ostringstream out;
    out << v;
    return out.str();
}

} // namespace

void Config::apply_defaults() {
    if (terrain.empty()) {
        terrain = {
            {"GRASS", 1.0f, 1.0f, true, 0.0f},  {"SAND", 1.5f, 2.0f, true, 0.0f},
            {"MUD", 2.0f, 0.5f, true, 0.0f},    {"PATH", 0.7f, 1.2f, true, 0.0f},
            {"ROCK", 1.0f, 1.0f, false, 0.0f},  {"WATER", 1.0f, 1.0f, false, 0.0f},
            {"THORNS", 1.5f, 1.0f, true, 1.0f},
        };
    }
    castes.resize(species.size());
    for (auto &list : castes)
        if (list.empty())
            list.push_back(CasteDef{}); // STANDARD
    // Default hostility: different species are hostile, same species are allies.
    bool any = false;
    for (auto &row : hostile)
        for (bool b : row)
            any = any || b;
    if (!any)
        for (int a = 0; a < S_MAX; ++a)
            for (int b = 0; b < S_MAX; ++b)
                hostile[a][b] = (a != b);
}

void Config::validate() const {
    std::vector<std::string> problems;
    auto bad = [&](const std::string &msg) { problems.push_back(msg); };
    // Range checks written as !(in range) so that NaN is rejected as well.
    auto at_least = [&](const std::string &path, double v, double lo) {
        if (!(v >= lo) || !std::isfinite(v))
            bad(path + " must be >= " + fmt(lo));
    };
    auto above = [&](const std::string &path, double v, double lo) {
        if (!(v > lo) || !std::isfinite(v))
            bad(path + " must be > " + fmt(lo));
    };
    auto within = [&](const std::string &path, double v, double lo, double hi) {
        if (!(v >= lo && v <= hi))
            bad(path + " must be in [" + fmt(lo) + ", " + fmt(hi) + "]");
    };
    auto finite = [&](const std::string &path, double v) {
        if (!std::isfinite(v))
            bad(path + " must be a finite number");
    };

    if (species.empty() || species.size() > static_cast<size_t>(S_MAX))
        bad("species: need 1.." + std::to_string(S_MAX) + " entries, got " +
            std::to_string(species.size()));
    if (max_ants_total <= 0)
        bad("max_ants_total must be positive");

    if (terrain.size() != TERRAIN_NAMES.size())
        bad("terrain: need the 7 terrain definitions of spec section 2");
    for (size_t i = 0; i < terrain.size(); ++i) {
        const std::string path = "terrain[" + std::to_string(i) + "]";
        const TerrainDef &t = terrain[i];
        // The engine indexes this table by terrain id, so the order is fixed (spec section 2).
        if (i < TERRAIN_NAMES.size() && t.name != TERRAIN_NAMES[i])
            bad(path + ".name must be " + TERRAIN_NAMES[i] + " (terrain ids are fixed)");
        above(path + ".move_cost", t.move_cost, 0);
        at_least(path + ".evap_mod", t.evap_mod, 0);
        at_least(path + ".hazard_damage", t.hazard_damage, 0);
    }

    for (size_t i = 0; i < species.size(); ++i) {
        const std::string path = "species[" + std::to_string(i) + "]";
        const SpeciesStats &s = species[i].stats;
        if (species[i].name.empty())
            bad(path + ".name must be a non-empty string");
        above(path + ".max_health", s.max_health, 0);
        if (s.max_age < 1)
            bad(path + ".max_age must be >= 1");
        within(path + ".flee_threshold", s.flee_threshold, 0, 1);
        within(path + ".flee_ticks", s.flee_ticks, 0, 255); // stored in the u8 Ant.timer
        if (!(s.speed > 0.0f && s.speed <= 1.0f))
            bad(path + ".speed must be in (0, 1]");
        within(path + ".random_move_prob", s.random_move_prob, 0, 1);
        at_least(path + ".alpha", s.alpha, 0);
        at_least(path + ".forward_bonus", s.forward_bonus, 0);
        at_least(path + ".nav_beta", s.nav_beta, 0);
        within(path + ".noise_damp", s.noise_damp, 0, 1);
        at_least(path + ".damage", s.damage, 0);
        at_least(path + ".armor", s.armor, 0);
        within(path + ".accuracy", s.accuracy, 0, 1);
        above(path + ".cost", s.cost, 0);
        above(path + ".carry_capacity", s.carry_capacity, 0);
        at_least(path + ".a_home", s.a_home, 0);
        at_least(path + ".a_food", s.a_food, 0);
        above(path + ".trail_len_home", s.trail_len_home, 0);
        above(path + ".trail_len_food", s.trail_len_food, 0);
        finite(path + ".danger_k", s.danger_k);
        finite(path + ".danger_k_home", s.danger_k_home);
        within(path + ".orphan_loss", s.orphan_loss, 0, 1);
        at_least(path + ".lost_mult", s.lost_mult, 0);

        float ratio_total = 0.0f;
        for (int c = 0; c < MAX_CASTES; ++c) {
            const float w = species[i].caste_ratio[c];
            const std::string rpath = path + ".caste_ratio[" + std::to_string(c) + "]";
            at_least(rpath, w, 0);
            if (w > 0.0f && i < castes.size() && static_cast<size_t>(c) >= castes[i].size())
                bad(rpath + " weights a caste the species does not define");
            if (w > 0.0f)
                ratio_total += w;
        }
        if (!(ratio_total > 0.0f))
            bad(path + ".caste_ratio needs at least one positive weight");

        if (i >= castes.size())
            continue;
        if (castes[i].size() > static_cast<size_t>(MAX_CASTES))
            bad(path + ".castes: at most " + std::to_string(MAX_CASTES) + " entries");
        for (size_t c = 0; c < castes[i].size(); ++c) {
            const std::string cpath = path + ".castes[" + std::to_string(c) + "]";
            const CasteDef &cd = castes[i][c];
            if (cd.name.empty())
                bad(cpath + ".name must be a non-empty string");
            at_least(cpath + ".max_health_mul", cd.max_health_mul, 0);
            at_least(cpath + ".damage_mul", cd.damage_mul, 0);
            at_least(cpath + ".armor_mul", cd.armor_mul, 0);
            at_least(cpath + ".speed_mul", cd.speed_mul, 0);
            at_least(cpath + ".carry_mul", cd.carry_mul, 0);
            at_least(cpath + ".cost_mul", cd.cost_mul, 0);
            at_least(cpath + ".a_home_mul", cd.a_home_mul, 0);
            at_least(cpath + ".a_food_mul", cd.a_food_mul, 0);
            finite(cpath + ".random_move_prob_add", cd.random_move_prob_add);
            finite(cpath + ".danger_k_add", cd.danger_k_add);
            within(cpath + ".defend_while_carrying", cd.defend_while_carrying, -1, 1);
        }
    }

    const PheromoneParams &p = pheromone;
    for (int c = 0; c < NUM_CHANNELS; ++c)
        within("pheromone.decay[" + std::to_string(c) + "]", p.decay[c], 0, 1);
    within("pheromone.decay_scale", p.decay_scale, 0, 10);
    within("pheromone.diffusion", p.diffusion, 0, 0.2);
    within("pheromone.cutoff", p.cutoff, 0, 1);
    within("pheromone.hit_alarm", p.hit_alarm, 0, 1);
    within("pheromone.death_alarm", p.death_alarm, 0, 1);
    within("pheromone.hazard_alarm", p.hazard_alarm, 0, 1);
    within("pheromone.home_beacon", p.home_beacon, 0, 1);
    above("pheromone.food_density_ref", p.food_density_ref, 0);
    above("pheromone.epsilon", p.epsilon, 0);
    within("pheromone.grad_beta", p.grad_beta, 0, 8);

    above("movement.nav_min", movement.nav_min, 0);
    if (!(movement.nav_max >= movement.nav_min))
        bad("movement.nav_max must be >= movement.nav_min");
    above("movement.noise_tau_ref", movement.noise_tau_ref, 0);
    within("movement.nav_scale", movement.nav_scale, 0, 4);
    within("movement.noise_damp_scale", movement.noise_damp_scale, 0, 2);

    within("food.spawn_interval", food.spawn_interval, 1, 10000);
    within("food.spawn_prob", food.spawn_prob, 0, 1);
    at_least("food.max_food_cells", food.max_food_cells, 0);
    within("food.cluster_radius_min", food.cluster_radius_min, 1, 3);
    within("food.cluster_radius_max", food.cluster_radius_max, 1, 3);
    within("food.volume_min", food.volume_min, 50, 200);
    within("food.volume_max", food.volume_max, 50, 200);
    within("food.density_min", food.density_min, 10, 50);
    within("food.density_max", food.density_max, 10, 50);
    if (food.cluster_radius_min > food.cluster_radius_max)
        bad("food.cluster_radius_min must be <= food.cluster_radius_max");
    if (food.volume_min > food.volume_max)
        bad("food.volume_min must be <= food.volume_max");
    if (food.density_min > food.density_max)
        bad("food.density_min must be <= food.density_max");

    at_least("colony.hill_radius", colony.hill_radius, 0);
    above("colony.max_health", colony.max_health, 0);
    at_least("colony.initial_energy", colony.initial_energy, 0);
    if (colony.max_population < 1)
        bad("colony.max_population must be >= 1");
    within("colony.spawn_cooldown", colony.spawn_cooldown, 0, 255); // stored in a u8 cooldown
    above("colony.loot_density", colony.loot_density, 0);

    if (!problems.empty()) {
        std::string msg = "invalid config:";
        for (const auto &line : problems)
            msg += "\n  " + line;
        throw std::invalid_argument(msg);
    }
}

} // namespace formicae
