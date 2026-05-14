#include <afk/http/DirectoryServer.h>

#include <format>
#include <stdexcept>
#include <sys/socket.h>

namespace afk::http {

DirectoryServer::DirectoryServer() {
    server_.Get("/", [](const httplib::Request&, httplib::Response& response) {
        response.set_redirect("/kiosk.html");
    });

    server_.set_read_timeout(10, 0);
    server_.set_write_timeout(10, 0);

    // Permit restarts without allowing multiple listeners to share the port.
    server_.set_socket_options([](socket_t socket) {
        int reuse = 1;
        ::setsockopt(socket, SOL_SOCKET, SO_REUSEADDR, &reuse, sizeof(reuse));
    });
}

DirectoryServer::~DirectoryServer() {
    stop();
}

int DirectoryServer::start(const std::filesystem::path& directory, const std::string& host, int port) {
    if (listener_.joinable()) {
        throw std::logic_error("HTTP server is already started");
    }

    if (port < 0 || port > 65535) {
        throw std::invalid_argument("Invalid HTTP port");
    }

    // Clear any decommissioned state left by a previous listener failure.
    server_.stop();
    server_.remove_mount_point("/");
    if (!server_.set_mount_point("/", directory.string())) {
        throw std::runtime_error(std::format("Cannot serve frontend directory: {}", directory.string()));
    }

    const int bound_port = (port == 0)
        ? server_.bind_to_any_port(host)
        : (server_.bind_to_port(host, port) ? port : -1);
    if (bound_port < 0) {
        server_.stop();
        throw std::runtime_error(std::format("Cannot bind HTTP server to {}:{}", host, port));
    }

    failure_ = nullptr;
    listener_ = std::jthread([this] {
        try {
            if (!server_.listen_after_bind()) {
                throw std::runtime_error("HTTP listener failed");
            }
        } catch (...) {
            failure_ = std::current_exception();
            server_.decommission();
        }
    });

    server_.wait_until_ready();
    if (!server_.is_running()) {
        stop();
        if (failure_) std::rethrow_exception(failure_);
        throw std::runtime_error("HTTP listener stopped during startup");
    }

    return bound_port;
}

void DirectoryServer::stop() {
    server_.stop();
    if (listener_.joinable()) listener_.join();
}

bool DirectoryServer::is_running() const {
    return server_.is_running();
}

} // namespace afk::http
