#pragma once

#include <afk/codex/CodexAgent.h>

#include <cstdint>
#include <optional>
#include <string>

namespace afk { class ThreadSafeAfkFpga; }

namespace afk::dialogue {

struct Reaction {
    std::uint64_t request_id;
    std::string text;
};

class AgentBackend {
public:
    virtual ~AgentBackend() = default;

    virtual bool Send(std::uint64_t request_id, const std::string& text) = 0;

    virtual std::optional<codex::CodexAgent::Response> Poll() = 0;

    // Forget the current request without restarting the agent.
    virtual void DiscardPendingResponse() = 0;
};

class FpgaBackend {
public:
    virtual ~FpgaBackend() = default;

    virtual bool Send(std::uint64_t request_id, const std::string& text) = 0;
    virtual std::optional<Reaction> Poll() = 0;
};

struct Transcription {
    std::string session;
    std::string tentative;
    std::string committed;
};

// Commands enqueue work and return; Poll retrieves completed transcriptions.
// Treat session strings as opaque tokens and return them with transcriptions.
class SpeechBackend {
public:
    virtual ~SpeechBackend() = default;

    virtual void Audio(const std::string& session, const std::string& bytes) = 0;
    virtual std::optional<Transcription> Poll() = 0;

    // Clear transcription state when the connection or customer changes.
    virtual void Reset(const std::string& session) = 0;
};

// Constructs and owns the agent for the lifetime of the backend.
class CodexBackend final : public AgentBackend {
public:
    explicit CodexBackend(std::string system_prompt, std::string executable = "codex");

    bool Send(std::uint64_t request_id, const std::string& text) override;
    std::optional<codex::CodexAgent::Response> Poll() override;
    void DiscardPendingResponse() override;

private:
    codex::CodexAgent agent_;
};

// The shared FPGA must outlive this adapter.
class AfkFpgaBackend final : public FpgaBackend {
public:
    explicit AfkFpgaBackend(ThreadSafeAfkFpga& fpga);

    bool Send(std::uint64_t request_id, const std::string& text) override;
    std::optional<Reaction> Poll() override;

private:
    ThreadSafeAfkFpga& fpga_;
};

} // namespace afk::dialogue
