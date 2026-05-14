#pragma once

#include <afk/codex/CodexProcess.h>

#include <nlohmann/json.hpp>

#include <chrono>
#include <cstdint>
#include <expected>
#include <optional>
#include <string>

namespace afk::codex {

// Single-owner conversation adapter; call its methods from one thread.
// Construction starts Codex and blocks until protocol initialization completes.
//
// Call SendRequest(request_id, text), then repeatedly call PollResponse().
// A successful empty optional means no message is ready yet. Consume each
// returned Response, keeping the request active while turn_completed is false.
// Keep polling until turn_completed is true, even after receiving assistant text;
// that completion event may have no text. Alternatively, DiscardPendingResponse()
// releases the pending request immediately without cancelling the Codex turn.
// Notifications are ignored until the matching RPC reply supplies a turn ID;
// afterward, only notifications with that turn ID are accepted.
//
// PollResponse reports errors through std::expected. A rejected turn/start or a
// failed/interrupted turn completion ends the request with an error instead of a
// completion Response. Runtime error notifications leave the turn active, so
// continue polling for its completion. Malformed protocol fields also return
// errors without clearing the pending request.
// Transport read exceptions propagate from CodexProcess unchanged.
class CodexAgent {
public:
    explicit CodexAgent(std::string system_prompt, std::string executable = "codex");

    CodexAgent(const CodexAgent&) = delete;
    CodexAgent& operator=(const CodexAgent&) = delete;
    CodexAgent(CodexAgent&&) = delete;
    CodexAgent& operator=(CodexAgent&&) = delete;

    struct Response {
        std::uint64_t request_id;
        std::string response;

        // Completion events may have no response text.
        bool turn_completed = false;
    };

    // request_id is also the JSON-RPC ID; use a distinct ID for each request.
    // A previous turn must finish or be discarded before another send.
    std::expected<void, std::string> SendRequest(std::uint64_t request_id, const std::string& request);

    // Inspect this while draining a losing turn. Discard only clears local
    // tracking; it neither cancels nor waits for that turn to finish.
    [[nodiscard]] bool HasPendingRequest() const noexcept { return pending_.has_value(); }

    void DiscardPendingResponse();

    // Does not wait for inference; returns at most one message or completion event.
    std::expected<std::optional<Response>, std::string> PollResponse();

private:
    using Json = nlohmann::json;
    using Clock = std::chrono::steady_clock;

    struct Pending {
        std::uint64_t request_id;
        std::string turn_id;
    };

    std::expected<Json, std::string> BlockingInitializationRpc(Json request);

    CodexProcess process_;
    std::string thread_id_;
    int next_id_ = 1;
    std::optional<Pending> pending_;
};

} // namespace afk::codex
