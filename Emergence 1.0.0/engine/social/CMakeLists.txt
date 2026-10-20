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

# T24: the speech between minds (SpeechRouter) and the bounded writes of the model (MindWriter).
target_sources(emergence_social PRIVATE src/mind_writer.cpp src/speech_router.cpp)

# T28: the tok-2 tokenizer in C++ (engine/social/tokenizer): same arrays as the Python oracle ai/tok2, feasibility mask,
# candidates, and a C interface for training (one tokenizer, in the game and in the training).
find_package(Threads REQUIRED)
add_library(emergence_tok2 STATIC
  tokenizer/src/value.cpp tokenizer/src/tokenizer.cpp tokenizer/src/mask.cpp tokenizer/src/candidates.cpp)
target_include_directories(emergence_tok2 PUBLIC tokenizer/include tokenizer/generated)
target_link_libraries(emergence_tok2 PUBLIC emergence_social)
emergence_strict_target(emergence_tok2)

add_executable(test_tok2_parity tokenizer/tests/test_parity.cpp)
target_link_libraries(test_tok2_parity PRIVATE emergence_tok2)
emergence_strict_target(test_tok2_parity)
add_test(NAME test_tok2_golden COMMAND test_tok2_parity ${CMAKE_CURRENT_SOURCE_DIR}/../../ai/tok2/golden/cases.jsonl)

add_executable(test_social_speech tests/test_speech_router.cpp)
target_link_libraries(test_social_speech PRIVATE emergence_social)
target_include_directories(test_social_speech PRIVATE ${CMAKE_CURRENT_SOURCE_DIR}/../core/testing/include ${CMAKE_CURRENT_SOURCE_DIR}/tests)
emergence_strict_target(test_social_speech)
add_test(NAME test_social_speech COMMAND test_social_speech)
add_executable(bench_tok2 tokenizer/tests/bench_tok2.cpp)
target_link_libraries(bench_tok2 PRIVATE emergence_tok2 Threads::Threads)
emergence_strict_target(bench_tok2)

add_executable(test_social_mind_writer tests/test_mind_writer.cpp)
target_link_libraries(test_social_mind_writer PRIVATE emergence_social)
target_include_directories(test_social_mind_writer PRIVATE ${CMAKE_CURRENT_SOURCE_DIR}/../core/testing/include)
emergence_strict_target(test_social_mind_writer)
add_test(NAME test_social_mind_writer COMMAND test_social_mind_writer)

foreach(t mask candidates half)
  add_executable(test_tok2_${t} tokenizer/tests/test_${t}.cpp)
  target_link_libraries(test_tok2_${t} PRIVATE emergence_tok2)
  target_include_directories(test_tok2_${t} PRIVATE ${CMAKE_CURRENT_SOURCE_DIR}/../core/testing/include)
  emergence_strict_target(test_tok2_${t})
  add_test(NAME test_tok2_${t} COMMAND test_tok2_${t})
endforeach()
target_include_directories(test_tok2_parity PRIVATE ${CMAKE_CURRENT_SOURCE_DIR}/../core/testing/include)

# C interface for the training (ctypes): a shared library with the same code as the game (ai/tok2/native.py loads it).
add_library(emergence_tok2_capi SHARED tokenizer/src/tokenizer_capi.cpp)
target_link_libraries(emergence_tok2_capi PRIVATE emergence_tok2)
set_target_properties(emergence_social emergence_tok2 emergence_tok2_capi PROPERTIES POSITION_INDEPENDENT_CODE ON)
emergence_strict_target(emergence_tok2_capi)

# T28 parity on the shared corpus (5000 sampler situations + 3000 faulty copies, expectations from the Python oracle) and
# the Python<->C++ tests through the C interface. They need python3 (the oracle); without it only the golden test runs.
find_package(Python3 COMPONENTS Interpreter QUIET)
if(Python3_Interpreter_FOUND)
  set(TOK2_CORPUS ${CMAKE_BINARY_DIR}/tok2_corpus.jsonl)
  add_test(NAME tok2_corpus_build COMMAND ${Python3_EXECUTABLE} ${CMAKE_CURRENT_SOURCE_DIR}/tokenizer/make_corpus.py --out ${TOK2_CORPUS} --reuse)
  set_tests_properties(tok2_corpus_build PROPERTIES FIXTURES_SETUP tok2_corpus TIMEOUT 900)
  add_test(NAME tok2_corpus_pin COMMAND ${Python3_EXECUTABLE} ${CMAKE_CURRENT_SOURCE_DIR}/tokenizer/make_corpus.py --out ${TOK2_CORPUS} --reuse --check-pin)
  set_tests_properties(tok2_corpus_pin PROPERTIES DEPENDS tok2_corpus_build)
  add_test(NAME test_tok2_corpus COMMAND test_tok2_parity ${TOK2_CORPUS})
  set_tests_properties(test_tok2_corpus PROPERTIES FIXTURES_REQUIRED tok2_corpus)
  add_test(NAME test_tok2_python COMMAND ${Python3_EXECUTABLE} -m unittest discover -s ${CMAKE_CURRENT_SOURCE_DIR}/tokenizer/tests -t ${CMAKE_CURRENT_SOURCE_DIR}/tokenizer/tests)
  set_tests_properties(test_tok2_python PROPERTIES ENVIRONMENT "EM_TOK2_LIB=$<TARGET_FILE:emergence_tok2_capi>" DEPENDS tok2_corpus_build)
endif()

# T24: the shared speech vectors are exactly what the Python oracle writes (reads the file, writes nothing).
find_package(Python3 COMPONENTS Interpreter)
if(Python3_Interpreter_FOUND)
  add_test(NAME speech_vectors_up_to_date COMMAND ${Python3_EXECUTABLE} ${CMAKE_CURRENT_SOURCE_DIR}/../../catalogue/tools/speech_vectors.py --check)
endif()

# T28b: the ContextBuilder (engine/social/tokenizer/context_builder): NpcState + side table + arena + perception links + wake
# -> DecisionContext, tokenized by the T28 tokenizer. Parity with the Python oracle on the quantised sampler situations.
target_sources(emergence_tok2 PRIVATE tokenizer/src/context_builder.cpp)
add_executable(test_context_builder tokenizer/tests/test_context_builder.cpp)
target_link_libraries(test_context_builder PRIVATE emergence_tok2)
target_include_directories(test_context_builder PRIVATE ${CMAKE_CURRENT_SOURCE_DIR}/../core/testing/include tokenizer/tests)
emergence_strict_target(test_context_builder)
add_test(NAME test_context_builder COMMAND test_context_builder)
add_executable(test_context_parity tokenizer/tests/test_context_parity.cpp)
target_link_libraries(test_context_parity PRIVATE emergence_tok2)
target_include_directories(test_context_parity PRIVATE tokenizer/tests)
emergence_strict_target(test_context_parity)
if(Python3_Interpreter_FOUND)
  set(CTX_CORPUS ${CMAKE_BINARY_DIR}/context_corpus.jsonl)
  add_test(NAME context_corpus_build COMMAND ${Python3_EXECUTABLE} ${CMAKE_CURRENT_SOURCE_DIR}/tokenizer/make_context_corpus.py --out ${CTX_CORPUS} --reuse)
  set_tests_properties(context_corpus_build PROPERTIES FIXTURES_SETUP context_corpus TIMEOUT 1200)
  add_test(NAME test_context_parity COMMAND test_context_parity ${CTX_CORPUS} --selection=both --bench=2 --min-rate=1000)
  set_tests_properties(test_context_parity PROPERTIES FIXTURES_REQUIRED context_corpus TIMEOUT 1200)
endif()
