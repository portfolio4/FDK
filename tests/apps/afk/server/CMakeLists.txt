add_executable(fake_codex_process fake_codex_process.cpp)
target_link_libraries(fake_codex_process PRIVATE nlohmann_json::nlohmann_json Threads::Threads)

add_executable(fake_codex_agent fake_codex_agent.cpp)
target_link_libraries(fake_codex_agent PRIVATE nlohmann_json::nlohmann_json)

add_catch_tests(test_afk_core SOURCES
    test_codex_agent.cpp
    test_codex_process.cpp
    test_dialogue_session.cpp
    test_normalize_fpga_text.cpp
)
target_link_libraries(test_afk_core PRIVATE afk::core nlohmann_json::nlohmann_json)
target_compile_definitions(test_afk_core PRIVATE
    AFK_FAKE_CODEX_EXECUTABLE="$<TARGET_FILE:fake_codex_process>"
    AFK_FAKE_CODEX_AGENT_EXECUTABLE="$<TARGET_FILE:fake_codex_agent>")
add_dependencies(test_afk_core fake_codex_process fake_codex_agent)


if(CMAKE_BUILD_TYPE STREQUAL "Release")
    # Manual integration test: never built by ALL or registered with CTest.
    set(AFK_WHISPER_MODEL "${CMAKE_BINARY_DIR}/mount-afk/models/ggml-base.en.bin" CACHE FILEPATH "Whisper model")
    set(AFK_WHISPER_VAD_MODEL "${CMAKE_BINARY_DIR}/mount-afk/models/ggml-silero-v6.2.0.bin" CACHE FILEPATH "Silero VAD model")
    set(AFK_WHISPER_TEST_AUDIO "${CMAKE_CURRENT_SOURCE_DIR}/resources/jfk.wav" CACHE FILEPATH "Mono 16 kHz PCM16 test WAV")
    add_executable(test_whisper_stt EXCLUDE_FROM_ALL test_whisper_stt.cpp)
    add_dependencies(test_whisper_stt afk_assets)
    target_link_libraries(test_whisper_stt PRIVATE afk::core Catch2::Catch2WithMain)
    target_compile_definitions(test_whisper_stt PRIVATE
        AFK_WHISPER_MODEL="${AFK_WHISPER_MODEL}"
        AFK_WHISPER_VAD_MODEL="${AFK_WHISPER_VAD_MODEL}"
        AFK_WHISPER_TEST_AUDIO="${AFK_WHISPER_TEST_AUDIO}")
else()
    message(STATUS "test_whisper_stt disabled: requires CMAKE_BUILD_TYPE=Release")
endif()
