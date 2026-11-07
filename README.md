# Formicae ex machina - an ant simulation project

Real-time ant colony simulator: C++20 engine (`engine/`), Python front end (`python/formicae_ui/`),
pybind11 module `formicae`. The full technical specification is in `docs/SPEC.md`.

## Run it (uv)

You need two things on your machine: [uv](https://docs.astral.sh/uv/) and a C++ compiler
(GCC >= 12 or Clang >= 15; on Debian/Ubuntu: `sudo apt install build-essential`). uv downloads the
right Python (3.13, see `.python-version`) and creates its own virtual environment in `.venv/`, so
the "externally-managed-environment" error of `pip install` does not apply. Never use `pip install`
directly; use `uv` instead.

```bash
# 1. install uv once (any one of these)
curl -LsSf https://astral.sh/uv/install.sh | sh      # or: pipx install uv   /   sudo apt install uv

# 2. from the project directory
uv sync                       # creates .venv, installs dependencies, builds the C++ module (first run ~1 min)

# 3. run
uv run formicae-ui --mock       # UI with the mock engine: dots move, no C++ needed
uv run formicae-ui              # UI with the real C++ engine (ants appear once P3 implements spawning)
uv run formicae-ui --map-seed 7 --sim-seed 3 --config configs/default.json

# 4. check
uv run pytest                 # API tests: mock engine and the real C++ module
make cpp-test                 # plain CMake build and all C++ regression checks
uv run ruff check .           # lint
```

`make` shortcuts: `make sync`, `make run`, `make run-mock`, `make test`, `make cpp-test`, `make lint`,
`make format`, `make clean`. After you edit any C++ file, `uv run ...` or `uv sync` rebuilds the
module automatically. Headless check (no window): `SDL_VIDEODRIVER=dummy uv run formicae-ui --mock --frames 60`.

UI keys: `Space` pause, `N` single step, `+`/`-` speed, `P` pheromone overlay, mouse wheel zoom,
middle or right button drag to pan, `E` export `metrics.csv`.

**Troubleshooting.** `uv: command not found` after installing: open a new terminal. Build errors
about the compiler: install `build-essential` (or `clang`). To use Python 3.15 later, change
`.python-version` and `requires-python` once NumPy, pygame-ce and Matplotlib publish wheels for it
(spec D8), then run `uv sync`.

### Windows (PowerShell)

Install uv and Visual Studio Build Tools with the **Desktop development with C++** workload
(MSVC and a Windows SDK). CMake detects the installed compiler; `make` is not required.
The native Windows build also supports MSVC with C++20 (Visual Studio 2019 16.11 or newer).
`FORMICAE_NATIVE` is only available with GCC or Clang using `-march=native`.

Run these commands from the repository root:

```powershell
uv sync --locked
uv run formicae-ui --mock
# Use the C++ engine:
uv run formicae-ui

uv run pytest
uv run ruff check .

# Standalone C++ checks; Debug keeps assertions enabled.
uv run cmake -S . -B build -DFORMICAE_BUILD_PYTHON=OFF -DFORMICAE_BUILD_TESTS=ON -DCMAKE_BUILD_TYPE=Debug
uv run cmake --build build --config Debug --parallel
uv run ctest --test-dir build -C Debug --output-on-failure

$env:SDL_VIDEODRIVER = "dummy"
try {
    uv run formicae-ui --mock --frames 60
} finally {
    Remove-Item Env:SDL_VIDEODRIVER
}
```

The environment lives in `.venv/`; select `.venv\Scripts\python.exe` as your editor's Python
interpreter. Activation is optional when using `uv run`.

## Layout and owners (spec sections 9.1 and 12)

| Path                                                                                                                                   | Module                      | Owner           | Person   |
| -------------------------------------------------------------------------------------------------------------------------------------- | --------------------------- | --------------- | -------- |
| `engine/include/formicae/{types,config,rng,grid,engine}.hpp`, `engine/src/{engine,pheromones,grid,config}.cpp`                         | M1 Core engine              | P1              | Szymon   |
| `engine/include/formicae/{species,ant,ai}.hpp`, `engine/src/{ai,species}.cpp`                                                          | M2 AI                       | P2              | Kacper K |
| `engine/include/formicae/{colony,combat}.hpp`, `engine/src/{colony,combat,food}.cpp`                                                   | M2 Combat, colonies, food   | P3              | Kacper   |
| `engine/bindings/`, `CMakeLists.txt`, `pyproject.toml`, `python/formicae_ui/config.py`, `python/formicae_mock.py`, `engine/src/io.cpp` | M0 Integration              | P4              | Jacek    |
| `python/formicae_ui/mapgen/`, `python/formicae_ui/analytics/`                                                                          | M3 Map generator, analytics | P5              | Kuba     |
| `python/formicae_ui/ui/`                                                                                                               | M4 UI                       | P6 (panels: P4) | Maks     |

## Current implementation status

The project builds and the existing test suite passes. The core simulation is largely implemented:

- **M1 (P1):** grid layers, RNG, config structs, ant slot storage/free list + periodic compaction, tick pipeline (§3), pheromone diffusion (double-buffered, optional), per-channel decay with precomputed factors, hill beacon, runtime food/terrain/param controls, and metrics accumulation.
- **M2 AI (P2):** `ant_update` implements the priority/state logic of §5.3 and movement/deposits of §5.4 (candidate filtering, weighted move choice, move cost, pickup/delivery, trail fading, hazard/flee/fight transitions) and is covered by `ai_checks`.
- **M2 combat/colonies/food (P3):** `colony_update`, `on_colony_destroyed`, `find_target`, `resolve_attack`, `on_ant_death`, and dynamic `spawn_food_step` (§7.4) are implemented.
- **M0 (P4):** build/packaging, mock engine, config loader skeleton, and the pybind11 `Simulation` API with zero-copy read-only views. `save`/`load` and full validation/UI panels are still pending.
- **M3/M4 (P5, P6):** `generate_map` (§8.2) and `Analytics` (history, CSV, render) are implemented; the PyGame UI runs with camera, zoom/pan, renderer/HUD, time control, overlays, and hotkeys.

Search for `TODO(P4)` to find the remaining explicit implementation markers (currently limited to M0/UI integration work).

## Concrete plans per person

The plans below are the remaining work as of this repository state. They are written to be implementable without guessing product decisions: follow `SPECS.md` as the source of truth, keep module ownership boundaries, and add/adjust tests with every behavior change.

### Shared quality bar (everyone)

- **Natural behavior:** ants should not teleport, jitter in place without cause, ignore obstacles/hills, fight allies, carry impossible loads, or create invisible state. Trail following must look plausible (emerge from deposits/evaporation, not hard-coded paths), fleeing should retreat toward home/danger logic, and combat outcomes should be explainable by species stats.
- **Well-chosen parameters:** do not tune by eye only. For every parameter change in `configs/default.json` or scenario configs, record the seed(s), tick count, and observed metrics (population per species, births/deaths by cause, food delivered/remaining, colonies alive, combat deaths per window). Keep defaults stable and playable; move extreme setups into `configs/scenario_*.json`.
- **Reproducibility:** use fixed `--map-seed`/`--sim-seed` for checks. After P1 adds a state hash, prefer hash/metrics comparisons for regression tests.
- **Verification commands:** run relevant checks after changes: `uv run pytest`, `uv run ruff check .`, `make cpp-test`, and headless UI smoke `SDL_VIDEODRIVER=dummy uv run formicae-ui --mock --frames 60` (or real engine when relevant).

### P1 — Szymon (M1 Core engine)

Goal: make the engine observable, deterministic to verify, and safe for long runs.

1. **Determinism hash (high priority).**
   - Add a public, read-only state fingerprint API (e.g. `uint64_t Engine::state_hash() const` and `Simulation.state_hash()` binding; keep names consistent with existing style).
   - Hash stable simulation state that defines behavior: `tick_`, RNG internal state, live ant slots in deterministic order (or full slot state with a defined encoding), occupancy/hill/terrain/food/pheromone arrays as needed, colony records, and any counters that affect future behavior. Do **not** hash transient buffers unless they affect results.
   - Add a regression test: same config + same `MapData` + same seeds, run N ticks twice from fresh initialization/reset → identical hash and identical key metrics. Also test that a changed seed/param produces a different hash.
   - Files likely touched: `engine/include/formicae/engine.hpp`, `engine/src/engine.cpp` (or dedicated hash helper), `engine/bindings/module.cpp`, `tests/`.

2. **Profiling harness (ants/s).**
   - Provide a repeatable way to measure performance without the UI (small C++ executable target, benchmark mode in tests, or a documented script). Report ticks, wall time, ticks/s, live ants, grid size, diffusion on/off.
   - Use the spec targets as reference (not pass/fail grades): 10k ants / 512² ≥ 300 ticks/s; 100k ants / 1024² ≥ 30 ticks/s.
   - Keep profiling code out of the hot tick path unless behind an explicit flag.

3. **Metrics completeness audit.**
   - Verify `metrics()` matches §9.3 exactly: per-species `population`, `births`, `kills`, `deaths_combat`, `deaths_hazard`, `deaths_age`, `deaths_orphan`, `colonies_alive`; global `tick`, `food_total_volume`, `food_total_energy`.
   - Confirm increments happen at the right moments: births on successful spawn, population on live/dead transitions, deaths/kills in death handling, `colonies_alive` on placement/destruction. Coordinate with P2/P3 where events originate; prefer a single authoritative update point per event.
   - Add tests that run a short scenario and assert metric invariants (e.g., population changes match births/deaths accounting over the sampled window where feasible; no negative counts).

4. **Long-run safety and memory checks.**
   - Run long smoke tests (e.g., 10k–100k ticks depending on cost) and confirm no unbounded growth in ant storage, pending-death queues, diffusion buffers, or history outside Analytics’ intended behavior.
   - Keep `compact_ant_array()` behavior correct: occupancy must remain valid after compaction; moved-slot references in grid must be updated (already present — add/keep a regression check).
   - Avoid allocations in the tick path; use existing buffers/vectors with reserved capacity.

5. **Stretch (only if scheduled): heatmaps.**
   - Implement `traffic`/`combat_map` counters in engine/grid/config only when `enable_heatmaps` is set. Expose `traffic()` and `combat_map()` through bindings and mock with identical shapes/dtypes/errors. Coordinate with P4 on binding API and with P6/P5 on visualization.

### P2 — (M2 AI, movement and state machine)

Goal: keep ant behavior natural, stable, and measurable; improve path choice with a pheromone gradient while preserving spec-compatible behavior.

1. **Behavior correctness and naturalness pass.**
   - Exercise `ant_update`/`move_ant` against §5.3–§5.4 in integrated runs and targeted tests. Check: no moves into impassable/occupied/enemy-hill cells, `last_dir`/reverse handling avoids jitter, dead-end backtracking works, FLEEING deposits DANGER and follows HOME, THORNS damage/death is applied, pickup chooses best adjacent/own food source, delivery only on friendly hill footprint, carried food/energy is conserved.
   - Confirm combat integration with P3: `find_target`/`resolve_attack` are called only when state rules allow; `defend_while_carrying` is respected; fleeing ants do not attack.
   - Confirm orphan behavior: ants of species with no live colonies take `orphan_loss * max_health` per tick as currently implemented and die with `DeathCause::Orphan` when health reaches zero.

2. **Pheromone-gradient pathfinding enhancement (requested).**
   - Current move choice samples among valid neighbors with `w = (ε + τ)^α * h * g`. Enhance it so ants are biased by the **local gradient** of the followed channel, not only by absolute neighbor values.
   - Implement in `move_ant` (`engine/src/ai.cpp`) with clear, cheap math. A practical formula: for each candidate neighbor `n`, compute
     - `tau_n = ε + pheromone_followed(species, channel, n)` (as now),
     - `tau_here = ε + pheromone_followed(species, channel, current_cell)`,
     - `grad = clamp(1 + beta_grad * (tau_n - tau_here) / max(tau_here, eps_grad), grad_min, grad_max)`,
     - `w_n = (tau_n)^α * h * g * grad`.
   - Keep `random_move_prob` unchanged as the exploration mechanism. Clamp the gradient factor so it cannot create negative/NaN weights or dominate so strongly that ants never explore.
   - Add configuration for the enhancement so it can be tuned/disabled without code edits: either new runtime params exposed through `set_param` (coordinate with P4 bindings/config validation) or species/config fields if product scope allows. If adding params, document names/ranges/defaults and preserve current behavior at default values.
   - Validate naturalness: ants should climb trails toward sources more reliably, still escape loops via randomness, and not form unrealistic single-file oscillations. Test on empty ground (near-random with forward bias), strong straight trail, forked trail, and trail disrupted by evaporation.

3. **Species tuning and trail-quality measurement.**
   - Tune `configs/default.json` species values for distinct, understandable roles (Swarmer/Tank/Nomad) and for visible interaction (foraging, occasional fights, survivable but not stagnant populations). Use scenario configs for aggressive/siege cases rather than making defaults chaotic.
   - Define and record a trail-quality metric during manual/automated runs, e.g. fraction of successful deliveries where the returning ant spent significant time on non-negligible HOME trail, or compare delivery rate with/without pheromone influence in controlled seeds. Store the method and sample numbers in commit/PR notes or a short note in `docs/` only if the team wants it; do not invent extra process files.
   - When changing parameters, include before/after metrics for the same seeds and explain the intended behavioral effect.

4. **Stretch (castes).**
   - If castes are enabled, verify spawn ratio/cost multipliers, resolved stats lookup, and that default ratio `[1,0,0,0]` remains behaviorally equivalent to single-caste runs. Any caste-specific behavior must still obey §5.3/§5.4.

### P3 — Kacper (M2 Combat, colonies, food)

Goal: make fights, economy, and colony lifecycle readable and balanced.

1. **Combat and lifecycle verification.**
   - Validate `find_target`/`resolve_attack`/`on_ant_death`/`on_colony_destroyed` against §6–§7 in end-to-end runs. Check deterministic tie behavior, damage floor, armor interaction, DANGER deposits (hit/death/hazard), carried-food drop and density merge, kill credit, colony HP/hill footprint clearing, loot conversion (`stored_energy / loot_density`) and volume-weighted merges.
   - Ensure dynamic food spawning (`spawn_food_step`) respects interval/probability, passable non-hill center selection, cluster radius/volume/density ranges, and global `max_food_cells` cap.

2. **Balance and “ants are fighting” visibility.**
   - Produce scenario configs (if not already present) that make outcomes obvious:
     - `configs/scenario_rivalry.json`: nearby hostile colonies/species, moderate food pressure, visible combat deaths and colony damage.
     - `configs/scenario_siege.json`: stronger defender vs more numerous attackers or asymmetric placement.
     - `configs/scenario_peaceful.json` (optional): low hostility/contact to validate foraging/economy independently.
   - Choose parameters so fights occur naturally from encounters, not from pathological overlap. Report the seeds and expected signals (non-zero `deaths_combat`, changing colony health/population, DANGER visible in overlay).

3. **Economy tuning.**
   - Check population stability over long runs (e.g., 20k ticks) for default and scenario configs. Avoid instant explosion/collapse unless a scenario explicitly demonstrates it.
   - Coordinate with P2 on speed/carry/cost/pheromone values and with P1 on metric correctness.

### P4 — Jacek (M0 Integration)

Goal: close the remaining integration gaps and make the simulation inspectable/debuggable.

1. **Config validation (finish).**
   - `python/formicae_ui/config.py` already rejects unknown keys/ranges; complete equivalent validation in C++ config parsing/binding path as needed so bad configs fail consistently (`engine/src/config.cpp`, `engine/bindings/module.cpp` `config_from_dict`).
   - Every `ConfigError`/`ValueError` should name the bad key/path and expected range/shape.
   - Add Python and/or C++ tests for unknown keys, missing required sections, out-of-range values, hostility matrix shape, and pheromone decay length.

2. **Save/load (priority P2).**
   - Implement binary save/load in `engine/src/io.cpp` and wire `Simulation.save()`/`load()` in `engine/bindings/module.cpp`. The format must include a clear header/version (spec mentions `ANTS` + format version) and restore all state required to continue identically: config/map-derived state as needed, tick, RNG state, ants (including dead-slot layout rules you choose, but deterministically), colonies, grid layers, metrics/counters, and runtime params.
   - Invalidate snapshot views on load as on step/reset. Add round-trip tests: save at tick T, load, step N → same hash/metrics as uninterrupted run to T+N.

3. **Inspector and control panels.**
   - Implement `InspectorPanel` in `python/formicae_ui/ui/panels.py`: render `sim.cell_info(x,y)` clearly (terrain, food volume/density, pheromones per species/channel as selected/available, ant summary, colony summary). Handle `None` fields.
   - Implement `ControlPanel`: sliders/controls for `TUNABLE_PARAMS` (`decay_scale`, `diffusion`, `food_spawn_prob`, `food_spawn_interval`) calling `sim.set_param`; show current values and clamp to ranges. If P2 adds gradient params and P4 exposes them, include them with explicit labels/defaults.
   - Wire selection and panel rendering in `python/formicae_ui/ui/app.py` (replace `TODO(P4)` hooks). `S` save snapshot: use a safe default path or prompt pattern consistent with the app; do not overwrite silently in surprising locations.

4. **Tests and CI hardening.**
   - Extend `test_config.py`, `test_mock_api.py`, and real-module tests to cover new behavior (save/load, state hash binding if added by P1, inspector-safe data access where practical). Add invariant checks where cheap: occupancy points to live ants or `NO_ANT`, pheromone values remain clamped by engine rules, no dead ants rendered as alive.

### P5 — (M3 Map generator, M4 analytics)

Goal: make generated worlds fair/playable and metrics easy to interpret.

1. **Map generator validation.**
   - Review `generate_map` against §8.2–§8.3 with fixed seeds. Confirm: border ROCK, passability/connectivity constraints, hill spacing/margins, corridor/path behavior, food cluster placement/caps, and `MapData` dtypes/shapes/C-contiguity.
   - Ensure colony placement supports the default 3-species setup and scenario configs. If map params are exposed by CLI/config, document them and keep determinism (NumPy/seed stream rules as in spec).

2. **Analytics quality.**
   - Verify CSV columns and graph content against §10: population, stored energy, combat deaths per 100 ticks (rolling), total food remaining/energy as implemented. Make labels/colors readable and handle empty histories.
   - Add or adjust tests in `tests/test_analytics.py` for rendering/export behavior when data is present.

3. **Demo support.**
   - Provide a small set of known-good seeds and commands for demos (mock and real engine). Coordinate with P3 scenario configs so map+species+params produce intended behavior.

### P6 — (M4 UI)

Goal: make the simulation smooth, legible, and demo-ready.

1. **Performance and rendering correctness.**
   - Test real-engine runs at target sizes (especially ~10k ants). Keep rendering viewport-culled; avoid per-cell Python work over the whole map each frame. Profile frame time separately from simulation `step()` budget.
   - Keep HUD/TPS/sim budget indicators accurate.

2. **UI integration and polish.**
   - Complete wiring for Tab/analytics panel behavior, pheromone/species selection clarity, and any save/cell-selection hooks added by P4. Ensure overlays do not hide critical state needed for debugging (colonies, ants, food).
   - Stretch: caste shade variations by species; heatmap overlays only after engine/binding support exists.

3. **Natural-behavior visibility.**
   - The UI should make it easy to judge behavior: distinguish searching/returning/fighting/fleeing where practical (color/marker/legend), show colony health/energy in sidebar/panels, and make combat/DANGER visible when relevant.
