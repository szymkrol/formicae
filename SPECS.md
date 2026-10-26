# Formicae ex machina — Technical Specification

*v1.0 · 10 Oct 2026 · 6 developers · 14 weeks · Linux, C++20, Python 3.15*

## 1. Introduction

This project is a real-time ant colony simulator. Several species of ants forage for food, fight each other and rebuild their colonies on a procedurally generated map, coordinating only through pheromone trails. A C++20 engine runs the simulation; a Python 3 front end generates maps, draws the world and plots live statistics. Six third-year students build it in 14 weeks, on Linux.

The specification covers these aspects:

- **World (§2):** a bounded 2D grid with 4-directional movement, seven terrain types and food deposits.
- **Time (§3):** fixed-step ticks with a defined update order; runs are reproducible from seeds.
- **Pheromones (§4):** three capped, evaporating channels per species: home, food and danger.
- **Ants (§5):** species with their own stats, a state machine (search, return, fight, flee) and purely pheromone-driven movement.
- **Combat and colonies (§6–7):** hostile species fight; colonies turn energy into new ants, can be destroyed and looted; there is no win condition.
- **Map generation (§8):** a seeded Python generator for terrain, colonies and food.
- **Modules and interfaces (§9):** the four modules and who owns them, and the exact contracts between them.
- **Front end (§10–11):** PyGame at 60 FPS with zoom, pan, cell inspection and speed control; live Matplotlib graphs; CSV export; JSON configuration.
- **Delivery (§12–15):** repository layout, build and conventions, team split, 14-week plan, acceptance criteria and risks.

**Must:** bounded grid world; terrain; seeded procedural maps; many species and colonies; 3 pheromone channels per species; ant state machines; combat; hazards; colony destruction with loot; live PyGame UI (zoom, pan, inspect, speed control); live analytics; CSV export; JSON configuration. **Should:** save/load, optional diffusion, mock engine for parallel work, invariant tests. **Stretch:** active castes, heatmaps, friendly swap rule, non-ant fauna.

## 2. World model

Grid W×H (default 512×512, supported 64–2048 per side). Index `i = y*W + x`, origin top-left. Bounded: out-of-range is impassable; the generator also draws a ROCK border.

**Cell layers** (flat, row-major):

| Layer | dtype | Shape |
| --- | --- | --- |
| `terrain` | uint8 | \[H,W\] |
| `evap_mod`, `move_cost` (derived from terrain) | float32 | \[H,W\] |
| `food_volume`, `food_density` | float32 | \[H,W\] |
| `occupancy` (ant slot index or -1) | int32 | \[H,W\] |
| `hill_id` (colony index or -1) | int16 | \[H,W\] |
| `pher` | float32 | \[S,3,H,W\] (species, channel HOME/FOOD/DANGER) |

Max species `S_MAX = 8`; arrays sized by the number of species in the config.

**Terrain table** (configurable; defaults):

| ID | Name | move\_cost | evap\_mod | Passable | Hazard dmg/tick |
| --- | --- | --- | --- | --- | --- |
| 0 | GRASS | 1.0 | 1.0 | yes | 0 |
| 1 | SAND | 1.5 | 2.0 | yes | 0 |
| 2 | MUD | 2.0 | 0.5 | yes | 0 |
| 3 | PATH | 0.7 | 1.2 | yes | 0 |
| 4 | ROCK | – | – | no | – |
| 5 | WATER | – | – | no | – |
| 6 | THORNS | 1.5 | 1.0 | yes | 1.0 |

**Hills.** A colony footprint is a square of `(2r+1)²` cells, default `r=2` (25 cells), marked in `hill_id`. Only ants of the colony's species may enter; for others it is an obstacle that can be attacked from an adjacent cell. A large footprint is deliberate: with one ant per cell, a 1-cell hill would throttle deliveries.

## 3. Time and update order

Fixed timestep: the engine knows nothing about wall-clock time. One `step()`:

1. `spawn_food()` (§7.3)
2. `colony_update()` for every live colony (spawn ants, §7.2)
3. `ant_update()` for every live ant, **sequentially and in place**; the iteration direction alternates every tick (forward/backward) to avoid bias. Sequential updates make the one-ant-per-cell rule trivial: occupancy is always current, no conflict resolution needed.
4. `cleanup_dead()`: free slots, drop carried food, alarm deposits
5. `pheromone_update()`: optional diffusion, then decay
6. metrics, `tick += 1`

**Determinism:** single thread, one RNG (PCG32 or xoshiro128++) seeded by `sim_seed`. Same config + map + seeds ⇒ identical run. Map seed and sim seed are independent.

**Ant storage:** one slot array (`std::vector<Ant>`) plus free list; `state == DEAD (255)` marks free slots; compaction + occupancy rebuild every 1000 ticks. No allocation inside `step()` (reserve at init; hard cap `max_ants_total`, default 150 000).

**Performance targets (not graded, for planning):** 10k ants / 512² ≥ 300 ticks/s; 100k ants / 1024² ≥ 30 ticks/s.

## 4. Pheromones

Channels per species: `HOME=0`, `FOOD=1`, `DANGER=2`. Values in `[0, 1]` (cap `P_MAX = 1`).

- **Deposit:** `p = min(P_MAX, p + a)`.
- **Decay (multiplicative):** `p *= (1 − ρ_c · decay_scale · evap_mod[cell])`, clamp factor to ≥ 0; if `p < 0.001` set `p = 0`. Precompute a per-channel factor plane when `decay_scale` changes; the loop becomes `p[i] *= f[i]`.
- Defaults: `ρ_HOME = 0.003` (half-life ≈ 230 ticks), `ρ_FOOD = 0.008` (≈ 87), `ρ_DANGER = 0.03` (≈ 23).
- **Diffusion (optional, default off):** `p' = p + D·(mean4(p) − p)`, `D ∈ [0, 0.2]`, double-buffered. Not needed for correctness; widens trails. Cost ≈ 5× decay, so it is skipped when `D = 0`.
- **Hill beacon:** each tick, HOME of the owning species is set to `P_MAX` on all its footprint cells.

