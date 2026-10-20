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

# T18: laws of matter 1 (ContactResolver, ProcessEngine, engine/act/laws/). Tables: matter_gen.h from catalogue/tools/gen_matter.py.
add_library(emergence_matter STATIC matter_catalog.cpp contact_resolver.cpp process_engine.cpp
            laws/law_kit.cpp laws/separate_laws.cpp laws/join_laws.cpp laws/collapse_law.cpp)
target_include_directories(emergence_matter PUBLIC ${CMAKE_CURRENT_SOURCE_DIR} ${CMAKE_CURRENT_SOURCE_DIR}/generated/emergence/act)
target_link_libraries(emergence_matter PUBLIC emergence_act)
emergence_strict_target(emergence_matter)

add_executable(test_matter_laws tests/test_matter_laws.cpp)
target_link_libraries(test_matter_laws PRIVATE emergence_matter)
target_include_directories(test_matter_laws PRIVATE ${CMAKE_CURRENT_SOURCE_DIR}/../core/testing/include ${CMAKE_CURRENT_SOURCE_DIR}/../social/generated)
emergence_strict_target(test_matter_laws)
add_test(NAME test_matter_laws COMMAND test_matter_laws)

add_executable(bench_matter_laws bench/bench_matter_laws.cpp)
target_link_libraries(bench_matter_laws PRIVATE emergence_matter)
emergence_strict_target(bench_matter_laws)

# T18 spec: no tool name in engine/act/laws/ (laws read properties). grep exits 1 when it finds nothing.
add_test(NAME matter_laws_name_no_tool COMMAND sh -c "! grep -rniwE '(axe|hatchet|hammer|sledgehammer|knife|sword|saw|pickaxe|shovel|hoe|mace|chisel|mallet|adze|whetstone|rope|crowbar)' ${CMAKE_CURRENT_SOURCE_DIR}/laws")

# T23 (docs/14 section 6.1): the perception by observer. Entities only; the voxel space is behind the SpaceQuery interface.
add_library(emergence_perception STATIC perception/src/percept_rules.cpp perception/src/space_query.cpp
            perception/src/spatial_index.cpp perception/src/perception_engine.cpp)
target_include_directories(emergence_perception PUBLIC perception/include)
target_link_libraries(emergence_perception PUBLIC emergence_act emergence_social)
emergence_strict_target(emergence_perception)

add_executable(test_perception perception/tests/test_perception.cpp)
target_link_libraries(test_perception PRIVATE emergence_perception)
target_include_directories(test_perception PRIVATE ${CMAKE_CURRENT_SOURCE_DIR}/../core/testing/include)
emergence_strict_target(test_perception)
add_test(NAME test_perception COMMAND test_perception)

add_executable(bench_perception perception/bench/bench_perception.cpp)
target_link_libraries(bench_perception PRIVATE emergence_perception)
emergence_strict_target(bench_perception)

# T23b (docs/14 section 4.8): mental map and route planner. Knowledge only; the voxel space is behind the ViewProbe interface.
add_library(emergence_navigation STATIC navigation/src/road_plan.cpp navigation/src/mental_map.cpp navigation/src/route_planner.cpp
            navigation/src/view_probe.cpp navigation/src/navigator.cpp)
target_include_directories(emergence_navigation PUBLIC navigation/include)
target_link_libraries(emergence_navigation PUBLIC emergence_act)
emergence_strict_target(emergence_navigation)

add_executable(test_navigation navigation/tests/test_navigation.cpp)
target_link_libraries(test_navigation PRIVATE emergence_navigation emergence_social)
target_include_directories(test_navigation PRIVATE ${CMAKE_CURRENT_SOURCE_DIR}/../core/testing/include)
emergence_strict_target(test_navigation)
add_test(NAME test_navigation COMMAND test_navigation)

add_executable(bench_navigation navigation/bench/bench_navigation.cpp)
target_link_libraries(bench_navigation PRIVATE emergence_navigation)
emergence_strict_target(bench_navigation)

# T23b spec: the planner never touches the world. grep exits 1 when it finds nothing.
add_test(NAME navigation_planner_no_world COMMAND sh -c "! grep -nE 'view_probe|ViewProbe|FlatTerrain|entity_store|EntityStore|SpaceQuery' ${CMAKE_CURRENT_SOURCE_DIR}/navigation/src/route_planner.cpp ${CMAKE_CURRENT_SOURCE_DIR}/navigation/include/emergence/act/navigation/route_planner.h ${CMAKE_CURRENT_SOURCE_DIR}/navigation/include/emergence/act/navigation/mental_map.h ${CMAKE_CURRENT_SOURCE_DIR}/navigation/src/mental_map.cpp")

# T22: the executor of gestures (docs/14 sections 4.3 and 4.4). Timing table: gesture_timing_gen.h from catalogue/tools/gen_act_timing.py.
# Terrain and perception come through interfaces (ExecutorNavigation, ActorSenses); the voxel world is not touched.
add_library(emergence_gesture STATIC gesture_timing.cpp gesture_executor.cpp gesture_senses.cpp executor_navigation.cpp
            resolver_frame.cpp navigator_adapter.cpp)
target_link_libraries(emergence_gesture PUBLIC emergence_matter emergence_perception emergence_social emergence_navigation)
emergence_strict_target(emergence_gesture)

add_executable(test_gesture_executor tests/test_gesture_executor.cpp)
target_link_libraries(test_gesture_executor PRIVATE emergence_gesture)
target_include_directories(test_gesture_executor PRIVATE ${CMAKE_CURRENT_SOURCE_DIR}/../core/testing/include ${CMAKE_CURRENT_SOURCE_DIR}/tests)
emergence_strict_target(test_gesture_executor)
add_test(NAME test_gesture_executor COMMAND test_gesture_executor)

add_executable(bench_gesture_executor bench/bench_gesture_executor.cpp)
target_link_libraries(bench_gesture_executor PRIVATE emergence_gesture)
target_include_directories(bench_gesture_executor PRIVATE ${CMAKE_CURRENT_SOURCE_DIR}/tests)
emergence_strict_target(bench_gesture_executor)

# The generated timing table must be in step with catalogue/data (no identifier moves: the generator only adds a header).
find_package(Python3 COMPONENTS Interpreter)
if(Python3_FOUND)
  add_test(NAME gesture_timing_table_fresh COMMAND ${Python3_EXECUTABLE} ${CMAKE_CURRENT_SOURCE_DIR}/../../catalogue/tools/gen_act_timing.py --check)
endif()

# T22 x T28b: the plan facts against a real ContextBuilder (the plan targets carry the bit-31 header).
add_executable(test_gesture_plan_context tests/test_gesture_plan_context.cpp)
target_link_libraries(test_gesture_plan_context PRIVATE emergence_gesture emergence_tok2)
target_include_directories(test_gesture_plan_context PRIVATE ${CMAKE_CURRENT_SOURCE_DIR}/../core/testing/include ${CMAKE_CURRENT_SOURCE_DIR}/tests
                           ${CMAKE_CURRENT_SOURCE_DIR}/../social/tokenizer/tests)
emergence_strict_target(test_gesture_plan_context)
add_test(NAME test_gesture_plan_context COMMAND test_gesture_plan_context)
