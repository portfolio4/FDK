#pragma once

#include <boost/asio/io_context.hpp>
#include <boost/asio/local/stream_protocol.hpp>
#include <boost/system/error_code.hpp>

#include <cstddef>
#include <deque>
#include <expected>
#include <future>
#include <optional>
#include <string>
#include <sys/types.h>
#include <utility>
#include <variant>

namespace afk::codex {

// Single-owner, newline-delimited stdio transport over a Unix socket pair.
// Start/Stop wait for startup/cleanup. Send/PollResponse never wait for replies
// or socket writability; call PollResponse regularly to advance queued writes.
class CodexProcess {
public:
    static constexpr std::size_t MAX_PENDING_BYTES = 1024 * 1024;
    static constexpr std::size_t MAX_RESPONSE_BYTES = 8 * 1024 * 1024;

    explicit CodexProcess(std::string system_prompt, std::string executable = "codex");
    ~CodexProcess();
    CodexProcess(const CodexProcess&) = delete;
    CodexProcess& operator=(const CodexProcess&) = delete;
    CodexProcess(CodexProcess&&) = delete;
    CodexProcess& operator=(CodexProcess&&) = delete;

    std::expected<void, std::string> Start();
    std::expected<void, std::string> Stop();

    // Queue one nonempty line, compacting valid JSON. Success means accepted,
    // not delivered. Reject requests that exceed the bounded pending queue.
    // Write errors are returned here or by a subsequent PollResponse; a prefix
    // may already have been sent. Stop/Start discards failed/pending writes.
    std::expected<void, std::string> Send(const std::string& request);

    // Return at most one complete line without waiting; empty means not ready.
    // As in the original transport, read failures (including EOF, a truncated
    // line, or an oversized line) throw boost::system::system_error.
    std::expected<std::optional<std::string>, std::string> PollResponse();

private:
    using Socket = boost::asio::local::stream_protocol::socket;

    struct Stopped {};

    struct Running {
        Running(pid_t process_id, Socket socket_value)
            : process(process_id), socket(std::move(socket_value)) {}

        pid_t process;
        Socket socket;
        std::string buffered;
        std::future<std::size_t> future_response;
        std::deque<std::string> outgoing;
        std::size_t pending_bytes = 0;
        boost::system::error_code write_error;
        bool stopping = false;
    };

    static void CreateAsyncRead(Running& running);

    static void WriteNext(Running& running);

    void PollIo();

    const std::string executable;
    const std::string prompt;

    // Outlives the socket, buffers, and pending handlers in state.
    boost::asio::io_context io;

    std::variant<Stopped, Running> state{Stopped{}};
};

} // namespace afk::codex
