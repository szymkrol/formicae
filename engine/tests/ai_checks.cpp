// ai_checks.cpp - M2 AI state machine, movement and foraging regression checks. Owner: P2.
#undef NDEBUG
#include <array>
#include <cassert>
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <limits>

#ifdef _MSC_VER
#include <crtdbg.h>
#endif

#include "formicae/ai.hpp"
#include "formicae/engine.hpp"

using namespace formicae;

namespace {

bool close(float a, float b) {
    return std::abs(a - b) < 0.00001f;
}

Config test_config() {
    Config cfg;
    cfg.species = {{"Swarmer", SpeciesStats{}}, {"Enemy", SpeciesStats{}}};
    cfg.colony.hill_radius = 0;
    cfg.colony.initial_energy = 0;
    cfg.food.spawn_prob = 0;
    cfg.pheromone.decay_scale = 0;
    cfg.max_ants_total = 100;
    cfg.species[0].stats.random_move_prob = 0;
    cfg.species[0].stats.accuracy = 1;
    return cfg;
}

MapData test_map(Terrain terrain = Terrain::Grass) {
    MapData m;
    m.width = m.height = 16;
    m.terrain.assign(256, static_cast<uint8_t>(terrain));
    m.food_volume.assign(256, 0);
    m.food_density.assign(256, 0);
    m.colonies = {{2, 2, 0}, {13, 13, 1}, {2, 13, 0}};
    return m;
}

int spawn(Engine &e, int x = 8, int y = 8, int colony = 0, int caste = 0) {
    const int slot = e.spawn_ant(colony, caste, e.grid().idx(x, y));
    assert(slot >= 0);
    return slot;
}

void at(const Engine &e, int slot, int x, int y) {
    assert(e.ants()[slot].x == x && e.ants()[slot].y == y);
    assert(e.grid().occupant(e.grid().idx(x, y)) == slot);
}

float pher(const Engine &e, Channel channel, int x, int y) {
    return e.grid().pher_at(0, static_cast<int>(channel), e.grid().idx(x, y));
}

void block(Engine &e, int x, int y) {
    e.set_terrain(x, y, Terrain::Rock);
}

void returning(Ant &a) {
    a.state = static_cast<uint8_t>(AntState::Returning);
    a.carried_volume = 2;
    a.carried_density = 25;
}

void test_candidates_and_backtracking() {
    Engine e(test_config());
    e.initialize(test_map());
    const int slot = spawn(e);
    Ant &a = e.ants()[slot];
    a.last_dir = static_cast<int8_t>(Dir::E);
    block(e, 8, 7);
    e.set_terrain(8, 9, Terrain::Water);
    ant_update(e, slot);
    at(e, slot, 9, 8); // reverse is excluded while forward is open
    assert(e.grid().occupant(e.grid().idx(8, 8)) == NO_ANT);
    block(e, 9, 7);
    block(e, 10, 8);
    block(e, 9, 9);
    ant_update(e, slot);
    at(e, slot, 8, 8); // reverse becomes legal in a dead end
    assert(a.last_dir == static_cast<int8_t>(Dir::W));

    block(e, 7, 8);
    const int friend_slot = spawn(e, 9, 8);
    a.move_acc = 0;
    for (int tick = 0; tick < 4; ++tick)
        ant_update(e, slot);
    at(e, slot, 8, 8);
    at(e, friend_slot, 9, 8);
    assert(a.move_acc == 2);
    assert(a.trail_age == 2); // waiting consumes neither movement points nor trail steps

    Engine edge(test_config());
    edge.initialize(test_map());
    const int corner = spawn(edge, 0, 0);
    block(edge, 1, 0);
    ant_update(edge, corner);
    at(edge, corner, 0, 1);
}

void test_hill_access() {
    Config cfg = test_config();
    cfg.hostile[1][0] = true; // species 0 is peaceful toward species 1, but cannot enter its hill
    Engine e(cfg);
    e.initialize(test_map());
    const int slot = spawn(e, 12, 13);
    block(e, 12, 12);
    block(e, 12, 14);
    ant_update(e, slot);
    at(e, slot, 11, 13);

    const int ally = spawn(e, 3, 13);
    block(e, 3, 12);
    block(e, 4, 13);
    block(e, 3, 14);
    ant_update(e, ally);
    at(e, ally, 2, 13); // another colony of the same species is friendly
    assert(e.ants()[ally].trail_age == 0);
}

void test_movement_costs() {
    Config cfg = test_config();
    cfg.species[0].stats.speed = 0.5f;
    Engine e(cfg);
    e.initialize(test_map());
    const int slot = spawn(e);
    block(e, 8, 7);
    block(e, 8, 9);
    block(e, 7, 8);
    ant_update(e, slot);
    at(e, slot, 8, 8);
    assert(e.ants()[slot].move_acc == 0.5f);
    assert(e.ants()[slot].trail_age == 0 && pher(e, Channel::Home, 8, 8) == 0);
    ant_update(e, slot);
    at(e, slot, 9, 8);
    assert(e.ants()[slot].move_acc == 0);

    Engine mud(test_config());
    mud.initialize(test_map(Terrain::Mud));
    const int slow = spawn(mud);
    ant_update(mud, slow);
    at(mud, slow, 8, 8);
    ant_update(mud, slow);
    assert(mud.ants()[slow].trail_age == 1 && mud.ants()[slow].move_acc == 0);

    Engine path(test_config());
    path.initialize(test_map(Terrain::Path));
    const int fast = spawn(path);
    for (int tick = 1; tick <= 3; ++tick) {
        ant_update(path, fast);
        assert(path.ants()[fast].trail_age == tick);
        assert(close(path.ants()[fast].move_acc, 0.3f * tick));
    }
}

// Reuse one ant and sample independent decisions with a fixed RNG stream. Broad intervals check
// the specified distribution without tying the tests to individual PCG draws or rounding details.
std::array<int, 4> sample_moves(Engine &e, int slot, AntState state, int heading = -1) {
    std::array<int, 4> counts{};
    Grid &g = e.grid();
    Ant &a = e.ants()[slot];
    const int start = g.idx(8, 8);
    for (int n = 0; n < 12000; ++n) {
        g.occupancy[g.idx(a.x, a.y)] = NO_ANT;
        a.x = a.y = 8;
        g.occupancy[start] = slot;
        a.age = 0;
        a.state = static_cast<uint8_t>(state);
        a.last_dir = static_cast<int8_t>(heading);
        a.timer = 10;
        a.move_acc = 0;
        ant_update(e, slot);
        assert(a.last_dir >= 0);
        ++counts[a.last_dir];
    }
    return counts;
}

void test_movement_weights() {
    Config cfg = test_config();
    // Prevent the sampler's deposits from changing the environment under observation.
    cfg.species[0].stats.a_home = cfg.species[0].stats.a_food = 0;
    cfg.pheromone.hazard_alarm = 0;
    Engine e(cfg);
    e.initialize(test_map());
    const int slot = spawn(e);
    auto counts = sample_moves(e, slot, AntState::Searching, static_cast<int>(Dir::N));
    assert(counts[2] == 0);
    assert(counts[0] > 4800 && counts[0] < 5500); // forward bonus: 3/7
    assert(counts[1] > 3100 && counts[1] < 3800);
    e.deposit(0, Channel::Food, e.grid().idx(9, 8), 0.4f);
    counts = sample_moves(e, slot, AntState::Searching, static_cast<int>(Dir::N));
    assert(counts[1] > 11400); // the example in spec 5.4 gives east about 97%

    e.deposit(0, Channel::Home, e.grid().idx(7, 8), 1);
    counts = sample_moves(e, slot, AntState::Returning);
    assert(counts[3] > 11700); // RETURNING follows HOME, not FOOD

    cfg.species[0].stats.random_move_prob = 1;
    Engine random(cfg);
    random.initialize(test_map());
    const int explorer = spawn(random);
    random.deposit(0, Channel::Food, random.grid().idx(9, 8), 1);
    counts = sample_moves(random, explorer, AntState::Searching);
    for (int count : counts)
        assert(count > 2700 && count < 3300);

    Engine other_species(test_config());
    other_species.initialize(test_map());
    const int isolated = spawn(other_species);
    other_species.deposit(1, Channel::Food, other_species.grid().idx(9, 8), 1);
    counts = sample_moves(other_species, isolated, AntState::Searching);
    for (int count : counts)
        assert(count > 2700 && count < 3300);
}

void test_extreme_movement_weights() {
    Config cfg = test_config();
    cfg.species[0].stats.alpha = 1000;
    cfg.species[0].stats.a_home = 0;
    Engine e(cfg);
    e.initialize(test_map());
    const int slot = spawn(e);
    auto counts = sample_moves(e, slot, AntState::Searching);
    for (int count : counts)
        assert(count > 2700 && count < 3300); // bare ground still has equal, nonzero weights
    e.deposit(0, Channel::Food, e.grid().idx(9, 8), 1);
    counts = sample_moves(e, slot, AntState::Searching);
    assert(counts[1] == 12000);

    cfg.species[0].stats.forward_bonus = 0;
    Engine no_forward(cfg);
    no_forward.initialize(test_map());
    const int walker = spawn(no_forward);
    no_forward.deposit(0, Channel::Food, no_forward.grid().idx(8, 7), 1);
    counts = sample_moves(no_forward, walker, AntState::Searching, static_cast<int>(Dir::N));
    assert(counts[0] == 0 && counts[2] == 0);
    assert(counts[1] > 5700 && counts[1] < 6300);
}

void test_danger_weights() {
    Config cfg = test_config();
    cfg.species[0].stats.a_home = cfg.species[0].stats.a_food = 0;
    cfg.species[0].stats.danger_k = 2;
    cfg.species[0].stats.danger_k_home = -1;
    cfg.pheromone.hazard_alarm = 0;
    Engine e(cfg);
    e.initialize(test_map());
    const int slot = spawn(e);
    e.deposit(0, Channel::Danger, e.grid().idx(9, 8), 1);
    auto counts = sample_moves(e, slot, AntState::Searching);
    assert(counts[1] > 120 && counts[1] < 280); // danger factor clamps to 0.05
    e.deposit(0, Channel::Home, e.grid().idx(8, 8), 0.9f);
    counts = sample_moves(e, slot, AntState::Searching);
    assert(counts[1] > 4500 && counts[1] < 5100); // near home, danger attracts defenders
    counts = sample_moves(e, slot, AntState::Fleeing);
    for (int count : counts)
        assert(count > 2700 && count < 3300); // fleeing ignores danger

    e.deposit(0, Channel::Home, e.grid().idx(8, 7), 1);
    counts = sample_moves(e, slot, AntState::Fleeing);
    assert(counts[0] > 11700);
}

void test_pickup_and_delivery() {
    Engine e(test_config());
    e.initialize(test_map());
    const int slot = spawn(e, 2, 13);
    Ant &a = e.ants()[slot];
    a.last_dir = static_cast<int8_t>(Dir::E);
    e.add_food(e.grid().idx(2, 13), 1, 50);
    e.add_food(e.grid().idx(3, 13), 3, 25);
    e.add_food(e.grid().idx(3, 12), 100, 50); // diagonal is out of reach
    ant_update(e, slot);
    at(e, slot, 2, 13);
    assert(a.state == static_cast<uint8_t>(AntState::Returning));
    assert(a.carried_volume == 2 && a.carried_density == 25 && a.trail_age == 0);
    assert(a.last_dir == static_cast<int8_t>(Dir::W));
    assert(e.grid().food_volume[e.grid().idx(3, 13)] == 1);
    assert(e.grid().food_density[e.grid().idx(3, 13)] == 25);
    assert(close(pher(e, Channel::Food, 2, 13), 0.06f));
    assert(e.colonies()[2].stored_energy == 0); // pickup and delivery are separate actions

    ant_update(e, slot);
    at(e, slot, 2, 13);
    assert(a.state == static_cast<uint8_t>(AntState::Searching));
    assert(a.carried_volume == 0 && a.carried_density == 0 && a.trail_age == 0);
    assert(a.last_dir == static_cast<int8_t>(Dir::E));
    assert(e.colonies()[0].stored_energy == 0 && e.colonies()[2].stored_energy == 50);

    ant_update(e, slot); // ties prefer the current cell, then N/E/S/W
    assert(a.carried_volume == 1 && a.carried_density == 50);
    assert(e.grid().food_volume[e.grid().idx(2, 13)] == 0);
    assert(e.grid().food_density[e.grid().idx(2, 13)] == 0);
    assert(close(pher(e, Channel::Food, 2, 13), 0.18f));
}

void test_trail_aging() {
    Config cfg = test_config();
    cfg.species[0].stats.trail_len_home = 2;
    cfg.species[0].stats.trail_len_food = 2;
    Engine e(cfg);
    e.initialize(test_map());
    const int slot = spawn(e, 2, 2);
    Ant &a = e.ants()[slot];
    a.trail_age = 200;
    ant_update(e, slot);
    assert(a.trail_age == 1);
    assert(close(pher(e, Channel::Home, a.x, a.y), 0.02f));
    ant_update(e, slot);
    assert(a.trail_age == 2);
    assert(pher(e, Channel::Home, a.x, a.y) == 0);

    returning(a);
    a.trail_age = 0;
    ant_update(e, slot);
    assert(a.trail_age == 1);
    assert(close(pher(e, Channel::Food, a.x, a.y), 0.03f));
    a.trail_age = std::numeric_limits<uint16_t>::max();
    ant_update(e, slot);
    assert(a.trail_age == std::numeric_limits<uint16_t>::max());
    assert(pher(e, Channel::Food, a.x, a.y) == 0);

    Engine rich(test_config());
    rich.initialize(test_map());
    const int gatherer = spawn(rich);
    rich.add_food(rich.grid().idx(8, 8), 1, 100);
    rich.deposit(0, Channel::Food, rich.grid().idx(8, 8), 0.95f);
    ant_update(rich, gatherer);
    assert(pher(rich, Channel::Food, 8, 8) == 1);
    assert(rich.ants()[gatherer].last_dir == static_cast<int8_t>(Dir::None));
}

void test_combat_transitions() {
    Engine e(test_config());
    e.initialize(test_map());
    const int slot = spawn(e);
    const int enemy = spawn(e, 9, 8, 1);
    e.add_food(e.grid().idx(8, 8), 10, 20);
    ant_update(e, slot);
    at(e, slot, 8, 8);
    assert(e.ants()[slot].state == static_cast<uint8_t>(AntState::Fighting));
    assert(e.ants()[slot].carried_volume == 0); // attacking takes precedence over pickup
    assert(e.ants()[enemy].health < 10);
    e.kill_ant(enemy, DeathCause::Combat, 0);
    ant_update(e, slot);
    assert(e.ants()[slot].state == static_cast<uint8_t>(AntState::Returning));
    assert(e.ants()[slot].carried_volume == 2); // fight ends and foraging resumes

    for (bool defend : {false, true}) {
        Config cfg = test_config();
        cfg.species[0].stats.defend_while_carrying = defend;
        Engine carrier(cfg);
        carrier.initialize(test_map());
        const int c = spawn(carrier);
        const int foe = spawn(carrier, 9, 8, 1);
        returning(carrier.ants()[c]);
        ant_update(carrier, c);
        assert((carrier.ants()[c].state == static_cast<uint8_t>(AntState::Fighting)) == defend);
        assert((carrier.ants()[foe].health < 10) == defend);
        assert(carrier.ants()[c].carried_volume == 2);
        if (defend) {
            carrier.kill_ant(foe, DeathCause::Combat, 0);
            ant_update(carrier, c);
            assert(carrier.ants()[c].state == static_cast<uint8_t>(AntState::Returning));
        }
    }

    Engine hill(test_config());
    hill.initialize(test_map());
    const int raider = spawn(hill, 12, 13);
    ant_update(hill, raider);
    at(hill, raider, 12, 13);
    assert(hill.ants()[raider].state == static_cast<uint8_t>(AntState::Fighting));
    assert(hill.colonies()[1].health < hill.colonies()[1].max_health);
}

void test_fleeing() {
    Config cfg = test_config();
    cfg.species[0].stats.flee_ticks = 3;
    Engine e(cfg);
    e.initialize(test_map());
    const int slot = spawn(e);
    const int enemy = spawn(e, 9, 8, 1);
    Ant &a = e.ants()[slot];
    a.health = 2;
    returning(a);
    block(e, 8, 7);
    block(e, 8, 9);
    ant_update(e, slot);
    at(e, slot, 7, 8);
    assert(a.state == static_cast<uint8_t>(AntState::Fleeing) && a.timer == 2);
    assert(a.carried_volume == 2 && e.ants()[enemy].health == 10);
    assert(close(pher(e, Channel::Danger, 7, 8), 0.3f));
    assert(pher(e, Channel::Food, 7, 8) == 0);
    ant_update(e, slot);
    assert(a.state == static_cast<uint8_t>(AntState::Fleeing) && a.timer == 1);
    ant_update(e, slot);
    assert(a.state == static_cast<uint8_t>(AntState::Returning) && a.timer == 0);

    const int sheltered = spawn(e, 3, 2);
    Ant &b = e.ants()[sheltered];
    b.state = static_cast<uint8_t>(AntState::Fleeing);
    b.timer = 10;
    block(e, 3, 1);
    block(e, 4, 2);
    block(e, 3, 3);
    ant_update(e, sheltered);
    at(e, sheltered, 2, 2);
    assert(b.state == static_cast<uint8_t>(AntState::Searching) && b.timer == 0);
    assert(b.trail_age == 0);

    const int trapped = spawn(e, 10, 3);
    Ant &c = e.ants()[trapped];
    c.state = static_cast<uint8_t>(AntState::Fleeing);
    c.timer = 1;
    block(e, 10, 2);
    block(e, 11, 3);
    block(e, 10, 4);
    block(e, 9, 3);
    ant_update(e, trapped);
    at(e, trapped, 10, 3);
    assert(c.state == static_cast<uint8_t>(AntState::Searching) && c.timer == 0);
    assert(pher(e, Channel::Danger, 10, 3) == 0); // deposits happen only after moving

    c.state = static_cast<uint8_t>(AntState::Fleeing);
    c.timer = 0;
    ant_update(e, trapped);
    assert(c.timer == 0); // no unsigned underflow for a zero-duration retreat
}

void test_hazards_and_deaths() {
    Engine e(test_config());
    e.initialize(test_map());
    const int slot = spawn(e);
    const int enemy = spawn(e, 9, 8, 1);
    e.set_terrain(8, 8, Terrain::Thorns);
    e.ants()[slot].health = 3.5f;
    ant_update(e, slot);
    assert(e.ants()[slot].state == static_cast<uint8_t>(AntState::Fleeing));
    assert(e.ants()[slot].health == 2.5f && e.ants()[enemy].health == 10);
    assert(close(pher(e, Channel::Danger, 8, 8), 0.3f));

    const int victim = spawn(e, 4, 4);
    returning(e.ants()[victim]);
    e.set_terrain(4, 4, Terrain::Thorns);
    e.ants()[victim].health = 1;
    e.step();
    assert(!is_alive(e.ants()[victim]));
    assert(e.metrics().deaths_hazard[0] == 1);
    assert(e.grid().occupant(e.grid().idx(4, 4)) == NO_ANT);
    assert(e.grid().food_volume[e.grid().idx(4, 4)] == 2);
    assert(close(pher(e, Channel::Danger, 4, 4), 0.8f));

    Engine aged(test_config());
    aged.initialize(test_map());
    const int old = spawn(aged);
    aged.ants()[old].age = aged.stats_of(aged.ants()[old]).max_age - 1;
    aged.set_terrain(8, 8, Terrain::Thorns);
    aged.step();
    assert(aged.metrics().deaths_age[0] == 1 && aged.metrics().deaths_hazard[0] == 0);
    assert(close(pher(aged, Channel::Danger, 8, 8), 0.5f));
    const uint32_t age = aged.ants()[old].age;
    ant_update(aged, old);
    assert(aged.ants()[old].age == age); // dead slots cannot act or die twice

    Engine orphan(test_config());
    orphan.initialize(test_map());
    const int survivor = spawn(orphan);
    on_colony_destroyed(orphan, 0);
    ant_update(orphan, survivor);
    assert(orphan.ants()[survivor].health == 10); // a second same-species hill remains
    on_colony_destroyed(orphan, 2);
    ant_update(orphan, survivor);
    assert(close(orphan.ants()[survivor].health, 9.9f));
    orphan.ants()[survivor].health = 0.05f;
    orphan.step();
    assert(orphan.metrics().deaths_orphan[0] == 1 && !is_alive(orphan.ants()[survivor]));
}

void test_resolved_castes() {
    Config cfg = test_config();
    CasteDef fighter;
    fighter.name = "FIGHTER";
    fighter.carry_mul = 0;
    fighter.max_health_mul = 2;
    fighter.speed_mul = 0.5f;
    fighter.a_home_mul = 2;
    cfg.castes = {{CasteDef{}, fighter}};
    Engine e(cfg);
    e.initialize(test_map());
    const int slot = spawn(e, 8, 8, 0, 1);
    e.add_food(e.grid().idx(8, 8), 10, 50);
    ant_update(e, slot);
    at(e, slot, 8, 8);
    assert(e.ants()[slot].health == 20 && e.ants()[slot].carried_volume == 0);
    assert(e.ants()[slot].state == static_cast<uint8_t>(AntState::Searching));
    ant_update(e, slot);
    const Ant &a = e.ants()[slot];
    assert(a.trail_age == 1);
    assert(close(pher(e, Channel::Home, a.x, a.y), 0.08f * (1 - 1.0f / 400)));
    assert(e.grid().food_volume[e.grid().idx(8, 8)] == 10);
}

void check_occupancy(const Engine &e) {
    int live = 0;
    for (int slot = 0; slot < static_cast<int>(e.ants().size()); ++slot) {
        const Ant &a = e.ants()[slot];
        if (!is_alive(a))
            continue;
        ++live;
        const int cell = e.grid().idx(a.x, a.y);
        assert(e.grid().in_bounds(a.x, a.y) && e.grid().is_passable(cell));
        assert(e.grid().occupant(cell) == slot);
        const int hill = e.grid().hill_at(cell);
        assert(hill == NO_HILL || e.colonies()[hill].species == a.species);
    }
    int occupied = 0;
    for (int cell = 0; cell < e.grid().cells(); ++cell) {
        const int slot = e.grid().occupant(cell);
        if (slot == NO_ANT)
            continue;
        ++occupied;
        assert(slot >= 0 && slot < static_cast<int>(e.ants().size()));
        const Ant &a = e.ants()[slot];
        assert(is_alive(a) && e.grid().idx(a.x, a.y) == cell);
    }
    assert(live == occupied);
    for (float value : e.grid().pher)
        assert(std::isfinite(value) && value >= 0 && value <= 1);
}

void test_foraging_pipeline_and_determinism() {
    Config cfg = test_config();
    cfg.colony.max_population = 1;
    MapData m = test_map(Terrain::Rock);
    m.colonies = {{2, 2, 0}};
    for (int x = 2; x <= 8; ++x)
        m.terrain[2 * m.width + x] = static_cast<uint8_t>(Terrain::Grass);
    m.food_volume[2 * m.width + 8] = 20;
    m.food_density[2 * m.width + 8] = 50;
    Engine corridor(cfg);
    corridor.initialize(m);
    spawn(corridor, 2, 2);
    corridor.step(11);
    assert(corridor.colonies()[0].stored_energy == 0);
    corridor.step();
    assert(corridor.colonies()[0].stored_energy == 100);
    assert(corridor.grid().food_volume[2 * m.width + 8] == 18);
    assert(pher(corridor, Channel::Home, 5, 2) > 0);
    assert(pher(corridor, Channel::Food, 5, 2) > 0);
    check_occupancy(corridor);

    cfg = test_config();
    cfg.colony.initial_energy = 600;
    cfg.species[0].stats.max_age = 250;
    cfg.species[1].stats.max_age = 250;
    m = test_map();
    for (int y = 4; y < 12; ++y) {
        m.terrain[y * m.width + 7] = static_cast<uint8_t>(Terrain::Thorns);
        m.food_volume[y * m.width + 5] = 30;
        m.food_density[y * m.width + 5] = 25;
    }
    Engine a(cfg), b(cfg);
    a.initialize(m);
    b.initialize(m);
    for (int tick = 0; tick < 1100; ++tick) {
        a.step();
        b.step();
        check_occupancy(a);
        assert(a.ants().size() == b.ants().size());
        for (size_t slot = 0; slot < a.ants().size(); ++slot)
            assert(std::memcmp(&a.ants()[slot], &b.ants()[slot], sizeof(Ant)) == 0);
        assert(a.grid().occupancy == b.grid().occupancy);
        assert(a.grid().pher == b.grid().pher);
        assert(a.grid().food_volume == b.grid().food_volume);
        assert(a.rng().state() == b.rng().state());
    }
}

} // namespace

int main() {
#ifdef _MSC_VER
    // Report assertion failures to CTest instead of opening an unattended Windows dialog.
    _CrtSetReportMode(_CRT_ASSERT, _CRTDBG_MODE_FILE);
    _CrtSetReportFile(_CRT_ASSERT, _CRTDBG_FILE_STDERR);
    _set_abort_behavior(0, _WRITE_ABORT_MSG | _CALL_REPORTFAULT);
#endif
    test_candidates_and_backtracking();
    test_hill_access();
    test_movement_costs();
    test_movement_weights();
    test_extreme_movement_weights();
    test_danger_weights();
    test_pickup_and_delivery();
    test_trail_aging();
    test_combat_transitions();
    test_fleeing();
    test_hazards_and_deaths();
    test_resolved_castes();
    test_foraging_pipeline_and_determinism();
    std::puts("ai_checks: OK");
}
