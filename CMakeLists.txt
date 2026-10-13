cmake_minimum_required(VERSION 3.26)
project(antsim LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)
set(CMAKE_POSITION_INDEPENDENT_CODE ON)
if(NOT CMAKE_BUILD_TYPE AND NOT CMAKE_CONFIGURATION_TYPES)
  set(CMAKE_BUILD_TYPE Release)
endif()

option(ANTSIM_NATIVE "Compile with -march=native (not portable)" OFF)
option(ANTSIM_BUILD_PYTHON "Build the pybind11 module" ON)
option(ANTSIM_BUILD_TESTS "Build C++ tests" OFF)

# ---- C++ engine (modules M1 + M2) ---------------------------------------------------------------
add_library(antsim_engine STATIC
  engine/src/config.cpp
  engine/src/grid.cpp
  engine/src/engine.cpp
  engine/src/pheromones.cpp
  engine/src/food.cpp
  engine/src/io.cpp
  engine/src/species.cpp
  engine/src/ai.cpp
  engine/src/colony.cpp
  engine/src/combat.cpp
)
target_include_directories(antsim_engine PUBLIC engine/include)
target_compile_features(antsim_engine PUBLIC cxx_std_20)
target_compile_options(antsim_engine PRIVATE -Wall -Wextra -Wpedantic)
if(ANTSIM_NATIVE)
  target_compile_options(antsim_engine PRIVATE -march=native)
endif()

# ---- Python module `antsim` (module M0) ---------------------------------------------------------
if(ANTSIM_BUILD_PYTHON)
  find_package(Python REQUIRED COMPONENTS Interpreter Development.Module)
  find_package(pybind11 CONFIG REQUIRED)
  pybind11_add_module(antsim_py engine/bindings/module.cpp)
  target_link_libraries(antsim_py PRIVATE antsim_engine)
  set_target_properties(antsim_py PROPERTIES OUTPUT_NAME antsim)
  install(TARGETS antsim_py LIBRARY DESTINATION .)
  install(FILES python/antsim_mock.py DESTINATION .)
endif()

# ---- C++ tests ----------------------------------------------------------------------------------
if(ANTSIM_BUILD_TESTS)
  enable_testing()
  add_executable(engine_smoke engine/tests/engine_smoke.cpp)
  target_link_libraries(engine_smoke PRIVATE antsim_engine)
  add_test(NAME engine_smoke COMMAND engine_smoke)
endif()
