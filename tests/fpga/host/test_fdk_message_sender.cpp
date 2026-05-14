#include <catch2/catch_all.hpp>

#include <fdk/fpga/message/MessageSender.h>

#include <algorithm>
#include <cstddef>
#include <cstdint>
#include <expected>
#include <optional>
#include <type_traits>

namespace {

using namespace fdk::fpga;

struct HeaderOnlyMessage {
    static constexpr std::uint16_t MSG_TYPE = 0xA5B6;
};

template <typename Payload>
struct RecordingChannelSender {
    std::uint8_t channel = 0;
    std::optional<Message<Payload>> message;
    std::size_t calls = 0;
    std::expected<void, SendError> result;

    template <typename T>
    std::expected<void, SendError> send(std::uint8_t channel_id, T const& value) {
        static_assert(std::is_same_v<T, Message<Payload>>);
        channel = channel_id;
        message = value;
        ++calls;
        return result;
    }
};

static_assert(sizeof(Message<HeaderOnlyMessage>) == sizeof(MsgHeader));

} // namespace

TEMPLATE_TEST_CASE("MessageSender passes the typed message to its channel sender", "[message][sender]",
                   EchoRequest, EchoResponse, HeaderOnlyMessage)
{
    static_assert(ChannelSenderLike<RecordingChannelSender<TestType>>);
    TestType payload{};
    if constexpr (!std::is_empty_v<TestType>) {
        std::size_t i = 0;
        for (auto& byte : payload.payload) {
            byte = static_cast<std::byte>(++i);
        }
    }
    RecordingChannelSender<TestType> channel_sender;
    const MessageSender message_sender{channel_sender};
    static_assert(MessageSenderLike<decltype(message_sender)>);
    const auto channel = static_cast<std::uint8_t>(GENERATE(0, 9, 255));

    SECTION("Success is returned") {}
    SECTION("Channel errors are returned") {
        channel_sender.result = std::unexpected(GENERATE(SendError::Disconnected, SendError::SysWriteError));
    }

    const auto result = message_sender.send(channel, 0x12345678, 0x90ABCDEF, payload);
    static_assert(std::is_same_v<decltype(result), const std::expected<void, SendError>>);
    CHECK(result == channel_sender.result);
    REQUIRE(channel_sender.calls == 1);
    CHECK(channel_sender.channel == channel);
    REQUIRE(channel_sender.message);
    const auto& message = *channel_sender.message;
    CHECK(message.msg_hdr.msg_size == sizeof(Message<TestType>));
    CHECK(message.msg_hdr.seq == 0x12345678);
    CHECK(message.msg_hdr.ack_seq == 0x90ABCDEF);
    CHECK(message.msg_hdr.msg_type == TestType::MSG_TYPE);
    if constexpr (!std::is_empty_v<TestType>) {
        CHECK(std::ranges::equal(message.msg.payload, payload.payload));
    }
}
