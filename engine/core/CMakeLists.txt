add_library(emergence_core STATIC
  base/src/image.cpp
  base/src/fingerprint.cpp
  base/src/parallel.cpp
  world/src/materials.cpp
  world/src/world_plan.cpp
  world/src/relief.cpp
  world/src/erosion.cpp
  world/src/settlements.cpp
  world/src/backdrop.cpp
  world/src/plan_images.cpp
  world/src/brick.cpp
  world/src/chunk_gen.cpp
  mesh/src/greedy.cpp
  mesh/src/chunk_cache.cpp
  mesh/src/terrain_streamer.cpp
)
target_include_directories(emergence_core PUBLIC
  base/include
  world/include
  mesh/include
  testing/include
)
emergence_strict_target(emergence_core)
find_package(Threads REQUIRED)
target_link_libraries(emergence_core PUBLIC Threads::Threads)
target_compile_definitions(emergence_core PUBLIC
  EMERGENCE_DATA_DIR="${CMAKE_CURRENT_SOURCE_DIR}/../data")

function(emergence_test name)
  add_executable(${name} ${ARGN})
  target_link_libraries(${name} PRIVATE emergence_core)
  emergence_strict_target(${name})
  add_test(NAME ${name} COMMAND ${name})
endfunction()

emergence_test(test_base base/tests/test_base.cpp)
emergence_test(test_world_plan world/tests/test_world_plan.cpp)
emergence_test(test_chunks world/tests/test_chunks.cpp)
emergence_test(test_mesh mesh/tests/test_mesh.cpp)

add_executable(bench_world world/bench/bench_world.cpp)
target_link_libraries(bench_world PRIVATE emergence_core)
emergence_strict_target(bench_world)

add_executable(bench_mesh mesh/bench/bench_mesh.cpp)
target_link_libraries(bench_mesh PRIVATE emergence_core)
emergence_strict_target(bench_mesh)
