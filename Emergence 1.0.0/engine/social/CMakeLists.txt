# Social engine (decision D31): tables generated from catalogue/ (python3 catalogue/tools/gen_cpp.py).
add_library(emergence_social STATIC src/governor.cpp src/side_table.cpp src/npc_state_codec.cpp)
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

add_executable(test_social_codec tests/test_codec.cpp)
target_link_libraries(test_social_codec PRIVATE emergence_social)
target_include_directories(test_social_codec PRIVATE ${CMAKE_CURRENT_SOURCE_DIR}/../core/testing/include)
emergence_strict_target(test_social_codec)
add_test(NAME test_social_codec COMMAND test_social_codec)

# T13: the inner language (parser + typed validator), parity with catalogue/tools/language.py on shared vectors.
target_sources(emergence_social PRIVATE src/language.cpp)

add_executable(test_social_language tests/test_language.cpp)
target_link_libraries(test_social_language PRIVATE emergence_social)
target_include_directories(test_social_language PRIVATE ${CMAKE_CURRENT_SOURCE_DIR}/../core/testing/include ${CMAKE_CURRENT_SOURCE_DIR}/tests)
emergence_strict_target(test_social_language)
add_test(NAME test_social_language COMMAND test_social_language)

# T06: the per-NPC proposition arena and its law of forgetting.
target_sources(emergence_social PRIVATE src/npc_bundle.cpp)

# T06: the reference save written BEFORE the compaction is reloaded by the test.
target_compile_definitions(test_social_codec PRIVATE EM_TESTDATA_DIR="${CMAKE_CURRENT_SOURCE_DIR}/tests/data")

# T14: the governor judges speech and records (check_utterance, check_record), parity with governor.py on shared vectors.
add_executable(test_social_governor_speech tests/test_governor_speech.cpp)
target_link_libraries(test_social_governor_speech PRIVATE emergence_social)
target_include_directories(test_social_governor_speech PRIVATE ${CMAKE_CURRENT_SOURCE_DIR}/../core/testing/include ${CMAKE_CURRENT_SOURCE_DIR}/tests)
emergence_strict_target(test_social_governor_speech)
add_test(NAME test_social_governor_speech COMMAND test_social_governor_speech)

# T21: the laws of the body and of the mind that the ENGINE applies at each tick (hunger, thirst, sleep, emotions, ageing...).
target_sources(emergence_social PRIVATE src/npc_laws.cpp)

add_executable(test_social_npc_laws tests/test_npc_laws.cpp)
target_link_libraries(test_social_npc_laws PRIVATE emergence_social)
target_include_directories(test_social_npc_laws PRIVATE ${CMAKE_CURRENT_SOURCE_DIR}/../core/testing/include)
emergence_strict_target(test_social_npc_laws)
add_test(NAME test_social_npc_laws COMMAND test_social_npc_laws)
