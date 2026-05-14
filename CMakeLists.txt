cmake_minimum_required(VERSION 3.30)

# Select a default only before compiler detection and without an explicit override.
if(NOT CMAKE_CXX_COMPILER AND "$ENV{CXX}" STREQUAL ""
   AND NOT CMAKE_TOOLCHAIN_FILE AND "$ENV{CMAKE_TOOLCHAIN_FILE}" STREQUAL "")
    set(CMAKE_CXX_COMPILER g++-16 CACHE FILEPATH "C++ compiler")
endif()

project(FPGADevelopmentKit LANGUAGES CXX)

if(NOT CMAKE_SYSTEM_NAME STREQUAL "Linux")
    message(FATAL_ERROR "Project only supports Linux.")
endif()
if(CMAKE_SOURCE_DIR STREQUAL CMAKE_BINARY_DIR)
    message(FATAL_ERROR "Use an out-of-source build: cmake -S . -B build_debug/host -DCMAKE_BUILD_TYPE=Debug")
endif()
if(CMAKE_CONFIGURATION_TYPES)
    message(FATAL_ERROR "Use a single-configuration generator (Ninja or Unix Makefiles).")
endif()
set(CMAKE_CXX_STANDARD 23)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)
set(CMAKE_RUNTIME_OUTPUT_DIRECTORY "${CMAKE_BINARY_DIR}/bin")
add_compile_options(-Wall -Wextra -Wpedantic -Werror)

include(CTest)
add_subdirectory(cpp)
add_subdirectory(fpga)
add_subdirectory(examples)
add_subdirectory(apps)
if(BUILD_TESTING)
    add_subdirectory(tests)
endif()
