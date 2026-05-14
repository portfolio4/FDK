find_package(Threads REQUIRED GLOBAL)
set(AFK_SOURCES
    src/Backends.cpp
    src/CodexAgent.cpp
    src/CodexProcess.cpp
    src/DirectoryServer.cpp
    src/DialogueSession.cpp
    src/DialogueServer.cpp
    src/SpeechWorker.cpp
    src/TriggerManager.cpp
    src/WhisperSTT.cpp
)
add_library(afk_core STATIC ${AFK_SOURCES})
add_library(afk::core ALIAS afk_core)
target_include_directories(afk_core PUBLIC "${CMAKE_CURRENT_SOURCE_DIR}/include")
target_link_libraries(afk_core
    PUBLIC
        fdk::core
        fdk::fpga
        httplib::httplib
        ixwebsocket::ixwebsocket
        Boost::headers
        nlohmann_json::nlohmann_json
    PRIVATE
        Threads::Threads
        whisper
)

# CodexAgent uses this empty directory as the cwd for thread/start. Create it
# ahead of time so the path exists and Codex starts outside the source repository.
file(MAKE_DIRECTORY "${CMAKE_CURRENT_BINARY_DIR}/codex-cwd")
target_compile_definitions(afk_core PRIVATE
    AFK_CODEX_CWD="${CMAKE_CURRENT_BINARY_DIR}/codex-cwd")

add_executable(afk_host main.cpp)
target_link_libraries(afk_host PRIVATE afk::core)

# Refresh assets even when the executable itself does not need relinking.
set(AFK_MOUNT_DIRECTORY "${CMAKE_BINARY_DIR}/mount-afk")
add_custom_target(afk_assets
    COMMAND "${CMAKE_COMMAND}" -E copy_directory_if_different
        "${CMAKE_CURRENT_SOURCE_DIR}/../frontend" "${AFK_MOUNT_DIRECTORY}/files"
    COMMAND "${CMAKE_COMMAND}" -E copy_directory_if_different
        "${CMAKE_CURRENT_SOURCE_DIR}/resources" "${AFK_MOUNT_DIRECTORY}/resources"
    COMMAND "${CMAKE_COMMAND}" -E copy_directory_if_different
        "${CMAKE_CURRENT_SOURCE_DIR}/../whisper/models" "${AFK_MOUNT_DIRECTORY}/models"
    COMMENT "Copying AFK runtime assets to mount-afk"
    VERBATIM)
add_dependencies(afk_host afk_assets)
