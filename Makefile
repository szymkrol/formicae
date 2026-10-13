.PHONY: sync run run-mock test cpp-test lint format clean

sync:       ## create .venv, install dependencies, build the C++ module
	uv sync

run:        ## UI with the real C++ engine
	uv run formicae-ui

run-mock:   ## UI with the mock engine (moving dots, no C++ needed)
	uv run formicae-ui --mock

test:       ## Python tests (mock engine and, once built, the real module)
	uv run pytest

cpp-test:   ## build the C++ engine with plain CMake and run engine_smoke
	uv run cmake -S . -B build -DFORMICAE_BUILD_TESTS=ON -Dpybind11_DIR="$$(uv run python -m pybind11 --cmakedir)"
	uv run cmake --build build -j
	./build/engine_smoke

lint:
	uv run ruff check .

format:
	uv run ruff format .

clean:
	rm -rf build .venv dist .pytest_cache .ruff_cache
