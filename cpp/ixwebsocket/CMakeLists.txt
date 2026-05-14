include(FetchContent)

FetchContent_Declare(ixwebsocket
    SYSTEM
    GIT_REPOSITORY https://github.com/machinezone/IXWebSocket.git
    GIT_TAG v11.4.6
    GIT_SHALLOW TRUE)
FetchContent_MakeAvailable(ixwebsocket)

# GCC 16 can report false array bounds in speculatively devirtualized shared_ptr
# cleanup. Limit the workaround to the affected dependency translation unit.
if(CMAKE_CXX_COMPILER_ID STREQUAL "GNU"
   AND CMAKE_CXX_COMPILER_VERSION VERSION_GREATER_EQUAL 16
   AND CMAKE_CXX_COMPILER_VERSION VERSION_LESS 17)
    set_source_files_properties("${ixwebsocket_SOURCE_DIR}/ixwebsocket/IXDNSLookup.cpp"
        TARGET_DIRECTORY ixwebsocket PROPERTIES COMPILE_OPTIONS "-Wno-array-bounds")
endif()
