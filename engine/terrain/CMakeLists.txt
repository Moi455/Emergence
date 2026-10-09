# Terrain on top of the worldgen module: chunk source, LOD streaming tests
# and the M3 bench on the game's real generator.
add_library(emergence_terrain STATIC src/worldgen_source.cpp)
target_include_directories(emergence_terrain PUBLIC include)
target_link_libraries(emergence_terrain PUBLIC emergence_core emergence_worldgen)
emergence_strict_target(emergence_terrain)

add_executable(test_terrain tests/test_terrain.cpp)
target_link_libraries(test_terrain PRIVATE emergence_terrain)
emergence_strict_target(test_terrain)
add_test(NAME test_terrain COMMAND test_terrain)

add_executable(bench_terrain bench/bench_terrain.cpp)
target_link_libraries(bench_terrain PRIVATE emergence_terrain)
emergence_strict_target(bench_terrain)
