cmake_minimum_required(VERSION 3.26)
project(formicae LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)
set(CMAKE_POSITION_INDEPENDENT_CODE ON)
if(NOT CMAKE_BUILD_TYPE AND NOT CMAKE_CONFIGURATION_TYPES)
  set(CMAKE_BUILD_TYPE Release)
endif()

option(FORMICAE_NATIVE "Compile with -march=native (not portable)" OFF)
option(FORMICAE_BUILD_PYTHON "Build the pybind11 module" ON)
option(FORMICAE_BUILD_TESTS "Build C++ tests" OFF)

# ---- C++ engine (modules M1 + M2) ---------------------------------------------------------------
add_library(formicae_engine STATIC
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
target_include_directories(formicae_engine PUBLIC engine/include)
target_compile_features(formicae_engine PUBLIC cxx_std_20)
target_compile_options(formicae_engine PRIVATE -Wall -Wextra -Wpedantic)
if(FORMICAE_NATIVE)
  target_compile_options(formicae_engine PRIVATE -march=native)
endif()

# ---- Python module `formicae` (module M0) ---------------------------------------------------------
if(FORMICAE_BUILD_PYTHON)
  find_package(Python REQUIRED COMPONENTS Interpreter Development.Module)
  find_package(pybind11 CONFIG REQUIRED)
  pybind11_add_module(formicae_py engine/bindings/module.cpp)
  target_link_libraries(formicae_py PRIVATE formicae_engine)
  set_target_properties(formicae_py PROPERTIES OUTPUT_NAME formicae)
  install(TARGETS formicae_py LIBRARY DESTINATION .)
  install(FILES python/formicae_mock.py DESTINATION .)
endif()

# ---- C++ tests ----------------------------------------------------------------------------------
if(FORMICAE_BUILD_TESTS)
  enable_testing()
  add_executable(engine_smoke engine/tests/engine_smoke.cpp)
  target_link_libraries(engine_smoke PRIVATE formicae_engine)
  add_test(NAME engine_smoke COMMAND engine_smoke)
endif()
