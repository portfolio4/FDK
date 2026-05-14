#pragma once

#include <afk/fpga/Channel.h>
#include <afk/fpga/Message.h>

#include <fdk/ErrorText.h>
#include <fdk/Reflection.h>
#include <fdk/fpga/Errors.h>
#include <fdk/fpga/channel/ChannelReceiver.h>
#include <fdk/fpga/channel/ChannelSender.h>
#include <fdk/fpga/message/MessageReader.h>
#include <fdk/fpga/message/MessageReceiver.h>
#include <fdk/fpga/message/MessageSender.h>
#include <fdk/fpga/platform/basys3.h>
#include <fdk/fpga/uart/UartReceiver.h>
#include <fdk/fpga/uart/UartSender.h>

#include <cerrno>
#include <chrono>
#include <cstdint>
#include <cstring>
#include <expected>
#include <fcntl.h>
#include <limits>
#include <memory>
#include <span>
#include <string_view>
#include <system_error>
#include <unistd.h>
#include <utility>
#include <vector>

namespace afk {

// Note: not thread safe
class AfkFpga {
public:
    explicit AfkFpga(const char* device_path, int baud_rate = fdk::fpga::platform::BAUD_RATE)
        : port_(device_path)
        , uart_receiver_(port_.fd, baud_rate)
        , uart_sender_(port_.fd, baud_rate)
    {}

    // Waits up to one second for the matching response.
    [[nodiscard]] std::expected<void, fdk::ErrorText> echo_request(
        std::uint8_t channel_id, std::string_view greeting) {
        fdk::fpga::EchoRequest request{};
        if (greeting.size() > sizeof(request.payload)) {
            return std::unexpected(fdk::ErrorText::format(
                "Echo greeting too long: {} bytes (max {})",
                greeting.size(), sizeof(request.payload)));
        }
        if (!greeting.empty()) {
            std::memcpy(request.payload, greeting.data(), greeting.size());
        }
        return send_request_and_wait_for_response<fdk::fpga::EchoResponse>(channel_id, request);
    }

    [[nodiscard]] std::expected<void, fdk::ErrorText> test_request(std::uint8_t channel_id) {
        return send_request_and_wait_for_response<Ack>(channel_id, TestRequest{});
    }

    [[nodiscard]] std::expected<void, fdk::ErrorText> program_reaction(ProgramReaction const& reaction) {
        return send_request_and_wait_for_response<Ack>(channels::PROGRAM_ACTIONS, reaction);
    }

    [[nodiscard]] std::expected<void, fdk::ErrorText> program_condition(ProgramCondition const& condition) {
        return send_request_and_wait_for_response<Ack>(channels::PROGRAM_ACTIONS, condition);
    }

    [[nodiscard]] std::expected<void, fdk::ErrorText> disable_condition(DisableCondition const& condition) {
        return send_request_and_wait_for_response<Ack>(channels::PROGRAM_ACTIONS, condition);
    }

    [[nodiscard]] std::expected<void, fdk::ErrorText> send_stimulus(std::uint64_t request_id, std::string_view payload) {
        if (payload.size() > std::numeric_limits<std::uint16_t>::max()) {
            return std::unexpected(fdk::ErrorText::format(
                "Stimulus too long: {} bytes (max {})",
                payload.size(), std::numeric_limits<std::uint16_t>::max()));
        }
        const Stimulus header{
            .request_id = request_id,
            .length = static_cast<std::uint16_t>(payload.size()),
        };
        std::vector<std::byte> bytes(sizeof(header) + payload.size());
        std::memcpy(bytes.data(), &header, sizeof(header));
        if (!payload.empty()) {
            std::memcpy(bytes.data() + sizeof(header), payload.data(), payload.size());
        }
        const auto sent = channel_sender_.send(channels::TRIGGER, std::span<const std::byte>{bytes});
        if (!sent) {
            return std::unexpected(fdk::ErrorText::format(
                "UART {}: ch={} Stimulus request_id={}",
                sent.error() == fdk::fpga::SendError::Disconnected
                    ? "disconnected" : "write/poll failed",
                channels::TRIGGER, request_id));
        }
        return {};
    }

