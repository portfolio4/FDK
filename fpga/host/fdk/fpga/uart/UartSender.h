#pragma once

#include <fdk/fpga/Errors.h>
#include <fdk/fpga/uart/UartConfig.h>

#include <cerrno>
#include <cstddef>
#include <expected>
#include <fcntl.h>
#include <poll.h>
#include <span>
#include <system_error>
#include <termios.h>
#include <unistd.h>

namespace fdk::fpga {

// POSIX UART sender. Borrows serial_fd; the caller owns and closes it.
// Configures raw 8N1 with no flow control and nonblocking I/O, matching
// UartReceiver. Use O_RDWR for duplex operation. Serialize send calls.
// Requires C++23. Constructor setup errors throw exceptions.
class UartSender {
public:
    explicit UartSender(int serial_fd, int baud_rate = 115200) : serial_fd_(serial_fd) {
        const speed_t speed = UartConfig::baud_speed(baud_rate);
        termios settings{};
        if (tcgetattr(serial_fd_, &settings) < 0) {
            fail("tcgetattr");
        }
        cfmakeraw(&settings);
        if (cfsetispeed(&settings, speed) < 0 ||
            cfsetospeed(&settings, speed) < 0) {
            fail("cfsetspeed");
        }
        settings.c_cflag &= ~(CSIZE | PARENB | CSTOPB | CRTSCTS);
        settings.c_cflag |= CS8 | CLOCAL | CREAD;
        settings.c_cc[VMIN] = 0;
        settings.c_cc[VTIME] = 0;
        if (tcsetattr(serial_fd_, TCSANOW, &settings) < 0) {
            fail("tcsetattr");
        }
        const int flags = fcntl(serial_fd_, F_GETFL);
        if (flags < 0) {
            fail("fcntl F_GETFL");
        }
        if (fcntl(serial_fd_, F_SETFL, flags | O_NONBLOCK) < 0) {
            fail("fcntl F_SETFL");
        }
    }

    UartSender(const UartSender&) = delete;
    UartSender& operator=(const UartSender&) = delete;
    UartSender(UartSender&&) = delete;
    UartSender& operator=(UartSender&&) = delete;

    // Sends raw bytes without protocol headers. Blocks until the OS accepts all
    // bytes, not until the FPGA acknowledges them. Empty input succeeds.
    // On error, a prefix may already have been sent; retrying can duplicate it.
    std::expected<void, SendError> send(std::span<const std::byte> bytes) {
        std::size_t sent = 0;
        while (sent < bytes.size()) {
            const ssize_t count = ::write(serial_fd_, bytes.data() + sent, bytes.size() - sent);
            if (count > 0) {
                sent += static_cast<std::size_t>(count);
            } else if (count < 0 && errno == EINTR) {
                continue;
            } else if (count == 0 || errno == EAGAIN || errno == EWOULDBLOCK) {
                auto result = wait_writable();
                if (!result) {
                    return result;
                }
            } else if (errno == EIO || errno == ENODEV || errno == ENXIO || errno == EPIPE) {
                return std::unexpected(SendError::Disconnected);
            } else {
                return std::unexpected(SendError::SysWriteError);
            }
        }
        return {};
    }

private:
    int serial_fd_;

    [[noreturn]] static void fail(const char* operation) {
        throw std::system_error(errno, std::generic_category(), operation);
    }

    std::expected<void, SendError> wait_writable() {
        while (true) {
            pollfd port{serial_fd_, POLLOUT, 0};
            if (::poll(&port, 1, -1) < 0) {
                if (errno == EINTR) {
                    continue;
                }
                return std::unexpected(SendError::SysWriteError);
            }
            if (port.revents & (POLLERR | POLLHUP | POLLNVAL)) {
                return std::unexpected(SendError::Disconnected);
            }
            if (port.revents & POLLOUT) {
                return {};
            }
        }
    }

};

} // namespace fdk::fpga
