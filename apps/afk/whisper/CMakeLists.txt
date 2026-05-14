include(FetchContent)

# Scope dependency settings to this directory, preserving our own strict warnings.
get_directory_property(whisper_compile_options COMPILE_OPTIONS)
list(REMOVE_ITEM whisper_compile_options -Werror)
set_directory_properties(PROPERTIES COMPILE_OPTIONS "${whisper_compile_options}")
set(CMAKE_POLICY_DEFAULT_CMP0077 NEW)
set(BUILD_SHARED_LIBS OFF)
set(WHISPER_BUILD_TESTS OFF)
set(WHISPER_BUILD_EXAMPLES OFF)
set(WHISPER_BUILD_SERVER OFF)
set(GGML_CCACHE OFF)

FetchContent_Declare(whisper_cpp
    SYSTEM
    GIT_REPOSITORY https://github.com/ggml-org/whisper.cpp.git
    GIT_TAG v1.8.3
    GIT_SHALLOW TRUE)
FetchContent_MakeAvailable(whisper_cpp)

# GCC 16's range analysis overestimates the normalized timestamp fields.
# Suppress only this diagnostic in the upstream implementation file.
if(CMAKE_CXX_COMPILER_ID STREQUAL "GNU"
   AND CMAKE_CXX_COMPILER_VERSION VERSION_GREATER_EQUAL 16
   AND CMAKE_CXX_COMPILER_VERSION VERSION_LESS 17)
    set_source_files_properties("${whisper_cpp_SOURCE_DIR}/src/whisper.cpp"
        TARGET_DIRECTORY whisper PROPERTIES COMPILE_OPTIONS "-Wno-format-truncation")
endif()
