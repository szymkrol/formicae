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
make cpp-test                 # plain CMake build of the C++ engine + engine_smoke
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

## Layout and owners (spec sections 9.1 and 12)

| Path | Module | Owner | Person |
|---|---|---|---|
| `engine/include/formicae/{types,config,rng,grid,engine}.hpp`, `engine/src/{engine,pheromones,grid,config}.cpp` | M1 Core engine | P1 | (WRITE HERE) |
| `engine/include/formicae/{species,ant,ai}.hpp`, `engine/src/{ai,species}.cpp` | M2 AI | P2 | (WRITE HERE) |
| `engine/include/formicae/{colony,combat}.hpp`, `engine/src/{colony,combat,food}.cpp` | M2 Combat, colonies, food | P3 | (WRITE HERE) |
| `engine/bindings/`, `CMakeLists.txt`, `pyproject.toml`, `python/formicae_ui/config.py`, `python/formicae_mock.py`, `engine/src/io.cpp` | M0 Integration | P4 | (WRITE HERE) |
| `python/formicae_ui/mapgen/`, `python/formicae_ui/analytics/` | M3 Map generator, analytics | P5 | (WRITE HERE) |
| `python/formicae_ui/ui/` | M4 UI | P6 (panels: P4) | (WRITE HERE) |

## What exists and what is a TODO

Everything compiles and `pytest` passes. Implemented: types and enums, RNG (PCG32), grid layers,
config defaults and validation skeleton, resolved species/caste table, ant slot storage, the tick
pipeline (spec section 3), baseline pheromone decay and hill beacon, food add/spawn/terrain/param
controls, the whole pybind11 API with zero-copy read-only views, the mock engine, TimeControl,
Camera, CSV export, and a basic renderer + HUD so the UI already runs. Search the code for `TODO(P1)` ... `TODO(P6)` to find each person's work:

| Dev | First tasks |
|---|---|
| P1 | diffusion, per-channel factor planes, slot compaction, metrics food totals, determinism hash |
| P2 | `ant_update` (priority table 5.3, movement 5.4) |
| P3 | `colony_update`, `on_colony_destroyed`, `find_target`, `resolve_attack`, `on_ant_death`, `spawn_food_step` |
| P4 | full config validation, `save`/`load`, inspector and control panels, CI hardening |
| P5 | map generator steps 1-7, `Analytics.render` |
| P6 | speed and quality of `Renderer.render`, remaining hotkeys, sidebar layout, real ticks/s display |

## Small differences from the specification text

- The grid functions of spec 9.4 (`idx`, `passable`, `occupant`, `pher`, `deposit`, `neighbors4`) are
  methods of `Grid`; `Engine` offers `rng()`, `spawn_ant()`, `kill_ant()`, `add_food()`.
- Combat functions live in `engine/src/combat.cpp` (listed under colonies in the spec).
- `CMakeLists.txt` installs `formicae_mock.py` next to the compiled module.
- `generate_map` returns a flat placeholder map until P5 implements spec section 8.2.
