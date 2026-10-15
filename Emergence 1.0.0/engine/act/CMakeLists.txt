# EntityStore (T15, docs/14 section 4.7): the non-voxel world. Components generated from catalogue/ by
# catalogue/tools/gen_cpp.py (engine/act/generated). An Applier of the operation bus (engine/ops); no voxel code.
add_library(emergence_act STATIC src/entity_store.cpp src/entity_ops.cpp)
target_include_directories(emergence_act PUBLIC include generated)
target_link_libraries(emergence_act PUBLIC emergence_ops)
emergence_strict_target(emergence_act)

add_executable(test_entity_store tests/test_entity_store.cpp)
target_link_libraries(test_entity_store PRIVATE emergence_act)
target_include_directories(test_entity_store PRIVATE ${CMAKE_CURRENT_SOURCE_DIR}/../core/testing/include)
emergence_strict_target(test_entity_store)
add_test(NAME test_entity_store COMMAND test_entity_store)

add_executable(bench_entity_store bench/bench_entity_store.cpp)
target_link_libraries(bench_entity_store PRIVATE emergence_act)
emergence_strict_target(bench_entity_store)
