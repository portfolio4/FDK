#include <afk/dialogue/Backends.h>

#include <afk/fpga/ThreadSafeAfkFpga.h>

#include <chrono>
#include <utility>

namespace afk::dialogue {

CodexBackend::CodexBackend(std::string system_prompt, std::string executable)
    : agent_(std::move(system_prompt), std::move(executable)) {}

bool CodexBackend::Send(std::uint64_t request_id, const std::string& text) {
    return agent_.SendRequest(request_id, text).has_value();
}

std::optional<codex::CodexAgent::Response> CodexBackend::Poll() {
    auto response = agent_.PollResponse();
    return response ? std::move(*response) : std::nullopt;
}

void CodexBackend::DiscardPendingResponse() {
    agent_.DiscardPendingResponse();
}

AfkFpgaBackend::AfkFpgaBackend(ThreadSafeAfkFpga& fpga) : fpga_(fpga) {}

bool AfkFpgaBackend::Send(std::uint64_t request_id, const std::string& text) {
    return fpga_.send_stimulus(request_id, text).has_value();
}

std::optional<Reaction> AfkFpgaBackend::Poll() {
    std::optional<Reaction> reaction;
    (void)fpga_.try_read_reaction_for([&](const afk::Reaction& received) {
        reaction = Reaction{
            .request_id = received.request_id,
            .text = std::string(reinterpret_cast<const char*>(received.payload), received.reaction_len),
        };
    }, std::chrono::nanoseconds(0));
    return reaction;
}

} // namespace afk::dialogue