## 5. Ants

### 5.1 Ant struct (40 bytes, POD)

One ant is a 40-byte plain-old-data record, so 100 000 ants fit in 4 MB. The same layout is exposed to NumPy as a structured dtype (`static_assert(sizeof(Ant) == 40)`).

| Offset | Bytes | Field | Type | Meaning |
| --- | --- | --- | --- | --- |
| 0 | 4 | `id` | u32 | Unique id, never reused within a run |
| 4 | 4 | `age` | u32 | Ticks alive; the ant dies at the species `max_age` |
| 8 | 2 | `x` | i16 | Column of the ant's cell |
| 10 | 2 | `y` | i16 | Row of the ant's cell |
| 12 | 2 | `colony` | u16 | Index of the colony that spawned it |
| 14 | 2 | `trail_age` | u16 | Steps since last visit home (searching) or last pickup (returning); scales deposits |
| 16 | 1 | `species` | u8 | Index into the species table |
| 17 | 1 | `caste` | u8 | Index into the caste table (0 = STANDARD in v1) |
| 18 | 1 | `state` | u8 | 0 SEARCHING, 1 RETURNING, 2 FIGHTING, 3 FLEEING, 255 DEAD |
| 19 | 1 | `last_dir` | i8 | Last move: 0 N, 1 E, 2 S, 3 W; −1 = none |
| 20 | 1 | `timer` | u8 | Remaining flee ticks |
| 21 | 3 | `pad` | u8\[3\] | Alignment padding |
| 24 | 4 | `health` | f32 | Current health (maximum is in the species table) |
| 28 | 4 | `carried_volume` | f32 | Units of food being carried |
| 32 | 4 | `carried_density` | f32 | Energy per unit of the carried food |
| 36 | 4 | `move_acc` | f32 | Accumulated movement points (see §5.4) |

### 5.2 Species table

Each species is one entry in the species table. Stats are not copied into ants; an ant reads them through its `species` index. Every value below is a starting point to be tuned in weeks 9–10.

| Group | Parameter | Meaning | Swarmer | Tank | Nomad |
| --- | --- | --- | --- | --- | --- |
| **Role** |  |  | Fast, cheap forager | Slow, armored defender | Wide-ranging explorer |
| **Survival** | `max_health` | Hit points | 10 | 60 | 20 |
|  | `max_age` | Lifespan in ticks | 4000 | 8000 | 5000 |
|  | `flee_threshold` | Health fraction below which it flees (0 = never) | 0.3 | 0 | 0.5 |
|  | `flee_ticks` | Ticks spent fleeing | 15 | 15 | 15 |
| **Movement** | `speed` | Cells per tick, max 1 | 1.0 | 0.5 | 0.9 |
|  | `random_move_prob` | Chance of a uniformly random step | 0.10 | 0.05 | 0.20 |
|  | `alpha` | Sensitivity to pheromone strength | 2.0 | 2.0 | 1.2 |
|  | `forward_bonus` | Weight for keeping the current heading | 1.5 | 1.5 | 1.5 |
| **Combat** | `damage` | Base damage per hit | 2 | 6 | 3 |
|  | `armor` | Damage subtracted from incoming hits | 0 | 2 | 0.5 |
|  | `accuracy` | Hit chance (0–1) | 0.7 | 0.6 | 0.7 |
|  | `defend_while_carrying` | Fights back while carrying food | no | yes | no |
| **Economy** | `cost` | Energy needed to spawn one ant | 60 | 400 | 200 |
|  | `carry_capacity` | Food volume per trip | 2 | 6 | 4 |
| **Pheromones** | `a_home` | HOME deposit strength | 0.04 | 0.04 | 0.04 |
|  | `a_food` | FOOD deposit strength | 0.12 | 0.12 | 0.12 |
|  | `trail_len_home` | Steps over which HOME deposits fade out | 400 | 400 | 400 |
|  | `trail_len_food` | Steps over which FOOD deposits fade out | 400 | 400 | 400 |
|  | `danger_k` | Reaction to DANGER: positive avoids, negative is attracted | 0.8 | −0.8 | 2.0 |
|  | `danger_k_home` | Same, when near home (HOME ≥ 0.9) | −0.5 | −1.0 | 1.0 |
| **Colony** | `orphan_loss` | Health fraction lost per tick with no live colony | 0.01 | 0.01 | 0.01 |

Global constants shared by all species: `ε = 0.05` (floor added to pheromone values in movement weights) and `D_REF = 50` (food density that gives a full-strength FOOD trail).

**Castes (stretch goal, data model ready from day one).** A caste is a role variant inside one species: it rescales that species' stats and tweaks a few behavior parameters. v1 ships only `STANDARD` (index 0) with all multipliers 1, so enabling castes later needs no format change.

| `CasteDef` field | Type | Effect |
| --- | --- | --- |
| `name` | string | Label shown in the UI and CSV |
| `max_health_mul`, `damage_mul`, `armor_mul` | f32, default 1 | Multiply the species value |
| `speed_mul` | f32, default 1 | Multiplies `speed`; result clamped to ≤ 1 |
| `carry_mul` | f32, default 1 | Multiplies `carry_capacity`; 0 = never picks up food |
| `cost_mul` | f32, default 1 | Multiplies the spawn `cost` |
| `random_move_prob_add` | f32, default 0 | Added to `random_move_prob`; result clamped to 0–1 |
| `a_home_mul`, `a_food_mul` | f32, default 1 | Multiply pheromone deposit strength |
| `danger_k_add` | f32, default 0 | Added to `danger_k` and `danger_k_home` |
| `defend_while_carrying` | yes / no / inherit | Overrides the species flag; default inherit |

**Rules**

- At init the engine precomputes a resolved table indexed `[species][caste]` (species value combined with the caste fields above), so the tick loop does one lookup and no arithmetic per ant. `Ant.caste` is the index into it.
- Up to 4 castes per species. The state machine, movement and combat rules are identical for all castes; only parameters differ.
- Each colony has `caste_ratio[]` (weights, default `[1, 0, 0, 0]`). On spawn the caste is drawn from these weights with the engine RNG; the ant's cost is `cost × cost_mul`.
- Metrics gain population per species and caste; the UI draws a caste as a brighter or darker shade of its species color.
- Acceptance: with the default ratio the run is bit-identical to a build without castes.

