# Agent guidelines — Formicae

Rules for humans and coding agents working in this repository. Follow them on every task unless the user explicitly overrides them.

## Language

- All agent communication, commit messages, PR titles/descriptions, code comments, docstrings, and new documentation **must be in English**.
- Do not introduce Polish (or other non-English) text into the codebase or git history.

## Source of truth

- **Architecture, APIs, algorithms, UI contract, config schema, and team ownership:** `SPECS.md` (canonical). Treat it as infrastructure and product law.
- **How to build, run, and own paths:** `README.md`.
- Prefer existing patterns in the tree over inventing new ones. Match naming, layout, and style of neighboring code.
- If implementation and `SPECS.md` disagree, follow the spec unless the user asks otherwise; note the mismatch briefly.

## Git workflow

1. **Always branch from the latest `master`.** Before starting work:
   ```bash
   git fetch origin
   git checkout master
   git pull --ff-only origin master
   git checkout -b <type>/<short-description>
   ```
2. Branch names: short English kebab-case, e.g. `feat/ui-tps-display`, `fix/pheromone-overlay`, `chore/ci-ruff`.
3. **Commit step by step.** One logical change per commit (one concern: feature slice, fix, refactor, test, or docs). Do not pile unrelated edits into a single commit.
4. Commit messages: concise English, imperative mood, explain *why* when non-obvious. Example: `Add real ticks/s to the sidebar HUD`.
5. Do not commit secrets, local `.venv`, build artifacts, or generated CSV dumps unless the user asks.
6. Do not force-push to `master`, rewrite shared history, or amend commits you did not just create locally, unless the user explicitly requests it.
7. Create commits only when the user asks (or when they clearly request a commit-as-you-go workflow for the current task).

## Production-quality code

- Ship **finished** implementations: correct, readable, and ready to merge — not sketches.
- **Do not leave `TODO`, `FIXME`, `HACK`, or “for later” stubs** in code you just implemented. If a follow-up belongs to another owner (`TODO(P1)`…`TODO(P6)` ownership markers for *unstarted* work), do not invent new TODOs for your own unfinished pieces — finish them or do not claim the change is done.
- Remove obsolete `TODO(Pn)` markers when you complete that work.
- Prefer clear names and small functions over comments that narrate the obvious. Comment intent, invariants, and non-obvious constraints (especially vs `SPECS.md`).
- No dead code, commented-out blocks, or unused imports. No drive-by refactors outside the task scope.
- Respect module owners (see `README.md` / `SPECS.md` §13). Change other owners’ files only when required for the task; keep the diff minimal.

## How to work (agent habits)

1. **Read before writing.** Skim the relevant section of `SPECS.md` and the files you will touch. Search for existing helpers before adding new ones.
2. **Plan briefly, then execute.** For multi-step work, keep a short checklist and complete it in order.
3. **Scope tightly.** Change only what the task needs. Do not expand into unrelated cleanup, renames, or “while we’re here” edits.
4. **Verify.** After meaningful changes, run the appropriate checks:
   - Python / UI / bindings: `uv run pytest`, `uv run ruff check .`
   - C++ engine: `make cpp-test` (or the project’s CMake smoke test)
   - UI smoke (headless): `SDL_VIDEODRIVER=dummy uv run formicae-ui --mock --frames 60`
5. **Report clearly.** Summarize what changed, how to verify it, and any remaining risks or dependencies on other owners (P1–P6).
6. **Do not invent APIs.** Use the Simulation / mock surface described in `SPECS.md` §9. Prefer `formicae_mock` for UI work that does not need the real engine.
7. **Ask only when blocked.** Prefer reading the repo and specs over guessing. If a decision needs a product choice, stop and ask once with options.

## Project map (short)

| Area | Path | Notes |
| --- | --- | --- |
| C++ engine | `engine/` | Core sim; build via CMake / `uv sync` |
| Python bindings | `engine/bindings/`, `pyproject.toml` | Module `formicae` |
| Mock engine | `python/formicae_mock.py` | Full API for UI/mapgen without C++ |
| UI | `python/formicae_ui/ui/` | P6 |
| Mapgen / analytics | `python/formicae_ui/mapgen/`, `analytics/` | P5 |
| Config | `configs/`, `python/formicae_ui/config.py` | JSON schema in `SPECS.md` §11 |

Use `uv` for Python tooling — never plain `pip install` into the system environment.

## Definition of done

A task is done when:

- Behavior matches the relevant part of `SPECS.md` (or an explicit user override).
- Code is production-ready: no leftover TODOs for the implemented scope.
- Relevant tests / smoke checks pass.
- Changes are committed step by step on a branch that started from up-to-date `master` (when commits were requested).
- The response to the user is short, English, and actionable.
