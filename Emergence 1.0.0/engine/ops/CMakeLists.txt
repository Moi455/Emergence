# Operation bus and journal (T16, docs/14 section 4.6 and 4.9). Standalone: no Godot, no other engine module.
add_library(emergence_ops STATIC src/digest.cpp src/operation.cpp src/operation_bus.cpp src/op_journal.cpp)
target_include_directories(emergence_ops PUBLIC include)
emergence_strict_target(emergence_ops)
find_package(Threads REQUIRED)
target_link_libraries(emergence_ops PUBLIC Threads::Threads)

add_executable(test_ops tests/test_ops.cpp)
target_link_libraries(test_ops PRIVATE emergence_ops)
target_include_directories(test_ops PRIVATE ${CMAKE_CURRENT_SOURCE_DIR}/../core/testing/include)
emergence_strict_target(test_ops)
add_test(NAME test_ops COMMAND test_ops)

add_executable(bench_ops bench/bench_ops.cpp)
target_link_libraries(bench_ops PRIVATE emergence_ops)
emergence_strict_target(bench_ops)
