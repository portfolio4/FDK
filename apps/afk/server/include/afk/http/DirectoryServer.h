#pragma once

#include <httplib.h>

#include <exception>
#include <filesystem>
#include <string>
#include <thread>

namespace afk::http {

// Owns a static-file HTTP listener and its thread. Control methods are called
// from one thread; request handlers never access FPGA or conversation state.
class DirectoryServer {
public:
    DirectoryServer();
    ~DirectoryServer();
    DirectoryServer(const DirectoryServer&) = delete;
    DirectoryServer& operator=(const DirectoryServer&) = delete;
    DirectoryServer(DirectoryServer&&) = delete;
    DirectoryServer& operator=(DirectoryServer&&) = delete;

    // Returns the bound port once the listener is ready. Port 0 selects an
    // ephemeral port. Throws on startup failure or if already started.
    int start(const std::filesystem::path& directory, const std::string& host, int port);

    // Stops the listener and joins its thread. Safe before start or repeatedly;
    // the server may be started again after stop. Destruction also stops it.
    void stop();

    [[nodiscard]] bool is_running() const;

private:
    httplib::Server server_;
    std::exception_ptr failure_;
    std::jthread listener_;
};

} // namespace afk::http
