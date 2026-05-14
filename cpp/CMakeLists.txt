add_library(fdk_core INTERFACE)
add_library(fdk::core ALIAS fdk_core)
target_include_directories(fdk_core INTERFACE "${CMAKE_CURRENT_SOURCE_DIR}")

add_subdirectory(httplib)
add_subdirectory(ixwebsocket)
add_subdirectory(boost)
add_subdirectory(nlohmann_json)
