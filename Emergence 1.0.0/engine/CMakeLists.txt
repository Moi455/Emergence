# Emergence 1.0.0 - the social engine (D31), C++20, tables generated from catalogue/ (catalogue/tools/gen_cpp.py).
# Build: cmake -S engine -B build && cmake --build build -j && ctest --test-dir build
cmake_minimum_required(VERSION 3.20)
project(emergence_social_engine LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)
set(CMAKE_EXPORT_COMPILE_COMMANDS ON)
if(NOT CMAKE_BUILD_TYPE AND NOT CMAKE_CONFIGURATION_TYPES)
  set(CMAKE_BUILD_TYPE Release CACHE STRING "" FORCE)
endif()

include(cmake/StrictFloat.cmake)   # emergence_strict_target(): no -ffast-math, warnings as errors
enable_testing()

# World engine (voxels, chunks, meshing, terrain), merged back in from the pre-1.0.0 tree.
# It is built only when its folders are present, so the social engine still builds alone.
set(GODOT_CPP_DIR "" CACHE PATH "Path to godot-cpp; enables the GDExtension")
set(EMERGENCE_GAME_BIN_DIR "${CMAKE_SOURCE_DIR}/../game/bin" CACHE PATH "Where the GDExtension library is written")
if(GODOT_CPP_DIR)
  set(CMAKE_POSITION_INDEPENDENT_CODE ON)  # the core is linked into a shared library
endif()
if(EXISTS "${CMAKE_CURRENT_SOURCE_DIR}/core/CMakeLists.txt")
  add_subdirectory(core)
endif()
if(EXISTS "${CMAKE_CURRENT_SOURCE_DIR}/sim/CMakeLists.txt")
  add_subdirectory(sim)
endif()

if(EXISTS "${CMAKE_CURRENT_SOURCE_DIR}/ops/CMakeLists.txt")
  add_subdirectory(ops)   # operation bus and journal (T16)
endif()

if(EXISTS "${CMAKE_CURRENT_SOURCE_DIR}/act/CMakeLists.txt")
  add_subdirectory(act)   # EntityStore, the non-voxel world (T15)
endif()

add_subdirectory(social)   # social engine (D31), tables generated from catalogue/

# Fine world generation (worldgen/) and the terrain module built on it, when present.
set(EMERGENCE_WORLDGEN_DIR "${CMAKE_CURRENT_SOURCE_DIR}/../worldgen" CACHE PATH "worldgen")
if(EXISTS "${EMERGENCE_WORLDGEN_DIR}/CMakeLists.txt")
  add_subdirectory(${EMERGENCE_WORLDGEN_DIR} worldgen)
  add_subdirectory(terrain)
endif()

# Godot binding: only when godot-cpp is provided.
if(GODOT_CPP_DIR)
  add_subdirectory(gdext)
endif()
