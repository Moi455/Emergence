cmake_minimum_required(VERSION 3.20)
project(emergence_engine LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)
set(CMAKE_EXPORT_COMPILE_COMMANDS ON)

if(NOT CMAKE_BUILD_TYPE AND NOT CMAKE_CONFIGURATION_TYPES)
  set(CMAKE_BUILD_TYPE Release CACHE STRING "" FORCE)
endif()

include(cmake/StrictFloat.cmake)

enable_testing()

set(GODOT_CPP_DIR "" CACHE PATH "Path to godot-cpp; enables the GDExtension")
set(EMERGENCE_GAME_BIN_DIR "${CMAKE_SOURCE_DIR}/../game/bin" CACHE PATH "Where the GDExtension library is written")
if(GODOT_CPP_DIR)
  set(CMAKE_POSITION_INDEPENDENT_CODE ON)  # the core is linked into a shared library
endif()

add_subdirectory(core)
add_subdirectory(sim)

# Fine world generation (emergence/worldgen, owned by the world generation
# thread) and the terrain module built on it, when the folder is present.
set(EMERGENCE_WORLDGEN_DIR "${CMAKE_CURRENT_SOURCE_DIR}/../worldgen" CACHE PATH "emergence/worldgen")
if(EXISTS "${EMERGENCE_WORLDGEN_DIR}/CMakeLists.txt")
  add_subdirectory(${EMERGENCE_WORLDGEN_DIR} worldgen)
  add_subdirectory(terrain)
endif()

# Godot binding (roadmap 0.4): only when godot-cpp is provided.
if(GODOT_CPP_DIR)
  add_subdirectory(gdext)
endif()
