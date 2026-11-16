// ai.cpp - ant behaviour (spec sections 5.3 and 5.4). Owner: P2 (M2).
#include "formicae/ai.hpp"

#include <algorithm>
#include <array>
#include <cmath>
#include <limits>

#include "formicae/combat.hpp"
#include "formicae/engine.hpp"

namespace formicae {

namespace {

constexpr float kGradMin = 0.5f;
constexpr float kGradMax = 2.0f;

bool on_friendly_hill(const Engine &e, const Ant &a, int cell) {
    const int hill = e.grid().hill_at(cell);
    return hill != NO_HILL && e.colonies()[hill].alive && e.colonies()[hill].species == a.species;
}

void resume_foraging(Ant &a) {
    a.state =
        static_cast<uint8_t>(a.carried_volume > 0.0f ? AntState::Returning : AntState::Searching);
}

void reverse_heading(Ant &a) {
    a.last_dir = static_cast<int8_t>(opposite(static_cast<Dir>(a.last_dir)));
}

bool is_lost(const Ant &a, const ResolvedStats &st) {
    if (st.lost_mult <= 0.0f)
        return false;
    const float limit =
        st.lost_mult * (a.state == static_cast<uint8_t>(AntState::Searching) ? st.trail_len_home
                                                                             : st.trail_len_food);
    return static_cast<float>(a.trail_age) >= limit;
}

void deposit_trail(Engine &e, const Ant &a, const ResolvedStats &st, int cell) {
    if (a.state == static_cast<uint8_t>(AntState::Fleeing)) {
        e.deposit(a.species, Channel::Danger, cell, e.config().pheromone.hazard_alarm);
        return;
    }

    const bool searching = a.state == static_cast<uint8_t>(AntState::Searching);
    const float length = searching ? st.trail_len_home : st.trail_len_food;
    const float fade = std::max(0.0f, 1.0f - a.trail_age / length);
    const float amount =
        searching ? st.a_home * fade
                  : st.a_food * fade *
                        std::min(1.0f, a.carried_density / e.config().pheromone.food_density_ref);
    e.deposit(a.species, searching ? Channel::Home : Channel::Food, cell, amount);
}

void move_ant(Engine &e, int slot, const ResolvedStats &st) {
    Ant &a = e.ants()[slot];
    Grid &g = e.grid();
    const int from = g.idx(a.x, a.y);
    const Neighbors4 neighbors = g.neighbors4(from);
    const int reverse = static_cast<int>(opposite(static_cast<Dir>(a.last_dir)));
    std::array<int, 4> directions{};
    int count = 0;
    int fallback = -1;
    for (int dir = 0; dir < 4; ++dir) {
        const int cell = neighbors.cell[dir];
        if (cell < 0 || !g.is_passable(cell) || g.occupant(cell) != NO_ANT)
            continue;
        const int hill = g.hill_at(cell);
        if (hill != NO_HILL && e.colonies()[hill].species != a.species)
            continue;
        if (dir == reverse)
            fallback = dir;
        else
            directions[count++] = dir;
    }
    if (count == 0 && fallback >= 0)
        directions[count++] = fallback;
    if (count == 0)
        return;

    const bool fleeing = a.state == static_cast<uint8_t>(AntState::Fleeing);
    const bool searching = a.state == static_cast<uint8_t>(AntState::Searching);
    const bool returning = a.state == static_cast<uint8_t>(AntState::Returning);
    const bool lost = (searching || returning) && is_lost(a, st);
    const bool lost_searching = searching && lost && a.carried_volume <= 0.0f;
    const Channel channel = (searching && !lost_searching) ? Channel::Food : Channel::Home;
    const PheromoneParams &pp = e.config().pheromone;
    const MovementParams &mv = e.config().movement;
    const float *plane = g.plane(a.species, static_cast<int>(channel));
    auto tau_at = [&](int dx, int dy) {
        const int x = a.x + dx;
        const int y = a.y + dy;
        return g.in_bounds(x, y) ? plane[g.idx(x, y)] : 0.0f;
    };
    float tau_max = 0.0f;
    float nx = 0.0f;
    float ny = 0.0f;
    if (pp.grad_beta > 0.0f) {
        const float nw = tau_at(-1, -1), n = tau_at(0, -1), ne = tau_at(1, -1);
        const float w = tau_at(-1, 0), c = tau_at(0, 0), e0 = tau_at(1, 0);
        const float sw = tau_at(-1, 1), s = tau_at(0, 1), se = tau_at(1, 1);
        tau_max = std::clamp(std::max({nw, n, ne, w, c, e0, sw, s, se}), 0.0f, 1.0f);
        const float gx = (ne + 2.0f * e0 + se) - (nw + 2.0f * w + sw);
        const float gy = (sw + 2.0f * s + se) - (nw + 2.0f * n + ne);
        nx = gx * 0.25f;
        ny = gy * 0.25f;
    } else {
        for (int dy = -1; dy <= 1; ++dy)
            for (int dx = -1; dx <= 1; ++dx)
                tau_max = std::max(tau_max, tau_at(dx, dy));
        tau_max = std::clamp(tau_max, 0.0f, 1.0f);
    }

    const float s_trail = std::min(1.0f, tau_max / mv.noise_tau_ref);
    const float damp_eff = std::clamp(st.noise_damp * mv.noise_damp_scale, 0.0f, 1.0f);
    const float p_rnd = st.random_move_prob * (1.0f - damp_eff * s_trail);
    const float r = e.rng().next_float();

    int choice = 0;
    if (r < p_rnd) {
        choice = e.rng().next_int(count);
    } else {
        std::array<float, 4> nav{1.0f, 1.0f, 1.0f, 1.0f};
        const bool use_nav = fleeing || returning || lost_searching;
        const float beta_eff = st.nav_beta * mv.nav_scale;
        if (use_nav && beta_eff > 0.0f && e.colonies()[a.colony].alive) {
            const ColonyRecord &home = e.colonies()[a.colony];
            const float hx = static_cast<float>(home.x - a.x);
            const float hy = static_cast<float>(home.y - a.y);
            const float d2 = hx * hx + hy * hy;
            if (d2 > 0.0f) {
                const float inv = 1.0f / std::sqrt(d2);
                const std::array<float, 4> align{-hy * inv, hx * inv, hy * inv, -hx * inv};
                const float conf = (fleeing || returning || lost_searching) ? 1.0f : 0.0f;
                const float k = beta_eff * conf * (1.0f - tau_max);
                for (int dir = 0; dir < 4; ++dir)
                    nav[dir] = std::clamp(1.0f + k * align[dir], mv.nav_min, mv.nav_max);
            }
        }

        const float danger_k = g.pher_at(a.species, static_cast<int>(Channel::Home), from) >= 0.9f
                                   ? st.danger_k_home
                                   : st.danger_k;
        std::array<double, 4> weights{};
        double largest_trail = 0.0;
        for (int k = 0; k < count; ++k) {
            const int dir = directions[k];
            if (dir == a.last_dir && st.forward_bonus == 0.0f)
                continue;
            weights[k] = static_cast<double>(e.config().pheromone.epsilon) +
                         g.pher_at(a.species, static_cast<int>(channel), neighbors.cell[dir]);
            largest_trail = std::max(largest_trail, weights[k]);
        }
        double total = 0.0;
        for (int k = 0; k < count; ++k) {
            if (weights[k] == 0.0)
                continue;
            const int dir = directions[k];
            const int cell = neighbors.cell[dir];
            const float heading = dir == a.last_dir ? st.forward_bonus : 1.0f;
            const float alarm = g.pher_at(a.species, static_cast<int>(Channel::Danger), cell);
            const float danger = fleeing ? 1.0f : std::clamp(1.0f - danger_k * alarm, 0.05f, 3.0f);
            // Divide out a common factor so even large alpha values retain a nonzero total.
            weights[k] = std::pow(weights[k] / largest_trail, st.alpha) * heading * danger;
            if (pp.grad_beta > 0.0f) {
                const float align_g = nx * DX[dir] + ny * DY[dir];
                const float grad = std::clamp(1.0f + pp.grad_beta * align_g, kGradMin, kGradMax);
                weights[k] *= grad;
            }
            weights[k] *= nav[dir];
            total += weights[k];
        }
        double roll = e.rng().next_float() * total;
        choice = count - 1;
        for (int k = 0; k < count; ++k) {
            roll -= weights[k];
            if (roll < 0.0f) {
                choice = k;
                break;
            }
        }
    }

    const int dir = directions[choice];
    const int to = neighbors.cell[dir];
    const float cost = g.cost_at(to);
    if (a.move_acc < cost)
        return;

    a.move_acc -= cost;
    g.occupancy[from] = NO_ANT;
    g.occupancy[to] = slot;
    a.x = static_cast<int16_t>(g.x_of(to));
    a.y = static_cast<int16_t>(g.y_of(to));
    a.last_dir = static_cast<int8_t>(dir);
    // Saturation prevents old trails from becoming fresh again after uint16_t wraps.
    if (a.trail_age < std::numeric_limits<uint16_t>::max())
        ++a.trail_age;
    if (a.state == static_cast<uint8_t>(AntState::Searching) && on_friendly_hill(e, a, to))
        a.trail_age = 0;
    deposit_trail(e, a, st, to);
}

bool pick_up_food(Engine &e, Ant &a, const ResolvedStats &st, int cell) {
    if (a.carried_volume > 0.0f || st.carry_capacity <= 0.0f)
        return false;

    Grid &g = e.grid();
    int source = cell;
    for (int neighbor : g.neighbors4(cell).cell)
        if (neighbor >= 0 && g.food_volume[neighbor] > g.food_volume[source])
            source = neighbor;
    if (g.food_volume[source] <= 0.0f)
        return false;

    a.carried_volume = std::min(st.carry_capacity, g.food_volume[source]);
    a.carried_density = g.food_density[source];
    g.food_volume[source] -= a.carried_volume;
    if (g.food_volume[source] == 0.0f)
        g.food_density[source] = 0.0f;
    a.state = static_cast<uint8_t>(AntState::Returning);
    a.trail_age = 0;
    reverse_heading(a);
    deposit_trail(e, a, st, cell);
    return true;
}

} // namespace

void ant_update(Engine &e, int slot) {
    Ant &a = e.ants()[slot];
    if (!is_alive(a))
        return;
    const ResolvedStats &st = e.stats_of(a);
    if (a.health <= 0.0f) {
        e.kill_ant(slot, DeathCause::Combat);
        return;
    }
    if (a.age >= st.max_age || ++a.age >= st.max_age) {
        e.kill_ant(slot, DeathCause::Age);
        return;
    }
    // Orphanhood is species-wide: another colony can support survivors of a destroyed nest.
    if (e.metrics().colonies_alive[a.species] == 0) {
        a.health -= st.orphan_loss * st.max_health;
        if (a.health <= 0.0f) {
            e.kill_ant(slot, DeathCause::Orphan);
            return;
        }
    }

    Grid &g = e.grid();
    const int cell = g.idx(a.x, a.y);
    a.move_acc = std::min(2.0f, a.move_acc + st.speed);
    if (g.hazard[cell] > 0.0f) {
        a.health -= g.hazard[cell];
        e.deposit(a.species, Channel::Danger, cell, e.config().pheromone.hazard_alarm);
        if (a.health <= 0.0f) {
            e.kill_ant(slot, DeathCause::Hazard);
            return;
        }
    }

    const Target target = find_target(e, slot);
    const bool enemy_adjacent = target.kind != Target::Kind::None;
    if (enemy_adjacent && a.health / st.max_health < st.flee_threshold) {
        a.state = static_cast<uint8_t>(AntState::Fleeing);
        a.timer = static_cast<uint8_t>(std::clamp(st.flee_ticks, 0, 255));
    }
    // Fleeing must take precedence over attacking, including the tick that starts the retreat.
    if (a.state == static_cast<uint8_t>(AntState::Fleeing)) {
        if (a.timer > 0 && !on_friendly_hill(e, a, cell))
            move_ant(e, slot, st);
        if (a.timer > 0)
            --a.timer;
        const bool at_home = on_friendly_hill(e, a, g.idx(a.x, a.y));
        if (a.timer == 0 || at_home) {
            a.timer = 0;
            resume_foraging(a);
            if (at_home && a.carried_volume == 0.0f)
                a.trail_age = 0;
        }
        return;
    }
    if (enemy_adjacent &&
        (a.state != static_cast<uint8_t>(AntState::Returning) || st.defend_while_carrying)) {
        a.state = static_cast<uint8_t>(AntState::Fighting);
        resolve_attack(e, slot, target);
        return;
    }
    if (a.state == static_cast<uint8_t>(AntState::Fighting))
        resume_foraging(a);

    if (a.state == static_cast<uint8_t>(AntState::Searching)) {
        if (on_friendly_hill(e, a, cell))
            a.trail_age = 0;
        if (pick_up_food(e, a, st, cell))
            return;
    } else if (a.state == static_cast<uint8_t>(AntState::Returning) &&
               on_friendly_hill(e, a, cell)) {
        e.metrics().deliveries[a.species] += 1;
        e.metrics().return_steps_sum[a.species] += a.trail_age;
        e.colonies()[g.hill_at(cell)].stored_energy +=
            static_cast<double>(a.carried_volume) * a.carried_density;
        a.carried_volume = 0.0f;
        a.carried_density = 0.0f;
        a.state = static_cast<uint8_t>(AntState::Searching);
        a.trail_age = 0;
        reverse_heading(a);
        return;
    }
    move_ant(e, slot, st);
}

} // namespace formicae
