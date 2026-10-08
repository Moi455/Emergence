# GDExtension binding the engine core to Godot 4.6 (roadmap 0.4).
# Needs godot-cpp: -DGODOT_CPP_DIR=/path/to/godot-cpp (pinned commit in engine/README.md).
set(GODOTCPP_API_VERSION "4.6" CACHE STRING "")
set(GODOTCPP_TARGET "template_debug" CACHE STRING "")
add_subdirectory(${GODOT_CPP_DIR} ${CMAKE_BINARY_DIR}/godot-cpp EXCLUDE_FROM_ALL)

add_library(emergence_gdext SHARED src/register_types.cpp src/emergence_world.cpp)
target_link_libraries(emergence_gdext PRIVATE emergence_core godot::cpp)
set_target_properties(emergence_gdext PROPERTIES
  POSITION_INDEPENDENT_CODE ON
  OUTPUT_NAME "emergence"
  LIBRARY_OUTPUT_DIRECTORY "${EMERGENCE_GAME_BIN_DIR}")
