// config.hpp - validated configuration structs (spec sections 5.2, 7, 11). Owner: P1 (M1);
// species/caste fields are owned by P2, colony/food fields by P3.
// The Python side loads and validates the JSON (python/antsim_ui/config.py) and passes a dict;
// bindings/module.cpp converts that dict into a Config.
#pragma once
#include <array>
#include <cstdint>
#include <string>
#include <vector>

#include "formicae/types.hpp"

namespace formicae {

struct TerrainDef {
    std::string name;
    float move_cost = 1.0f;
    float evap_mod = 1.0f;
    bool passable = true;
    float hazard_damage = 0.0f; // damage per tick to ants standing here
};

// One species' base stats (spec 5.2). Castes rescale these (see CasteDef, SpeciesTable).
struct SpeciesStats {
    // survival
    float max_health = 10;
    uint32_t max_age = 4000;
    float flee_threshold = 0.3f;
    int flee_ticks = 15;
    // movement
    float speed = 1.0f; // cells per tick, (0, 1]
    float random_move_prob = 0.10f;
    float alpha = 2.0f;
    float forward_bonus = 1.5f;
    // navigation
    float nav_beta = 1.5f;
    float noise_damp = 0.8f;
    // memory / mill mitigation
    float p_fid = 0.95f;
    float goal_beta = 2.0f;
    float goal_random_move_frac = 1.0f / 3.0f;
    int explore_ticks = 40;
    float food_erase_factor = 0.3f;
    float food_erase_tau = 0.1f;
    float food_erase_delta = 0.02f;
    bool deposit_home_while_searching = true;
    // combat
    float damage = 2;
    float armor = 0;
    float accuracy = 0.7f;
    bool defend_while_carrying = false;
    // economy
    float cost = 60;
    float carry_capacity = 2;
    // pheromones
    float a_home = 0.06f;
    float a_food = 0.18f;
    float trail_len_home = 600;
    float trail_len_food = 600;
    float danger_k = 0.8f;
    float danger_k_home = -0.5f;
    // colony
    float orphan_loss = 0.01f; // fraction of max_health lost per tick without a live colony
    // lost-ant threshold multiplier: 0 disables
    float lost_mult = 1.0f;
};

struct SpeciesDef {
    std::string name;
    SpeciesStats stats;
    // Spawn weights per caste for this species' colonies (spec 5.2, 7.1); STANDARD only by default.
    std::array<float, MAX_CASTES> caste_ratio{1.0f, 0.0f, 0.0f, 0.0f};
};

// A caste is a role variant inside one species (spec 5.2). Index 0 is STANDARD (all neutral).
struct CasteDef {
    std::string name = "STANDARD";
    float max_health_mul = 1, damage_mul = 1, armor_mul = 1, speed_mul = 1, carry_mul = 1,
          cost_mul = 1;
    float random_move_prob_add = 0;
    float a_home_mul = 1, a_food_mul = 1;
    float danger_k_add = 0;
    int defend_while_carrying = -1; // -1 inherit, 0 no, 1 yes
};

struct PheromoneParams {
    std::array<float, NUM_CHANNELS> decay = {0.0015f, 0.001f,
                                             0.015f}; // rho per channel (HOME, FOOD, DANGER)
    float decay_scale = 1.0f;                         // runtime tunable
    float diffusion = 0.03f;                          // runtime tunable, 0 = off
    float cutoff = 0.001f;                            // values below become 0
    float hit_alarm = 0.4f;                           // DANGER deposited at a hit (both species)
    float death_alarm = 0.5f;    // DANGER deposited at a death (victim's species)
    float hazard_alarm = 0.3f;   // DANGER deposited by an ant on THORNS / while fleeing
    float home_beacon = P_MAX;   // HOME value kept on own hill cells
    float food_density_ref = 50; // D_REF
    float epsilon = 0.05f;       // floor in movement weights
    float grad_beta = 2.0f;      // gradient bias strength (0 = no bias, default 2.0)
    float tau_cap = 1.0f;        // soft cap for HOME/FOOD deposits; 1.0 = legacy hard cap
};

struct MovementParams {
    float nav_min = 0.3f;
    float nav_max = 2.0f;
    float noise_tau_ref = 0.3f;
    float nav_scale = 1.0f;        // runtime-only, not JSON
    float noise_damp_scale = 1.0f; // runtime-only, not JSON
    // Jam avoidance (stretch, spec 13.2 P2): an ant with no free cell may swap places with a
    // same-species ant heading straight at it. Off by default, so default runs are unchanged.
    bool friendly_swap = false;
};

struct FoodParams {
    int spawn_interval = 50; // runtime tunable
    float spawn_prob = 0.5f; // runtime tunable
    int max_food_cells = 2000;
    int cluster_radius_min = 1, cluster_radius_max = 3;
    float volume_min = 50, volume_max = 200;
    float density_min = 10, density_max = 50;
};

struct ColonyParams {
    int hill_radius = 2; // footprint is (2r+1)^2 cells
    float max_health = 1000;
    float initial_energy = 600;
    uint32_t max_population = 30000;
    int spawn_cooldown = 2;  // ticks between two spawns
    float loot_density = 25; // energy per volume unit when a colony is destroyed
};

struct Config {
    uint64_t sim_seed = 1;
    int max_ants_total = 150000;
    bool enable_heatmaps = false;    // stretch
    std::vector<TerrainDef> terrain; // indexed by Terrain id
    std::vector<SpeciesDef> species; // size <= S_MAX
    std::vector<std::vector<CasteDef>>
        castes; // [species] -> up to MAX_CASTES; empty = STANDARD only
    std::array<std::array<bool, S_MAX>, S_MAX>
        hostile{}; // hostile[a][b]; default: different species
    PheromoneParams pheromone;
    MovementParams movement;
    FoodParams food;
    ColonyParams colony;

    // Fills defaults (terrain table of spec 2, hostility matrix) for unset parts.
    void apply_defaults();
    // Throws std::invalid_argument listing every problem (bad ranges, S > S_MAX, ...).
    void validate() const;
};

} // namespace formicae
