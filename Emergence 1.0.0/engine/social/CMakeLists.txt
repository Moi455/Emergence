# Social engine (decision D31): tables generated from catalogue/ (python3 catalogue/tools/gen_cpp.py).
add_library(emergence_social STATIC src/governor.cpp src/side_table.cpp)
target_include_directories(emergence_social PUBLIC include generated)
emergence_strict_target(emergence_social)

add_executable(test_social_governor tests/test_governor.cpp)
target_link_libraries(test_social_governor PRIVATE emergence_social)
target_include_directories(test_social_governor PRIVATE ${CMAKE_CURRENT_SOURCE_DIR}/../core/testing/include)
emergence_strict_target(test_social_governor)
add_test(NAME test_social_governor COMMAND test_social_governor)

add_executable(test_social_state tests/test_state.cpp)
target_link_libraries(test_social_state PRIVATE emergence_social)
target_include_directories(test_social_state PRIVATE ${CMAKE_CURRENT_SOURCE_DIR}/../core/testing/include)
emergence_strict_target(test_social_state)
add_test(NAME test_social_state COMMAND test_social_state)

add_executable(test_social_clock tests/test_clock.cpp)
target_link_libraries(test_social_clock PRIVATE emergence_social)
target_include_directories(test_social_clock PRIVATE ${CMAKE_CURRENT_SOURCE_DIR}/../core/testing/include)
emergence_strict_target(test_social_clock)
add_test(NAME test_social_clock COMMAND test_social_clock)

add_executable(test_social_side_table tests/test_side_table.cpp)
target_link_libraries(test_social_side_table PRIVATE emergence_social)
target_include_directories(test_social_side_table PRIVATE ${CMAKE_CURRENT_SOURCE_DIR}/../core/testing/include)
emergence_strict_target(test_social_side_table)
add_test(NAME test_social_side_table COMMAND test_social_side_table)

add_executable(test_social_forgetting tests/test_forgetting.cpp)
target_link_libraries(test_social_forgetting PRIVATE emergence_social)
target_include_directories(test_social_forgetting PRIVATE ${CMAKE_CURRENT_SOURCE_DIR}/../core/testing/include ${CMAKE_CURRENT_SOURCE_DIR}/tests)
emergence_strict_target(test_social_forgetting)
add_test(NAME test_social_forgetting COMMAND test_social_forgetting)
