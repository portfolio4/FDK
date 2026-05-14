#pragma once

#include <afk/dialogue/Backends.h>

#include <chrono>
#include <cstdint>
#include <deque>
#include <expected>
#include <filesystem>
#include <mutex>
#include <optional>
#include <string>

namespace afk::dialogue {

using Clock = std::chrono::steady_clock;
using Time = Clock::time_point;

class Client {
public:
    virtual ~Client() = default;

    virtual void Send(const std::string& text) = 0;
    virtual void Close(std::uint16_t code, const std::string& reason) = 0;
};

struct Options {
    Clock::duration pause_interval = std::chrono::seconds(2);
    std::size_t max_queued_requests = 8;
};

// Shared by IX connection callbacks and a periodic Poll caller. A single mutex
// serializes dialogue state and all agent access. Callbacks run under that mutex
// and must not reenter the session. Stop external producers before destruction.
class DialogueSession {
public:
    // Backends must outlive the session and be accessed through it.
    DialogueSession(AgentBackend& agent, FpgaBackend& fpga,
                    SpeechBackend& speech, Options options = {});

    // The client is borrowed and must remain alive until Close() returns.
    std::expected<void, std::string> Open(std::string connection_id, Client* client);
    void Close(const std::string& connection_id);
    void OnText(const std::string& connection_id, const std::string& text, Time now);
    void OnAudio(const std::string& connection_id, const std::string& bytes);
    // Call periodically even when no messages arrive. Does not wait for replies.
    void Poll(Time now);
    [[nodiscard]] std::optional<std::string> CurrentSession();

    static std::expected<std::string, std::string> MakeSystemPrompt(
        const std::filesystem::path& prompt, const std::filesystem::path& menu);

private:
    struct Request {
        std::uint64_t request_id;
        std::string text;
    };

    std::string Token() const;
    void Send(const nlohmann::json& messages);
    void SendError();
    void FlushTranscript();
    void FinishCustomer();
    void CheckIfRequestCompleted();
    void Reply(const nlohmann::json& messages);
    void PollSpeech(Time now);
    void PollAgent();
    void PollFpga();

    std::mutex mutex_;
    AgentBackend& agent_;
    FpgaBackend& fpga_;
    SpeechBackend& speech_;
    Options options_;
    std::optional<std::string> connection_id_;
    Client* client_ = nullptr;
    std::uint64_t speech_generation_ = 0;
    std::uint64_t next_request_id_ = 1;
    std::string transcript_;
    Time pause_deadline_{};
    std::deque<Request> queued_requests_;
    std::optional<Request> active_request_;
};

} // namespace afk::dialogue