**Planned castes** (starting values, to be tuned):

| Caste | Role | Changes |
| --- | --- | --- |
| EXPLORER | Finds new food | `random_move_prob_add` +0.15, `a_home_mul` 0.5, `a_food_mul` 0.5, `max_health_mul` 0.8, `carry_mul` 0.5, `cost_mul` 0.8 |
| GATHERER | Hauls food | `carry_mul` 1.5, `speed_mul` 0.9, `damage_mul` 0.5, `defend_while_carrying` no |
| FIGHTER | Defends and raids; never forages | `carry_mul` 0 (it roams and is drawn to DANGER), `damage_mul` 1.5, `max_health_mul` 1.5, `danger_k_add` −1.0, `cost_mul` 1.5 |

### 5.3 State machine

States: `SEARCHING=0, RETURNING=1, FIGHTING=2, FLEEING=3, DEAD=255`. Rules are evaluated top-down every tick; the first match wins and the ant performs **one action** per tick (attack, or pick up/deliver, or move).

| Pri | Condition | Action → next state |
| --- | --- | --- |
| 1 | health ≤ 0, age ≥ max\_age, or orphan loss kills it | mark DEAD |
| 2 | on THORNS | take damage, deposit DANGER (0.3), continue below |
| 3 | enemy ant or enemy hill adjacent (4-neighborhood) and health/max < flee\_threshold | → FLEEING, `timer = flee_ticks` |
| 4 | enemy adjacent and (state ≠ RETURNING or defend\_while\_carrying) | attack (§6) → FIGHTING |
| 5 | FIGHTING with no enemy adjacent | → RETURNING if carrying else SEARCHING |
| 6 | FLEEING: move by the RETURNING rule ignoring danger weights; deposit DANGER 0.3 | `timer−−`; at 0 or on a friendly hill → SEARCHING/RETURNING |
| 7 | SEARCHING, carrying nothing, food in own or 4-adjacent cell | pick up → RETURNING, `trail_age=0`, `last_dir` reversed |
| 8 | RETURNING on a friendly hill footprint | deliver → SEARCHING, `last_dir` reversed |
| 9 | otherwise | move (§5.4) |

**Pickup:** choose the adjacent cell (or own) with largest `food_volume`; `amount = min(carry_capacity, food_volume)`; `carried_density = food_density[cell]`; when volume reaches 0, density is set to 0. **Delivery:** `colony.stored_energy += carried_volume × carried_density`.

### 5.4 Movement

Whenever the state table (§5.3) ends in "move", the ant goes through four steps in order: list the cells it may enter, choose one, check whether it can afford the step, then leave a pheromone mark. Ants have no vision or memory; the only information they use is the pheromone values of the four cells next to them.

| State | Follows channel | Deposits | Reacts to DANGER |
| --- | --- | --- | --- |
| SEARCHING | FOOD | HOME | yes (`danger_k`) |
| RETURNING | HOME | FOOD | yes (`danger_k`) |
| FLEEING | HOME | DANGER, 0.3 per step | no |
| FIGHTING | does not move | – | – |

**Step 1 — Candidate cells.** The ant looks at its 4 neighbors (N, E, S, W). A neighbor is a candidate only if it is inside the map, has passable terrain, holds no other ant, and is not part of another species' hill. The cell behind the ant (opposite of `last_dir`) is excluded, which stops ants from jittering back and forth. It becomes allowed again only when nothing else is available, so ants can leave dead ends and back out of a head-on jam. With no candidates the ant waits and keeps its accumulated movement points.

**Step 2 — Choose a cell.** With probability `random_move_prob` the ant picks a candidate uniformly; this keeps exploration alive and lets ants escape trail loops. Otherwise it draws a candidate at random with these weights:

```latex
w = (\varepsilon + \tau)^{\alpha} \cdot h \cdot g
```

