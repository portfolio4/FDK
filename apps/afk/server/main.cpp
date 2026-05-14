#include <afk/dialogue/DialogueSession.h>
#include <afk/fpga/ThreadSafeAfkFpga.h>
#include <afk/fpga/Channel.h>
#include <afk/fpga/TriggerManager.h>
#include <afk/http/DirectoryServer.h>
#include <afk/websocket/DialogueServer.h>
#include <afk/whisper/SpeechWorker.h>
#include <fdk/log/Log.h>

#include <chrono>
#include <csignal>
#include <filesystem>
#include <format>
#include <stdexcept>
#include <thread>

namespace {
volatile std::sig_atomic_t stop_requested = 0;
void request_stop(int) { stop_requested = 1; }
} // namespace

int main(int argc, char* argv[]) {
    if (argc != 3) {
        LOG_ERR("Usage: {} <mount-afk-path> <serial-device>", argv[0]);
        return 1;
    }
    std::signal(SIGINT, request_stop);
    std::signal(SIGTERM, request_stop);
    constexpr auto host = "127.0.0.1";
    constexpr int http_port = 8000;
    constexpr int ws_port = 8001;
    const auto mount = std::filesystem::path(argv[1]);
    const auto frontend = mount / "files";
    const auto prompt_path = mount / "resources/system_prompt.md";
    const auto models = mount / "models";

    // Initialize every required service before opening either listener.
    afk::ThreadSafeAfkFpga fpga(argv[2]);
    if (const auto result = fpga.test_request(afk::channels::ADMIN); !result) {
        throw std::runtime_error(std::format("TestRequest failed: {}", result.error().text()));
    }
    afk::TriggerManager trigger_manager(fpga);
    trigger_manager.ProgramTriggers();
    afk::dialogue::AfkFpgaBackend fpga_backend(fpga);
    LOG_INFO("FPGA triggers programmed and acknowledged");

    const auto prompt = afk::dialogue::DialogueSession::MakeSystemPrompt(
        prompt_path, frontend / "kiosk.html");
    if (!prompt) {
        throw std::runtime_error(prompt.error());
    }
    afk::dialogue::CodexBackend agent(*prompt, "codex");

    afk::whisper::WhisperSTT whisper_stt(
        models / "ggml-base.en.bin", models / "ggml-silero-v6.2.0.bin");
    afk::whisper::SpeechWorker speech(whisper_stt);

    afk::dialogue::DialogueSession dialogue(agent, fpga_backend, speech);
    afk::http::DirectoryServer http;
    afk::ws::DialogueServer websocket(dialogue, host, ws_port);
    http.start(frontend, host, http_port);
    websocket.Start();
    LOG_INFO("Frontend: http://{}:{}/kiosk.html", host, http_port);
    LOG_INFO("WebSocket: ws://{}:{}/ws", host, ws_port);
    LOG_INFO("AFK ready");
    while (!stop_requested) {
        dialogue.Poll(afk::dialogue::Clock::now());
        std::this_thread::sleep_for(std::chrono::milliseconds(10));
    }
    websocket.Stop();
    http.stop();
    // Speech joins before whisper_stt destruction; Codex and serial resources
    // are released after all network producers have stopped.
    return 0;
}
