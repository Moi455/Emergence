# emergence_worldgen: fine world generation (2 cm voxel chunks) from the
# world plan of engine/core/world. Built standalone (pulls the engine in) or
# from a parent project that already defines emergence_core.
cmake_minimum_required(VERSION 3.20)
project(emergence_worldgen LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)
if(NOT CMAKE_BUILD_TYPE AND NOT CMAKE_CONFIGURATION_TYPES)
  set(CMAKE_BUILD_TYPE Release CACHE STRING "" FORCE)
endif()

if(NOT TARGET emergence_core)
  set(EMERGENCE_ENGINE_DIR "${CMAKE_CURRENT_SOURCE_DIR}/../engine" CACHE PATH "engine/ of the Emergence repository")
  add_subdirectory(${EMERGENCE_ENGINE_DIR} engine)
  # The engine locates data/ from CMAKE_SOURCE_DIR, which is this folder when
  # worldgen is the top project: point it back at engine/data.
  foreach(prop COMPILE_DEFINITIONS INTERFACE_COMPILE_DEFINITIONS)
    get_target_property(defs emergence_core ${prop})
    list(TRANSFORM defs REPLACE "^EMERGENCE_DATA_DIR=.*$" "EMERGENCE_DATA_DIR=\"${EMERGENCE_ENGINE_DIR}/data\"")
    set_target_properties(emergence_core PROPERTIES ${prop} "${defs}")
  endforeach()
endif()
enable_testing()

add_library(emergence_worldgen STATIC
  src/worldgen.cpp
  src/surface.cpp
  src/geology.cpp
  src/raster.cpp
  src/caves.cpp
  src/trees.cpp
)
target_include_directories(emergence_worldgen PUBLIC include)
target_link_libraries(emergence_worldgen PUBLIC emergence_core)
emergence_strict_target(emergence_worldgen)

add_executable(test_worldgen tests/test_worldgen.cpp)
target_link_libraries(test_worldgen PRIVATE emergence_worldgen)
emergence_strict_target(test_worldgen)
target_compile_definitions(test_worldgen PRIVATE
  EMERGENCE_WORLDGEN_GOLDEN="${CMAKE_CURRENT_SOURCE_DIR}/tests/golden_seed7_4km.txt")
add_test(NAME test_worldgen COMMAND test_worldgen)

add_executable(worldgen_tool tools/worldgen_tool.cpp)
target_link_libraries(worldgen_tool PRIVATE emergence_worldgen)
emergence_strict_target(worldgen_tool)
