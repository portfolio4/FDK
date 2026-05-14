#include <fdk/fpga/channel/ChannelReceiver.h>
#include <fdk/fpga/channel/ChannelSender.h>
#include <fdk/fpga/message/MessageReader.h>
#include <fdk/fpga/message/MessageReceiver.h>
#include <fdk/fpga/message/MessageSender.h>
#include <fdk/fpga/uart/UartReceiver.h>
#include <fdk/fpga/uart/UartSender.h>

#include <algorithm>
#include <chrono>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <format>
#include <iostream>
#include <print>
#include <stdexcept>
#include <string>
#include <thread>

static int run(int serial_fd) {
    constexpr std::uint8_t ECHO_CHANNEL_ID = 5;
    fdk::fpga::UartReceiver uart_receiver(serial_fd);
    fdk::fpga::UartSender uart_sender(serial_fd);
    fdk::fpga::ChannelSender channel_sender{uart_sender};
    fdk::fpga::MessageSender message_sender{channel_sender};
    fdk::fpga::ChannelReceiver channel_receiver{uart_receiver};
    fdk::fpga::MessageReceiver message_receiver{channel_receiver};
    fdk::fpga::MessageReader message_reader{message_receiver};
    static_assert(sizeof(fdk::fpga::Message<fdk::fpga::EchoRequest>) == 140);
    static_assert(sizeof(fdk::fpga::Message<fdk::fpga::EchoResponse>) == 140);

    std::uint32_t send_seq = 0;
    for (std::uint64_t i = 0; ; ++i) {
        const auto next_send = std::chrono::steady_clock::now() + std::chrono::seconds(1);
        const std::string greeting = std::format("Hello World {}!", i);
        fdk::fpga::EchoRequest request{};
        std::memcpy(request.payload, greeting.data(), greeting.size());
        const auto sent = message_sender.send(ECHO_CHANNEL_ID, send_seq, 0, request);
        if (!sent) {
            throw std::runtime_error(std::format("UART send failed: {}", static_cast<int>(sent.error())));
        }

        const auto on_message = [&](const fdk::fpga::MessageView<fdk::fpga::EchoResponse>& view) {
            const auto response_channel = view.metadata.channel_id;
            const auto& response = *view.message;
            if (response_channel != ECHO_CHANNEL_ID) {
                throw std::runtime_error("Unexpected echo response channel");
            }
            if (response.msg_hdr.ack_seq != send_seq ||
                !std::equal(std::begin(request.payload), std::end(request.payload),
                            std::begin(response.msg.payload))) {
                throw std::runtime_error("Echo response acknowledgment or data did not match");
            }
            const auto response_seq = response.msg_hdr.seq;
            const auto response_ack_seq = response.msg_hdr.ack_seq;
            const auto* reinterpreted_payload = reinterpret_cast<const char*>(response.msg.payload);
            const std::string echo_resp_msg(
                reinterpreted_payload, strnlen(reinterpreted_payload, sizeof(response.msg.payload)));
            std::println("EchoResponse channel={} seq={} ack={}: {}",
                         response_channel, response_seq, response_ack_seq, echo_resp_msg);
            std::fflush(stdout);
        };
        if (!message_reader.try_read_for<fdk::fpga::EchoResponse>(ECHO_CHANNEL_ID, on_message, std::chrono::seconds(5))) {
            throw std::runtime_error("Timed out waiting for EchoResponse");
        }
        send_seq += sizeof(fdk::fpga::Message<fdk::fpga::EchoRequest>);
        std::this_thread::sleep_until(next_send);
    }
}

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
    int result;
    try {
        result = run(serial_fd);
    } catch (const std::exception& error) {
        std::cerr << error.what() << '\n';
        result = 1;
    }
    close(serial_fd);
    return result;
}
