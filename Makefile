.PHONY: sync run run-mock test cpp-test bench lint format clean

sync:       ## create .venv, install dependencies, build the C++ module
	uv sync

run:        ## UI with the real C++ engine
	uv run formicae-ui

run-mock:   ## UI with the mock engine (moving dots, no C++ needed)
	uv run formicae-ui --mock

test:       ## Python tests (mock engine and, once built, the real module)
	uv run pytest

cpp-test:   ## build the C++ engine with plain CMake and run all C++ checks
	uv run cmake -S . -B build -DFORMICAE_BUILD_TESTS=ON -Dpybind11_DIR="$$(uv run python -m pybind11 --cmakedir)"
	uv run cmake --build build -j
	uv run ctest --test-dir build --output-on-failure

bench:      ## Release build of formicae_bench; runs the spec section 3 reference presets
	uv run cmake -S . -B build-bench -DCMAKE_BUILD_TYPE=Release -DFORMICAE_BUILD_PYTHON=OFF -DFORMICAE_BUILD_BENCH=ON
	uv run cmake --build build-bench -j --target formicae_bench
	./build-bench/formicae_bench $(BENCH_ARGS)

lint:
	uv run ruff check .

format:
	uv run ruff format .

clean:
	rm -rf build build-bench .venv dist .pytest_cache .ruff_cache
