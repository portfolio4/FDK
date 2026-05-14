#include <fdk/fpga/uart/UartReceiver.h>
#include <fdk/fpga/uart/UartSender.h>

#include <chrono>
#include <iostream>
#include <string>
#include <thread>

int main(int argc, char* argv[]) {
    if (argc != 2) {
        std::cerr << "Usage: " << argv[0] << " <serial-device>\n";
        return 1;
    }
    const int serial_fd = open(argv[1], O_RDWR | O_NOCTTY | O_NONBLOCK);
    if (serial_fd < 0) {
        std::cerr << std::system_error(errno, std::generic_category(), "open").what() << '\n';
        return 1;
    }
    fdk::fpga::UartReceiver receiver(serial_fd);
    fdk::fpga::UartSender sender(serial_fd);
    const std::string message = "Hello world!";
    while (true) {
        for (std::byte byte : std::as_bytes(std::span(message))) {
            auto result = sender.send(std::span<const std::byte>(&byte, 1));
            if (!result) {
                std::cerr << "Send failed, error code = "
                          << static_cast<int>(result.error()) << std::endl;
                close(serial_fd);
                return 1;
            }
            std::cout << "Sent: " << std::to_integer<char>(byte) << std::endl;
        }
        std::size_t received = 0;
        while (received < message.size()) {
            auto result = receiver.poll();
            if (!result) {
                std::cerr << "Receive/poll failed, error code = "
                          << static_cast<int>(result.error()) << std::endl;
                close(serial_fd);
                return 1;
            }
            const auto bytes = receiver.peek();
            if (bytes.empty()) {
                std::this_thread::sleep_for(std::chrono::milliseconds(1));
                continue;
            }
            for (std::byte byte : bytes) {
                std::cout << "Received: " << std::to_integer<char>(byte) << std::endl;
            }
            received += bytes.size();
            receiver.consume(bytes.size());
        }
        std::this_thread::sleep_for(std::chrono::seconds(1));
    }
}
