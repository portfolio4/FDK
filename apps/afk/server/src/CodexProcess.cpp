#include <afk/codex/CodexProcess.h>

#include <boost/asio/read_until.hpp>
#include <boost/asio/use_future.hpp>
#include <boost/asio/write.hpp>
#include <nlohmann/json.hpp>

#include <cerrno>
#include <chrono>
#include <csignal>
#include <cstring>
#include <experimental/scope>
#include <format>
#include <spawn.h>
#include <sys/socket.h>
#include <sys/wait.h>
#include <thread>
#include <unistd.h>
#include <vector>

extern char** environ;

namespace afk::codex {

namespace {

boost::asio::io_context MakeIoContext() {
    // Boost 1.87 checks errno after parsing its configuration without clearing
    // it first. Ignore stale ERANGE left by earlier work such as model loading.
    errno = 0;
    return boost::asio::io_context{};
}

} // namespace

CodexProcess::CodexProcess(std::string system_prompt, std::string executable_path)
    : executable(std::move(executable_path)), prompt(std::move(system_prompt)), io(MakeIoContext()) {}

CodexProcess::~CodexProcess() {
    (void)Stop();
}

std::expected<void, std::string> CodexProcess::Start() {
    if (std::get_if<Running>(&state) != nullptr) {
        return {};
    }

    io.restart();
    boost::asio::local::stream_protocol::socket socket(io), child(io);

    std::vector<std::string> arguments{executable, "app-server", "--stdio",
        "--disable", "shell_tool", "--disable", "apps", "--disable", "browser_use", "--disable", "view_image",
        "-c", "web_search=\"disabled\"", "-c", std::format("developer_instructions={}", nlohmann::json(prompt).dump())};

    std::vector<char*> argv;
    for (auto& argument : arguments) {
        argv.push_back(argument.data());
    }

    argv.push_back(nullptr);

    int descriptors[2];
    if (socketpair(AF_UNIX, SOCK_STREAM | SOCK_CLOEXEC, 0, descriptors) != 0) {
        return std::unexpected(std::format("Cannot create Codex socket pair: {}", std::strerror(errno)));
    }

    const std::experimental::scope_exit close_descriptors([&] {
        for (const int descriptor : descriptors) {
            if (descriptor != -1) {
                close(descriptor);
            }
        }
    });

    boost::system::error_code ec;
    socket.assign(boost::asio::local::stream_protocol(), descriptors[0], ec);
    if (ec) {
        return std::unexpected(std::format("Cannot assign Codex socket: {}", ec.message()));
    }

    descriptors[0] = -1;

    child.assign(boost::asio::local::stream_protocol(), descriptors[1], ec);
    if (ec) {
        return std::unexpected(std::format("Cannot assign Codex child socket: {}", ec.message()));
    }

    descriptors[1] = -1;

    posix_spawn_file_actions_t actions;
    int error = posix_spawn_file_actions_init(&actions);
    if (error != 0) {
        return std::unexpected(std::format("Cannot initialize Codex spawn actions: {}", std::strerror(error)));
    }

    const std::experimental::scope_exit destroy_actions([&] {
        posix_spawn_file_actions_destroy(&actions);
    });

    error = posix_spawn_file_actions_adddup2(&actions, child.native_handle(), STDIN_FILENO);
    if (error == 0) {
        error = posix_spawn_file_actions_adddup2(&actions, child.native_handle(), STDOUT_FILENO);
    }

    if (error == 0) {
        // This backend targets Linux/glibc, which provides closefrom spawn actions.
        error = posix_spawn_file_actions_addclosefrom_np(&actions, 3);
    }

    pid_t process = -1;
    if (error == 0) {
        error = posix_spawnp(&process, executable.c_str(), &actions, nullptr, argv.data(), environ);
    }

    if (error != 0) {
        return std::unexpected(std::format("Cannot launch Codex: {}", std::strerror(error)));
    }

    state.emplace<Running>(process, std::move(socket));
    return {};
}

std::expected<void, std::string> CodexProcess::Stop() {
    auto* running = std::get_if<Running>(&state);
    if (running == nullptr) {
        return {};
    }

    running->stopping = true;
    boost::system::error_code ec;
    running->socket.cancel(ec);
    io.restart();
    io.poll();

    // Signal stdin EOF, retaining the read endpoint until the child exits.
    running->socket.shutdown(boost::asio::socket_base::shutdown_send, ec);
    if (kill(running->process, SIGTERM) != 0 && errno != ESRCH) {
        return std::unexpected(std::format("Cannot stop Codex: {}", std::strerror(errno)));
    }

    bool exited = false;
    for (int attempt = 0; attempt < 20; ++attempt) {
        const auto reaped = waitpid(running->process, nullptr, WNOHANG);
        if (reaped == running->process || (reaped < 0 && errno == ECHILD)) {
            exited = true;
            break;
        }

        if (reaped < 0 && errno != EINTR) {
            return std::unexpected(std::format("Cannot reap Codex: {}", std::strerror(errno)));
        }

        std::this_thread::sleep_for(std::chrono::milliseconds(10));
    }

    if (!exited) {
        if (kill(running->process, SIGKILL) != 0 && errno != ESRCH) {
            return std::unexpected(std::format("Cannot kill Codex: {}", std::strerror(errno)));
        }

        pid_t reaped;
        do {
            reaped = waitpid(running->process, nullptr, 0);
        } while (reaped < 0 && errno == EINTR);

        if (reaped < 0 && errno != ECHILD) {
            return std::unexpected(std::format("Cannot reap Codex: {}", std::strerror(errno)));
        }
    }

    // Drain cancelled handlers before releasing buffers or reusing the context.
    running->socket.close(ec);
    io.restart();
    io.poll();

    state.emplace<Stopped>();
    return {};
}

std::expected<void, std::string> CodexProcess::Send(const std::string& request) {
    if (request.empty()) {
        return std::unexpected("Codex request should not be empty.");
    }

    auto* running = std::get_if<Running>(&state);
    if (running == nullptr) {
        return std::unexpected("Codex is stopped.");
    }

    PollIo();
    if (running->write_error) {
        return std::unexpected(std::format("Cannot write to Codex: {}", running->write_error.message()));
    }

    if (request.size() >= MAX_PENDING_BYTES) {
        return std::unexpected("Codex request exceeds the pending byte limit.");
    }

    const auto message = nlohmann::json::parse(request, nullptr, false);

    // Compact valid JSON so each request occupies exactly one protocol line.
    auto outgoing = message.is_discarded() ? request : message.dump();
    if (outgoing.find_first_of("\r\n") != std::string::npos) {
        return std::unexpected("Codex request must occupy one protocol line.");
    }

    outgoing += '\n';
    if (outgoing.size() > MAX_PENDING_BYTES - running->pending_bytes) {
        return std::unexpected("Codex pending write queue is full.");
    }

    const bool idle = running->outgoing.empty();
    running->pending_bytes += outgoing.size();
    running->outgoing.push_back(std::move(outgoing));
    if (idle) WriteNext(*running);

    PollIo();
    if (running->write_error) {
        return std::unexpected(std::format("Cannot write to Codex: {}", running->write_error.message()));
    }

    return {};
}

std::expected<std::optional<std::string>, std::string> CodexProcess::PollResponse() {
    auto* running = std::get_if<Running>(&state);
    if (running == nullptr) {
        return std::unexpected("Codex is stopped.");
    }

    if (!running->future_response.valid()) {
        CreateAsyncRead(*running);
    }

    PollIo();
    if (running->write_error) {
        return std::unexpected(std::format("Cannot write to Codex: {}", running->write_error.message()));
    }

    if (running->future_response.wait_for(std::chrono::seconds(0)) != std::future_status::ready) {
        return std::optional<std::string>{};
    }

    // Asio exceptions propagate through the future instead of being rewritten.
    const auto count = running->future_response.get();
    auto response = running->buffered.substr(0, count - 1);
    running->buffered.erase(0, count);
    return std::optional<std::string>{std::move(response)};
}

void CodexProcess::CreateAsyncRead(Running& running) {
    running.future_response = boost::asio::async_read_until(running.socket,
        boost::asio::dynamic_buffer(running.buffered, MAX_RESPONSE_BYTES), '\n', boost::asio::use_future);
}

void CodexProcess::WriteNext(Running& running) {
    boost::asio::async_write(running.socket, boost::asio::buffer(running.outgoing.front()),
        [&running](boost::system::error_code error, std::size_t) {
            if (error || running.stopping) {
                running.write_error = error;
                running.outgoing.clear();
                running.pending_bytes = 0;
                return;
            }

            running.pending_bytes -= running.outgoing.front().size();
            running.outgoing.pop_front();

            if (!running.outgoing.empty()) WriteNext(running);
        });
}

void CodexProcess::PollIo() {
    io.restart();
    for (int count = 0; count < 32; ++count) {
        if (io.poll_one() == 0) break;
    }
}

} // namespace afk::codex