| Term | Meaning |
| --- | --- |
| `τ` | Pheromone value (0–1) of the followed channel, for the ant's own species, in that cell |
| `ε` | Floor (0.05) so cells without pheromone still have a small chance |
| `α` | Species sensitivity: higher means the ant sticks to strong trails more strictly |
| `h` | `forward_bonus` (1.5) if the cell continues the current heading, otherwise 1 |
| `g` | `clamp(1 − k·d, 0.05, 3)`, where `d` is the DANGER value in the cell and `k` is `danger_k` (or `danger_k_home` when HOME at the ant's own cell is ≥ 0.9). Positive `k` makes the cell less attractive, negative `k` more |

Example, a searching Swarmer (`α = 2`) heading north; south is excluded as the way back.

| Situation | N (ahead) | E | W |
| --- | --- | --- | --- |
| FOOD values | 0 | 0.40 | 0 |
| Weights | 0.0025 × 1.5 = 0.00375 | 0.45² = 0.2025 | 0.0025 |
| Chance (non-random move) | 1.8% | 97.0% | 1.2% |
| With no pheromone at all | 42.9% | 28.6% | 28.6% |

A strong trail therefore dominates, while on bare ground the forward bonus gives gently curved, persistent walks. For danger: a Nomad (`k = 2`) next to a cell with `d = 0.4` multiplies that cell's weight by 0.2; a Tank (`k = −0.8`) with `d = 0.5` multiplies it by 1.4.

**Step 3 — Pay the movement cost.** Each tick the ant adds its `speed` to `move_acc` (capped at 2). It can enter the chosen cell only if `move_acc` ≥ the terrain's `move_cost`; the cost is then subtracted. An ant moves at most one cell per tick. Examples: a Tank (speed 0.5) on grass (cost 1.0) moves every second tick; a Swarmer (speed 1.0) in mud (cost 2.0) also moves every second tick; on a PATH (cost 0.7) a Swarmer moves every tick and the surplus 0.3 is kept.

**Step 4 — Deposit pheromone.** After moving (and at the moment of pickup) the ant adds pheromone to the cell it stands on, capped at 1.

| State | Channel | Amount | `trail_age` |
| --- | --- | --- | --- |
| SEARCHING | HOME | `a_home · max(0, 1 − trail_age / trail_len_home)` | Reset to 0 on a friendly hill, +1 per move |
| RETURNING | FOOD | `a_food · dn · max(0, 1 − trail_age / trail_len_food)`, with `dn = min(1, carried_density / D_REF)` | Reset to 0 at pickup, +1 per move |

Because deposits fade with `trail_age`, a trail is strongest near its source and weakest far away, so following it uphill always leads toward the nest (HOME) or the food (FOOD). Richer food (higher density) gives a stronger FOOD trail, which pulls more ants to the better source.

## 6. Combat, hazards, death

- **Hostility:** `hostile[S][S]` boolean matrix, default: different species = hostile; same species = allies.
- **Attack:** target = adjacent enemy ant with lowest health (ties random), else an adjacent enemy hill footprint. Roll `r ∈ [0,1)`; hit if `r < accuracy`; damage = `max(0.5, damage · (0.75 + 0.5·rng) − target.armor)`. Applied immediately (sequential model).
- **Hit event:** deposit `0.4` DANGER at the target's cell into both involved species' DANGER layers.
- **Death:** drop carried load onto the cell (`volume` added, density volume-weighted), deposit DANGER 0.5 for the victim's species, free the slot; counters by cause (combat/hazard/age/orphan) and kill credit to the attacker's species.
- **Hazard:** THORNS damages standing ants every tick (see §5.3).

## 7. Colonies, economy, food

### 7.1 Colony

A colony is the home base of one species: it stores energy, produces ants and can be destroyed. Colonies live in a fixed array and are never removed, so a colony index stays valid for the whole run, even after the colony dies.

| Field | Type | Meaning | Default | In `colonies()` |
| --- | --- | --- | --- | --- |
| `x`, `y` | i16 | Center cell of the footprint | from the map | yes |
| `species` | u8 | Species this colony belongs to | from the map | yes |
| `alive` | bool | False once destroyed (§7.3) | true | yes |
| `health` | f32 | Hit points; at 0 or below the colony is destroyed | 1000 | yes |
| `max_health` | f32 | Maximum hit points | 1000 | yes |
| `stored_energy` | f64 | Energy delivered by ants and not yet spent on spawning | 600 at start | yes |
| `population` | u32 | Live ants that were spawned by this colony | 0 | yes |
| `spawn_cooldown` | u8 | Ticks until the next ant may be spawned | 0 | no |
| `caste_ratio[4]` | f32 | Spawn weights per caste (§5.2) | `[1, 0, 0, 0]` | no |

Footprint size comes from the `hill_radius` setting (default 2, a 5×5 square); it is shared by all colonies and not stored per colony.

### 7.2 Spawning

Each tick, if `alive`, cooldown 0, `stored_energy ≥ cost` and `population < max_population (30 000)`: spawn one ant in a free footprint cell (random start offset, first free), pay `cost`, set cooldown 2. No free cell ⇒ postpone. Spawn type = species default caste (stretch: weighted by `caste_ratio`).

### 7.3 Destruction and loot

Enemy hits reduce `health`; at ≤ 0 the colony is destroyed: footprint cleared (`hill_id = −1`), and `stored_energy` becomes food on the center cell (`volume += E/25`, density 25; volume-weighted merge). Looters must transport it home. Ants of a species with no live colony are **orphans**: they lose `orphan_loss` (1% of max health) per tick. There is no win condition.

### 7.4 Food

- Cell holds one food type: `volume` (units) and `density` (energy per unit, typically 10–50).
- Dynamic spawn: every `spawn_interval` ticks (default 50), with probability `spawn_prob` (0.5), place a cluster (radius 1–3, cells in a disc) at a random passable non-hill cell; volume per cell uniform \[50, 200\], density uniform \[10, 50\]; global cap `max_food_cells = 2000` (skip when reached).
- Manual: `sim.spawn_food(x, y, radius, volume, density)`.

## 8. Map generation (Python)

The generator is a pure Python function, `generate_map(seed, width, height, n_colonies, species_ids, params) -> MapData`. It needs only NumPy. The same inputs always produce the same map (pin the NumPy version for bit-exact results across machines). Expected run time: under 1 s at 512×512, under 10 s at 2048×2048.

### 8.1 Parameters

| Parameter | Default | Meaning |
| --- | --- | --- |
| `seed` | required | Master seed; split into 5 independent random streams (elevation, moisture, thorns, placement and paths, food) with `numpy.random.SeedSequence(seed).spawn(5)`, so changing a food parameter never changes the terrain |
| `width`, `height` | 512 | Grid size (64–2048) |
| `n_colonies` | 3 | Number of hills; colony `i` gets species `species_ids[i % len(species_ids)]` |
| `noise_octaves`, `noise_scale` | 5, 64 | Octaves, and the feature size in cells of the lowest octave |
| `water_level`, `rock_level` | 0.28, 0.78 | Elevation below / above which terrain is WATER / ROCK |
| `sand_moisture`, `mud_moisture` | 0.30, 0.70 | Moisture below / above which land is SAND / MUD |
| `thorn_threshold` | 0.85 | Thorn-field value above which land becomes THORNS |
| `hill_radius` | 2 | Footprint half-size (as §2) |
| `min_hill_distance` | 0.2 · min(W, H) | Minimum distance between hill centers, in cells |
| `food_density_of_clusters` | 1 per 20 000 cells | Number of food clusters is `max(2 · n_colonies, round(W · H / 20 000))` |
| `food_min_hill_distance` | 15 | Minimum distance of a food cluster center from any hill center, in cells |
| `max_retries` | 100 | Placement attempts per hill or cluster |

### 8.2 Algorithm

1. **Noise fields.** Build three independent fields `elevation`, `moisture` and `thorns`, each in \[0, 1\]. Fractal value noise: for octave `o` (0 to `noise_octaves` − 1) draw a random grid with cell size `noise_scale / 2^o` (at least 2), upsample it to H×W with smoothstep bilinear interpolation (`3t² − 2t³`), weight it by `0.5^o`, sum the octaves, then rescale the sum to \[0, 1\] by min and max.
2. **Terrain classification.** For each cell, the first matching rule wins: outermost ring of cells → ROCK; elevation < `water_level` → WATER; elevation > `rock_level` → ROCK; thorns > `thorn_threshold` → THORNS; moisture < `sand_moisture` → SAND; moisture > `mud_moisture` → MUD; otherwise GRASS. If fewer than 50% of cells are passable, repeat from step 1 with `seed + 1` (up to 10 times); the seed actually used is returned as `effective_seed`.
3. **Hill placement.** For colony `i`, sample random cells until one satisfies: the whole footprint plus a 2-cell margin lies on passable cells that are not THORNS; the distance to every earlier hill center is at least `min_hill_distance`. After `max_retries` failures raise `MapGenError` naming the colony. Then set every footprint cell to GRASS.
4. **Connectivity.** Label the 4-connected components of passable cells (breadth-first flood fill; `scipy.ndimage.label` may be used if installed, but is not required). For every hill outside the component of hill 0, carve a 1-cell-wide L-shaped corridor (horizontal first, then vertical) from its center to the center of hill 0: every impassable or THORNS cell on it becomes GRASS. Re-label after each corridor.
5. **Paths.** For each pair of consecutive hills `i` and `i + 1`, walk from hill `i` toward hill `i + 1`: each step moves toward the target along the axis with the larger remaining distance with probability 0.7, otherwise in a random direction; steps into impassable cells or hill footprints are skipped. Every visited cell that is not a hill cell becomes PATH. Stop at the target footprint or after 4 × (Manhattan distance) steps.
6. **Food clusters.** For each cluster, sample a center among passable, non-THORNS, non-hill cells at least `food_min_hill_distance` from every hill center (up to `max_retries` attempts; a cluster that cannot be placed is skipped and counted in `stats`). Pick radius `r` uniformly from {1, 2, 3}. All passable, non-hill cells with `dx² + dy² ≤ r²` receive `food_volume` drawn uniformly from \[50, 200\] per cell. The density is the same in the whole cluster: `clamp(lerp(10, 50, d) · U(0.8, 1.2), 10, 50)`, where `d = min(1, distance to nearest hill / (0.4 · max(W, H)))`, so far food is richer than near food.
7. **Validation.** Assert before returning: the border is ROCK; every hill center and every food cell lies in one 4-connected component; no food on impassable or hill cells; array shapes and dtypes match the table below.

### 8.3 Output

| Field | Type | Meaning |
| --- | --- | --- |
| `width`, `height` | int | Grid size |
| `terrain` | uint8 \[H, W\] | Terrain ids (§2) |
| `food_volume` | float32 \[H, W\] | Food units per cell, 0 where none |
| `food_density` | float32 \[H, W\] | Energy per unit, 0 where no food |
| `colonies` | int32 \[K, 3\] | One row per hill: `x`, `y`, `species_id` |
| `effective_seed` | int | Seed that produced this map (step 2) |
| `stats` | dict | Passable fraction, number of hills and food clusters placed, clusters skipped, corridors carved |

## 9. Modules and interfaces

### 9.1 Modules

The project has four functional modules and one integration module. Each has one owner, a directory it alone edits, and fixed inputs and outputs, so the team can work in parallel.

| Module | Language | Responsibility | Directory / files | Needs | Owner |
| --- | --- | --- | --- | --- | --- |
| **M1 Core Engine** | C++ | Grid layers, tick pipeline (§3), RNG, ant slot storage, pheromone deposit/decay/diffusion, food spawning, metrics counters, save/load | `engine/include/formicae/{types,config,rng,grid,engine}.hpp`, `engine/src/{engine,pheromones,food,io}.cpp` | nothing | P1 |
| **M2 Entity & AI** | C++ | Species and caste tables, `Ant` struct, state machine, sensing, movement, deposits (§5); combat, hazards, colony lifecycle, death handling (§6–7) | `engine/include/formicae/{species,ant,colony,ai,combat}.hpp`, `engine/src/{ai,colony}.cpp` | M1 grid API (§9.4) | P2 (AI), P3 (combat, colonies) |
| **M3 Environment Generator** | Python | `generate_map` (§8) | `python/formicae_ui/mapgen/` | nothing | P5 |
| **M4 Frontend & Analytics** | Python | PyGame rendering, input, inspector, time control, Matplotlib graphs, CSV export (§10) | `python/formicae_ui/{ui,analytics}/` | module `formicae` or its mock; M3 | P6 (UI), P5 (analytics) |
| **M0 Integration** | C++ / Python / CMake | pybind11 bindings, build and packaging, config schema and loader, mock engine, CI | `engine/bindings/module.cpp`, `CMakeLists.txt`, `pyproject.toml`, `python/formicae_ui/config.py`, `python/formicae_mock.py` | M1, M2 | P4 |

Data flow:

```text
M3 generate_map --MapData--> [formicae.Simulation = M0 bindings over M1 + M2] --snapshots--> M4 UI + analytics
                                         ^------------------- controls (set_param, spawn_food, ...) ---|
config JSON --> M0 loader --> engine structs (species, terrain, params);  M3 and M4 read their own sections
```

### 9.2 Interface overview

| ID | From → To | Mechanism | Content | When |
| --- | --- | --- | --- | --- |
| I1 | M3 → M1 | `Simulation.initialize(map_data)` | `MapData` (§8.3), copied into engine memory | once per run or reset |
| I2 | M1 ↔ M2 | header-only inline C++ functions (§9.4) | grid access, RNG; entry points the engine calls | every tick |
| I3 | M1 → M4 | `step(n)` and snapshot getters (§9.3) | read-only NumPy views and a metrics dict | every frame |
| I4 | M4 → M1 | setter methods (§9.3) | runtime parameters, food spawn, terrain edit | on user input |
| I5 | file → M0, M3, M4 | `load_config(path) -> dict` | the JSON configuration (§11) | at start |
| I6 | M4 internal | `Analytics.record / render / export_csv` (§9.5) | metrics samples, plots, CSV | every 10 ticks / 1 s / on demand |

### 9.3 Python API of module `formicae` (I1, I3, I4)

The module exposes `formicae.__version__` and `formicae.API_VERSION = 1`. All calls must come from one thread. While `step` runs, it releases the GIL so the UI thread may redraw, but any other call on the same `Simulation` then raises `RuntimeError("busy")`. Bad arguments raise `ValueError`; calling in the wrong state raises `RuntimeError`; `step` itself never raises.

| Method | Behavior |
| --- | --- |
| `Simulation(config: dict)` | Validates the config; `ValueError` lists every bad key. Creates an empty simulation (not yet runnable). |
| `initialize(map_data: dict) -> None` | Requires all `MapData` keys with the exact dtypes and C-contiguous layout (no implicit conversion), copies them, sets `tick = 0`, spawns no ants. `step` before this raises `RuntimeError`. |
| `step(n: int = 1) -> int` | Runs `1 ≤ n ≤ 10 000` ticks and returns the new tick number. Invalidates all views. |
| `reset() -> None` | Restores the stored config, initial map and seeds; `tick = 0`. Invalidates all views. |
| `tick` (read-only property) | Current tick number. |
| `save(path) -> None` / `load(path) -> None` | Binary snapshot with header `ANTS` + format version; `load` restores everything including RNG state. (Priority P2.) |
| `spawn_food(x, y, radius, volume, density) -> int` | `0 ≤ radius ≤ 10`, `volume > 0`, `0 < density ≤ 100`. Fills the disc as in §7.4, skipping impassable and hill cells; merges with existing food volume-weighted; returns the number of cells changed. |
| `set_terrain(x, y, terrain_id) -> None` | Changes one cell and its derived `move_cost`/`evap_mod`. `ValueError` for unknown id, hill cells, or making an occupied cell impassable. |
| `set_param(name, value) -> None` | Runtime-tunable values only (table below); takes effect at the next tick. |
| `cell_info(x, y) -> dict` | Keys: `terrain`, `food_volume`, `food_density`, `pheromone` (float array \[S, 3\]), `ant` (dict of the ant's fields or `None`), `colony` (dict or `None`). |

Runtime parameters for `set_param`:

| Name | Range | Default |
| --- | --- | --- |
| `decay_scale` | 0–10 | 1.0 |
| `diffusion` | 0–0.2 | 0.0 |
| `food_spawn_prob` | 0–1 | 0.5 |
| `food_spawn_interval` | 1–10 000 ticks | 50 |

**Snapshot getters** return zero-copy, read-only NumPy views (`flags.writeable == False`) onto engine memory. A view is valid until the next `step`, `reset` or `load`; copy it with `np.array(view)` to keep it.

| Getter | Shape and dtype |
| --- | --- |
| `terrain()` | uint8 \[H, W\] |
| `food_volume()`, `food_density()` | float32 \[H, W\] |
| `pheromones()` | float32 \[S, 3, H, W\] (species, channel HOME/FOOD/DANGER) |
| `ants()` | structured array, one record per slot, layout of §5.1; skip records with `state == 255` |
| `colonies()` | structured array, 32 bytes per record (layout below) |
| `traffic()`, `combat_map()` | uint32 \[H, W\]; only when `enable_heatmaps` is set (stretch), otherwise `RuntimeError` |
| `metrics()` | dict, copied (layout below) |

Each `colonies()` record is 32 bytes:

| Offset | Bytes | Field | Type | Meaning |
| --- | --- | --- | --- | --- |
| 0 | 8 | `stored_energy` | f64 | Energy in the colony's store |
| 8 | 4 | `health` | f32 | Current hit points |
| 12 | 4 | `max_health` | f32 | Maximum hit points |
| 16 | 4 | `population` | u32 | Live ants of this colony |
| 20 | 2 | `x` | i16 | Center column |
| 22 | 2 | `y` | i16 | Center row |
| 24 | 1 | `species` | u8 | Species index |
| 25 | 1 | `alive` | u8 | 1 = alive, 0 = destroyed |
| 26 | 6 | padding | – | Unused, keeps the record at 32 bytes |

`metrics()` keys (S = number of species; counters are cumulative since tick 0):

| Key | Type | Meaning |
| --- | --- | --- |
| `tick` | int | Current tick |
| `population` | int64 \[S\] | Live ants per species |
| `births` | int64 \[S\] | Ants spawned |
| `kills` | int64 \[S\] | Ants killed by this species (credit to the attacker) |
| `deaths_combat`, `deaths_hazard`, `deaths_age`, `deaths_orphan` | int64 \[S\] | Deaths of this species by cause |
| `colonies_alive` | int64 \[S\] | Live colonies per species |
| `food_total_volume`, `food_total_energy` | float64 | Sum over the map (energy = volume × density) |

### 9.4 C++ contract between M1 and M2 (I2)

The hot path uses header-only inline functions: no virtual calls, no exceptions, no allocation inside a tick. M1 provides, in `grid.hpp` and `rng.hpp`:

```cpp
namespace formicae {
inline int  idx(int x, int y);                 // y * W + x
inline bool in_bounds(int x, int y);
inline bool passable(int i);                   // terrain passable (hazards count as passable)
inline int  occupant(int i);                   // ant slot index or -1
inline int  hill_at(int i);                    // colony index or -1
inline float move_cost(int i);
inline float pher(int species, int channel, int i);
inline void  deposit(int species, int channel, int i, float amount);   // capped at 1
inline Neighbors4 neighbors4(int i);           // N,E,S,W cell indices, -1 if outside
struct Rng { uint32_t next_u32(); float next_float(); int next_int(int n); };
}
```

M1 calls these entry points, implemented by M2:

| Function | Owner | Called | Task |
| --- | --- | --- | --- |
| `void ant_update(Engine&, int slot)` | P2 (attacks call P3's `resolve_attack`) | step 3, per live ant | Runs the state table (§5.3), movement, pickup, delivery, deposits |
| `void resolve_attack(Engine&, int attacker_slot, Target)` | P3 | from `ant_update` | Hit roll, damage, hit-event alarm (§6) |
| `void colony_update(Engine&, int colony)` | P3 | step 2, per live colony | Spawning (§7.2), regeneration none |
| `void on_ant_death(Engine&, int slot, DeathCause, int killer_species)` | P3 | step 4 | Drop load, alarm deposit, counters, free the slot |
| `void on_colony_destroyed(Engine&, int colony)` | P3 | when health ≤ 0 | Loot food, clear footprint, orphan handling (§7.3) |

M2 may read species and caste data only through `species_of(ant)` (the resolved table of §5.2) and may write grid layers only through the functions above. Any change to this list needs the owners of M1 and M2.

### 9.5 Python-internal contracts (I5, I6)

| Call | Module | Contract |
| --- | --- | --- |
| `load_config(path: str) -> dict` | M0 | Reads JSON, rejects unknown keys, checks ranges (§11), returns the validated dict |
| `generate_map(seed, width, height, n_colonies, species_ids, params) -> dict` | M3 | Returns `MapData` (§8.3); raises `MapGenError` |
| `Analytics.record(metrics: dict) -> None` | M4 | Called every 10 ticks with `sim.metrics()`; stores one row |
| `Analytics.render(size: tuple[int, int]) -> pygame.Surface` | M4 | Draws the graphs with the Agg backend; called at most once per second |
| `Analytics.export_csv(path: str) -> None` | M4 | Writes the full history with the columns of §10 |

**Mock engine.** `python/formicae_mock.py` implements the whole API of §9.3 with random-walking dummy ants and the same dtypes, shapes and errors, so M3 and M4 can be developed and tested from week 1 without the C++ build.

## 10. Frontend and analytics

**Window:** 1280×800; map viewport + 280 px sidebar. Pipeline per frame: take the visible cell crop → build RGB array with NumPy (terrain palette LUT, food tint, ants colored by species, optional pheromone overlay) → `blit_array` → scale to zoom. Cull to the viewport; do not process all 1M cells each frame.

**Controls:** wheel = zoom toward cursor; right/middle drag = pan; left click = inspect cell (terrain, food, pheromones per species/channel, occupant, colony); `Space` pause; `N` single step; `+/-` speed; `P` pheromone overlay; `1/2/3` channel; `[ ]` species; `F` spawn-food mode; `R` reset; `E` export CSV; `Tab` analytics panel; `S` save snapshot (P2).

**Time control:** `acc += dt · base_tps · mult` (base\_tps = 30; mult ∈ {0.25, 0.5, 1, 2, 5, 10, MAX}); `n = floor(acc)`; run `step(n)` but stop when the frame's simulation budget (default 10 ms) is spent; show actual ticks/s. Rendering stays at 60 FPS regardless.

**Analytics:** sampled every 10 ticks into preallocated NumPy history (full run kept for CSV); Matplotlib uses the Agg backend, redrawn at most once per second into a pygame surface. Plots: population per species; stored energy per colony; combat deaths per 100 ticks per species (rolling); total food remaining.

**CSV:** columns `tick, pop_s{i}, births_s{i}, kills_s{i}, deaths_combat_s{i}, deaths_hazard_s{i}, deaths_age_s{i}, energy_c{j}, food_total_energy`. **Casualty rate** = Δ deaths per tick over the sampling window, split by cause.

**Heatmaps (stretch):** traffic (increment on entering a cell) and combat (increment per hit), shown with log-scaled color.

## 11. Configuration

One JSON file (`configs/default.json`) with sections `world`, `time`, `pheromone`, `food`, `terrain[]`, `species[]` (each species may contain `castes[]`), `colony`, `hostility`, `render`, `analytics`, and `seeds`. Validated at load: unknown keys rejected, ranges checked, `S ≤ 8`. CLI: `python -m formicae_ui --config configs/default.json --map-seed 42 --sim-seed 7`.

## 12. Repository, build, conventions

```
formicae/
  CMakeLists.txt  pyproject.toml            # scikit-build-core
  engine/include/formicae/   types.hpp config.hpp rng.hpp grid.hpp
                           species.hpp ant.hpp colony.hpp ai.hpp combat.hpp engine.hpp
  engine/src/              engine.cpp pheromones.cpp food.cpp colony.cpp ai.cpp io.cpp
  engine/bindings/module.cpp
  engine/tests/            (Catch2, optional)
  python/formicae_ui/        __main__.py config.py mapgen/ ui/ analytics/
  python/formicae_mock.py
  configs/default.json   docs/SPEC.md   tests/ (pytest)
```

- **Build:** CMake ≥ 3.26, GCC ≥ 12 or Clang ≥ 15, `-std=c++20 -O3 -Wall -Wextra`, `-march=native` behind an option; pybind11 via FetchContent or pip. Install: `pip install -e .`.
- **C++:** namespace `formicae`; types `PascalCase`, functions/vars `snake_case`, constants `UPPER_SNAKE`; `clang-format` (LLVM style); no virtuals/exceptions/allocation in the tick path.
- **Python:** type hints, `ruff` (lint + format), NumPy docstrings on public functions.

## 13. Team split and timeline

Work is split so that every developer owns one main piece and one smaller piece of comparable size, and every developer both writes code that others depend on and depends on someone else's. Review buddies read each other's pull requests.

### 13.1 Team split

| Dev | Main piece | Second piece | Review buddy |
| --- | --- | --- | --- |
| P1 | M1 Core engine: grid layers, tick pipeline, ant slots, pheromone decay | Performance profiling and optimization | P4 |
| P2 | M2 AI: species table, movement, state machine, deposits | Species tuning and trail-quality checks; castes (stretch) | P3 |
| P3 | M2 Combat, hazards, colony lifecycle | Food spawning and loot; demo scenarios | P2 |
| P4 | M0 Integration: build, config, pybind11 bindings, mock engine | UI side panels (inspector, controls); save/load | P1 |
| P5 | M3 Map generator | Analytics, graphs and CSV export | P6 |
| P6 | M4 UI renderer: camera, map and ant drawing, overlays | Time control and keyboard input | P5 |

### 13.2 Tasks per person

| Dev | Weeks | Task | Deliverable |
| --- | --- | --- | --- |
| P1 | 1–2 | `Engine` skeleton, grid layers (§2), RNG, config structs, `grid.hpp` API of §9.4 | Compiles; `step()` runs empty |
| P1 | 3 | Ant slot storage with free list, occupancy layer, tick pipeline with calls to M2 stubs | Pipeline order of §3 in place |
| P1 | 4–5 | Pheromone planes: deposit, decay with precomputed factors, cutoff; optional diffusion; metrics counters | §4 behavior; counters for §9.3 `metrics()` |
| P1 | 6–7 | State hash for determinism, profiling harness (ants/s), `hill_id` initialization | Same-seed runs give equal hashes |
| P1 | 8 | Profile at 100k ants / 1024²; optimize (decay every k ticks, layout, `-march`) | Measured ticks/s recorded in the report |
| P1 | 9–12 | Heatmap counters (stretch), fixes from integration, memory checks | No growth over 100 000 ticks |
| P2 | 1–2 | `species.hpp`, resolved `[species][caste]` table, `Ant` struct (§5.1), stub `ant_update` | Tables load from config |
| P2 | 3–4 | Movement: candidates, weights, random move, speed and move cost (§5.4) | Ants wander on an empty map without collisions |
| P2 | 5 | Pickup, delivery, deposits and `trail_age` | One species forages and a trail forms |
| P2 | 6–7 | FLEEING and FIGHTING transitions, danger weights, hazard reaction (§5.3) | Full state table works with P3's combat |
| P2 | 8–10 | Multi-species tests, tuning of species values, trail-quality measure (share of deliveries on the trail) | Tuned `default.json` species block |
| P2 | 11–12 | Castes (stretch), jam-avoidance swap rule if jams show up, bug fixing | Caste table active with default ratio unchanged |
| P3 | 1–2 | `Colony` array, hill footprint setup, manual and dynamic food spawning (§7.4) | Food appears and grows by rule |
| P3 | 3–4 | `colony_update`: spawn rule, cost, cooldown, free footprint cell, population cap (§7.2) | Colonies produce ants from stored energy |
| P3 | 5–6 | `resolve_attack`, hit roll, damage, hill damage, `on_ant_death`, THORNS damage (§6) | Two species fight; counters by cause |
| P3 | 7 | Colony destruction, loot, orphans (§7.3), hostility matrix | Destroyed colony becomes food |
| P3 | 8–9 | Verify counters, 3 demo scenario configs (peaceful, rivalry, siege) | `configs/scenario_*.json` |
| P3 | 10–12 | Economy balancing, optional colony upkeep (if chosen), bug fixing | Stable populations over 20 000 ticks |
| P4 | 1 | Repository, CMake + scikit-build-core, formatting/lint setup, CI; Python 3.15 wheel check | `pip install -e .` works; decision on Python version |
| P4 | 2 | Config schema, `load_config`, `configs/default.json`; mock engine v0 | M3 and M4 can start against the mock |
| P4 | 3–5 | pybind11 bindings: `Simulation`, `initialize`, `step`, all getters, structured dtypes, errors, `set_param`, `spawn_food`, `set_terrain`, `cell_info` (§9.3) | Mock and real module pass the same API test |
| P4 | 6–8 | Side panels with P6: cell inspector and parameter controls | Click shows `cell_info`; sliders call `set_param` |
| P4 | 9–10 | `save`/`load`, `reset`, API tests (shapes, dtypes, errors) | Saved run resumes identically |
| P4 | 11–12 | Invariant tests (occupancy, pheromone range, determinism) in CI | CI runs a 1000-tick smoke test |
| P5 | 1–2 | Noise fields, terrain classification (§8.2 steps 1–2) | PNG of maps for 20 seeds |
| P5 | 3 | Hills, connectivity corridors, paths, food clusters, validation (steps 3–7), `MapData` | 100 seeds produce valid maps |
| P5 | 4–6 | `Analytics.record`, history arrays, Matplotlib Agg rendering | Four graphs drawn from mock data |
| P5 | 7–9 | Graph panel in the UI with P6; CSV export; casualty rates by cause | `E` key writes CSV that matches graphs |
| P5 | 10 | Map parameters on the command line, seed list for demos | `--map-seed` works |
| P5 | 11–12 | Heatmap overlays (stretch), bug fixing | Traffic and combat overlays |
| P6 | 1–2 | PyGame window, 60 FPS loop with mock engine, terrain palette and crop rendering | Static map at 60 FPS |
| P6 | 3–4 | Camera: zoom toward cursor, pan; food and ants (species colors, skip DEAD) | Smooth zoom/pan at 512² |
| P6 | 5 | Time control: accumulator, speed steps, frame budget, TPS display, `Space`/`N` | Speed 0.25× to MAX works |
| P6 | 6–7 | Pheromone overlay (species/channel selection), hill and colony drawing, hotkeys of §10 | Overlay toggles without slowdown |
| P6 | 8–9 | Switch to the real engine, 10k and 100k ant tests, spawn-food mode, reset key | 60 FPS with 10k ants |
| P6 | 10–12 | Polish, screenshots, caste shades (stretch), bug fixing | Demo-ready UI |
| All | 1 | Spec review and freeze | Frozen spec |
| All | 8 | Integration week: end-to-end runs, cross-module bugs | 2 species, 3 colonies run end to end |
| All | 13 | Each person writes the chapter for their module; final report and user guide | Report complete |
| All | 14 | Buffer and delivery | Delivered |

### 13.3 Milestones

| End of week | Milestone | Done when |
| --- | --- | --- |
| 3 | M1: static world | Generated map shown in the UI from the mock and from the real engine |
| 7 | M2: living world | Ants forage, fight and spawn; colonies can be destroyed |
| 10 | M3: feature complete | Analytics, CSV, save/load, scenarios and inspector all work |
| 12 | Feature freeze | Only bug fixes and balancing from here |
| 14 | Delivery | Report, user guide and demo scenarios ready |
