# Emergence 1.0.0 - the social engine (D31), C++20, tables generated from catalogue/ (catalogue/tools/gen_cpp.py).
# Build: cmake -S engine -B build && cmake --build build -j && ctest --test-dir build
cmake_minimum_required(VERSION 3.20)
project(emergence_social_engine LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)
set(CMAKE_EXPORT_COMPILE_COMMANDS ON)
if(NOT CMAKE_BUILD_TYPE AND NOT CMAKE_CONFIGURATION_TYPES)
  set(CMAKE_BUILD_TYPE Release CACHE STRING "" FORCE)
endif()

include(cmake/StrictFloat.cmake)   # emergence_strict_target(): no -ffast-math, warnings as errors
enable_testing()
add_subdirectory(social)
