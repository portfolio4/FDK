#pragma once

#include <fdk/fpga/Errors.h>
#include <fdk/fpga/uart/UartConfig.h>

#include <array>
#include <cerrno>
#include <cstddef>
#include <cstring>
#include <expected>
#include <fcntl.h>
#include <poll.h>
#include <span>
#include <stdexcept>
#include <system_error>
#include <termios.h>
#include <unistd.h>

namespace fdk::fpga {

// POSIX UART receiver. Borrows serial_fd; the caller owns and closes it.
// Configures raw 8N1 with no flow control and nonblocking reads. Pass a numeric
// baud rate (for example, 115200). Use from one thread. Requires C++23.
class UartReceiver {
public:
    static constexpr std::size_t BUFFER_SIZE = 4096;

    explicit UartReceiver(int serial_fd, int baud_rate = 115200) : serial_fd_(serial_fd) {
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

    UartReceiver(const UartReceiver&) = delete;
    UartReceiver& operator=(const UartReceiver&) = delete;
    UartReceiver(UartReceiver&&) = delete;
    UartReceiver& operator=(UartReceiver&&) = delete;

    // Append available bytes until the buffer is full or no more data is ready.
    // Never waits for data. A full buffer is left intact until consume().
    std::expected<void, ReceiveError> poll() {
        while (buffer_size_ < BUFFER_SIZE) {
            pollfd port{serial_fd_, POLLIN, 0};
            if (::poll(&port, 1, 0) < 0) {
                if (errno == EINTR) {
                    return {};
                }
                return std::unexpected(ReceiveError::SysPollError);
            }
            if (port.revents & POLLIN) {
                const ssize_t count = ::read(serial_fd_, buffer_.data() + buffer_size_,
                                             BUFFER_SIZE - buffer_size_);
                if (count > 0) {
                    buffer_size_ += static_cast<std::size_t>(count);
                    continue;
                }
                if (count < 0 && errno != EINTR && errno != EAGAIN && errno != EWOULDBLOCK) {
                    return std::unexpected(ReceiveError::SysReadError);
                }
            }
            if (port.revents & (POLLERR | POLLHUP | POLLNVAL)) {
                return std::unexpected(ReceiveError::Disconnected);
            }
            return {};
        }
        return {};
    }

    // The returned view is valid until the next poll() or consume().
    std::span<const std::byte> peek() const {
        return {buffer_.data(), buffer_size_};
    }

    void consume(std::size_t count) {
        if (count > buffer_size_) {
            throw std::out_of_range("Cannot consume more UART bytes than buffered");
        }
        buffer_size_ -= count;
        std::memmove(buffer_.data(), buffer_.data() + count, buffer_size_);
    }

private:
    int serial_fd_;
    std::array<std::byte, BUFFER_SIZE> buffer_;
    std::size_t buffer_size_ = 0;

    [[noreturn]] static void fail(const char* operation) {
        throw std::system_error(errno, std::generic_category(), operation);
    }

};

} // namespace fdk::fpga
