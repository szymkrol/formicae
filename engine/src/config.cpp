// config.cpp - Config defaults and validation. Owner: P1 (M1), validation rules extended by P4 (M0).
#include <sstream>
#include <stdexcept>

#include "antsim/config.hpp"

namespace antsim {

void Config::apply_defaults() {
  if (terrain.empty()) {
    terrain = {
        {"GRASS", 1.0f, 1.0f, true, 0.0f}, {"SAND", 1.5f, 2.0f, true, 0.0f},
        {"MUD", 2.0f, 0.5f, true, 0.0f},   {"PATH", 0.7f, 1.2f, true, 0.0f},
        {"ROCK", 1.0f, 1.0f, false, 0.0f}, {"WATER", 1.0f, 1.0f, false, 0.0f},
        {"THORNS", 1.5f, 1.0f, true, 1.0f},
    };
  }
  castes.resize(species.size());
  for (auto& list : castes)
    if (list.empty()) list.push_back(CasteDef{});  // STANDARD
  // Default hostility: different species are hostile, same species are allies.
  bool any = false;
  for (auto& row : hostile) for (bool b : row) any = any || b;
  if (!any)
    for (int a = 0; a < S_MAX; ++a)
      for (int b = 0; b < S_MAX; ++b) hostile[a][b] = (a != b);
}

void Config::validate() const {
  std::ostringstream err;
  auto bad = [&](const char* msg) { err << msg << "\n"; };
  if (species.empty() || species.size() > static_cast<size_t>(S_MAX)) bad("species: need 1..S_MAX entries");
  if (terrain.size() != 7) bad("terrain: need the 7 terrain definitions of spec section 2");
  if (max_ants_total <= 0) bad("max_ants_total must be positive");
  for (const auto& s : species) {
    if (s.stats.speed <= 0.0f || s.stats.speed > 1.0f) bad("species.speed must be in (0, 1]");
    if (s.stats.max_health <= 0.0f) bad("species.max_health must be positive");
    // TODO(P4): check every remaining range of spec section 5.2 / 11.
  }
  if (colony.hill_radius < 0) bad("colony.hill_radius must be >= 0");
  if (pheromone.decay_scale < 0.0f) bad("pheromone.decay_scale must be >= 0");
  const std::string msg = err.str();
  if (!msg.empty()) throw std::invalid_argument(msg);
}

}  // namespace antsim