    // Callback receives const Reaction& backed by the receive buffer. Access
    // reaction_len bytes through payload; the reference is valid only during
    // the callback.
    //
    // A zero timeout attempts one nonblocking read, including
    // polling the UART once if no queued reaction is available.
    template <typename CallbackFn>
    bool try_read_reaction_for(CallbackFn&& callback, std::chrono::nanoseconds timeout) {
        const auto deadline = std::chrono::steady_clock::now() + timeout;
        const auto try_read = [&] {
            while (const auto packet = channel_receiver_.peek(channels::TRIGGER)) {
                if (packet->payload.size() >= sizeof(Reaction)) {
                    Reaction header{};
                    std::memcpy(&header, packet->payload.data(), sizeof(header));
                    const Reaction expected_header{};
                    if (std::memcmp(header.preamble, expected_header.preamble, sizeof(header.preamble)) == 0 &&
                        header.start_frame_delimiter == expected_header.start_frame_delimiter &&
                        header.reaction_len <= MAX_REACTION_PAYLOAD_SIZE &&
                        packet->payload.size() >= sizeof(header) + header.reaction_len) {
                        callback(*std::start_lifetime_as<Reaction>(packet->payload.data()));
                        channel_receiver_.consume(channels::TRIGGER);
                        return true;
                    }
                }
                channel_receiver_.consume(channels::TRIGGER);
            }
            return false;
        };
        do {
            if (try_read()) {
                return true;
            }
            if (!channel_receiver_.poll()) {
                return false;
            }
            if (try_read()) {
                return true;
            }
        } while (std::chrono::steady_clock::now() < deadline);
        return false;
    }

private:
    // Polls for one matching message without waiting. Partial
    // messages remain buffered for the next call; unknown types are consumed.
    template <fdk::fpga::MessageLike... Ts, typename CallbackFn>
        requires (sizeof...(Ts) > 0)
    bool poll_message(std::uint8_t channel_id, CallbackFn&& callback) {
        return message_reader_.try_read_for<Ts...>(
            channel_id, std::forward<CallbackFn>(callback), std::chrono::seconds(0));
    }

    template <fdk::fpga::MessageLike T>
    std::expected<std::uint32_t, fdk::ErrorText> send_request(std::uint8_t channel_id, const T& payload) {
        const auto sent = message_sender_.send(channel_id, send_seq_, 0, payload);
        if (!sent) {
            return std::unexpected(fdk::ErrorText::format(
                "UART {}: ch={} type={} seq={}",
                sent.error() == fdk::fpga::SendError::Disconnected
                    ? "disconnected" : "write/poll failed",
                channel_id, T::MSG_TYPE, send_seq_));
        }
        const auto sequence = send_seq_;
        send_seq_ += sizeof(fdk::fpga::Message<T>);
        return sequence;
    }

    template <fdk::fpga::MessageLike Response, fdk::fpga::MessageLike T>
    std::expected<void, fdk::ErrorText> send_request_and_wait_for_response(
        std::uint8_t channel_id, const T& payload,
        std::chrono::nanoseconds timeout = std::chrono::seconds(1))
    {
        const auto sequence = send_request(channel_id, payload);
        if (!sequence) {
            return std::unexpected(sequence.error());
        }
        const auto deadline = std::chrono::steady_clock::now() + timeout;
        bool received = false;
        const auto on_response = [&](const fdk::fpga::MessageView<Response>& view) {
            received = view.message->msg_hdr.ack_seq == *sequence;
        };
        do {
            if (poll_message<Response>(channel_id, on_response) && received) {
                return {};
            }
        } while (std::chrono::steady_clock::now() < deadline);
        return std::unexpected(fdk::ErrorText::format(
            "No {} received: ch={} type={} seq={}", fdk::runtime_type_name<Response>(), channel_id, T::MSG_TYPE, *sequence));
    }

    struct SerialPort {
        explicit SerialPort(const char* device_path)
            : fd(::open(device_path, O_RDWR | O_NOCTTY | O_NONBLOCK)) {
            if (fd < 0) {
                throw std::system_error(errno, std::generic_category(), "open");
            }
        }
        ~SerialPort() { ::close(fd); }
        SerialPort(const SerialPort&) = delete;
        SerialPort& operator=(const SerialPort&) = delete;

        int fd;
    };

    SerialPort port_;
    fdk::fpga::UartReceiver uart_receiver_;
    fdk::fpga::UartSender uart_sender_;
    fdk::fpga::ChannelReceiver<fdk::fpga::UartReceiver> channel_receiver_{uart_receiver_};
    fdk::fpga::ChannelSender<fdk::fpga::UartSender> channel_sender_{uart_sender_};
    fdk::fpga::MessageReceiver<decltype(channel_receiver_)> message_receiver_{channel_receiver_};
    fdk::fpga::MessageSender<decltype(channel_sender_)> message_sender_{channel_sender_};
    fdk::fpga::MessageReader<decltype(message_receiver_)> message_reader_{message_receiver_};
    std::uint32_t send_seq_ = 0;
};

} // namespace afk
