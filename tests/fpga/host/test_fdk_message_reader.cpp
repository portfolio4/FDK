#include <catch2/catch_all.hpp>

#include <fdk/fpga/message/MessageReader.h>

#include <array>
#include <chrono>
#include <cstddef>
#include <cstdint>
#include <expected>
#include <optional>
#include <queue>
#include <span>
#include <utility>
#include <vector>

namespace {

using namespace fdk::fpga;

struct FirstMessage {
    static constexpr std::uint16_t MSG_TYPE = 1;
    std::uint32_t value;
};

struct SecondMessage {
    static constexpr std::uint16_t MSG_TYPE = 2;
    std::uint16_t value;
};

struct HeaderOnlyMessage {
    static constexpr std::uint16_t MSG_TYPE = 3;
};

using StoredMessage = std::vector<std::byte>;

template <MessageLike T>
struct MessageBuilder {
    T payload{};
    std::uint32_t seq = 7;
    std::uint32_t ack_seq = 3;
    std::optional<std::uint16_t> override_msg_type = std::nullopt;
    std::optional<std::uint16_t> override_msg_size = std::nullopt;

    MessageBuilder& operator=(MessageBuilder const&) = default;

    StoredMessage build() const {
        const Message<T> message{
            .msg_hdr = {
                .msg_size = override_msg_size.value_or(sizeof(Message<T>)),
                .seq = seq,
                .ack_seq = ack_seq,
                .msg_type = override_msg_type.value_or(T::MSG_TYPE),
            },
            .msg = payload,
        };
        const auto bytes = std::as_bytes(std::span{&message, 1});
        return {bytes.begin(), bytes.end()};
    }
};

struct MockMessageReceiver {
    std::array<std::queue<StoredMessage>, 256> queued;
    std::array<std::queue<StoredMessage>, 256> arrivals;
    std::expected<void, ReceiveError> poll_result;
    std::size_t polls = 0;
    std::size_t consumes = 0;

    std::expected<void, ReceiveError> poll() {
        ++polls;
        if (!poll_result) {
            return poll_result;
        }
        for (std::size_t channel = 0; channel < queued.size(); ++channel) {
            while (!arrivals[channel].empty()) {
                queued[channel].push(std::move(arrivals[channel].front()));
                arrivals[channel].pop();
            }
        }
        return {};
    }

    std::optional<AnyMessageView> peek(std::uint8_t channel) const {
        if (queued[channel].empty()) {
            return std::nullopt;
        }
        const auto& message = queued[channel].front();
        return AnyMessageView{
            .metadata = {.channel_id = channel},
            .msg_bytes = message,
        };
    }

    void consume(std::uint8_t channel) {
        REQUIRE_FALSE(queued[channel].empty());
        ++consumes;
        queued[channel].pop();
    }
};

} // namespace

TEST_CASE("MessageReader dispatches a typed view without copying the message", "[message][reader]")
{
    constexpr std::uint8_t channel = 9;
    const MessageBuilder expected{.payload = FirstMessage{0x12345678}};
    MockMessageReceiver receiver;
    receiver.queued[channel].push(expected.build());
    MessageReader reader{receiver};

    REQUIRE(reader.try_read<FirstMessage>(channel, [&](MessageView<FirstMessage> const& view) {
        CHECK(view.metadata.channel_id == channel);
        CHECK(static_cast<const void*>(view.message) == receiver.queued[channel].front().data());
        CHECK(view.message->msg_hdr.msg_size == sizeof(Message<FirstMessage>));
        CHECK(view.message->msg_hdr.seq == expected.seq);
        CHECK(view.message->msg_hdr.ack_seq == expected.ack_seq);
        CHECK(view.message->msg_hdr.msg_type == FirstMessage::MSG_TYPE);
        CHECK(view.message->msg.value == expected.payload.value);
        CHECK(receiver.consumes == 0); // Borrowed storage remains valid during the callback.
    }));
    CHECK(receiver.consumes == 1);
}

TEST_CASE("MessageReader skips unmatched and malformed messages", "[message][reader]")
{
    constexpr std::uint8_t channel = 9;
    const MessageBuilder unmatched{.payload = FirstMessage{}, .override_msg_type = 99};
    const MessageBuilder matching{.payload = FirstMessage{42}};
    MessageBuilder<FirstMessage> wrong_size;
    wrong_size = matching;
    wrong_size.override_msg_size = sizeof(Message<FirstMessage>) - 1;
    MockMessageReceiver receiver;
    receiver.queued[channel].push(unmatched.build());
    receiver.queued[channel].push(wrong_size.build());
    receiver.queued[channel].push(matching.build());
    MessageReader reader{receiver};
    std::size_t callbacks = 0;
    REQUIRE(reader.try_read<FirstMessage>(channel, [&](MessageView<FirstMessage> const& view) {
        callbacks += 1;
        CHECK(view.message->msg_hdr.seq == matching.seq);
        CHECK(receiver.consumes == 2);
    }));
    CHECK(callbacks == 1);
    CHECK(receiver.queued[channel].empty());
}

TEST_CASE("MessageReader stops at the first matching message", "[message][reader]")
{
    constexpr std::uint8_t channel = 9;
    const MessageBuilder first{.payload = FirstMessage{42}};
    const MessageBuilder second{.payload = SecondMessage{19}};
    MockMessageReceiver receiver;
    receiver.queued[channel].push(first.build());
    receiver.queued[channel].push(second.build());
    MessageReader reader{receiver};
    std::size_t callbacks = 0;
    REQUIRE((reader.try_read<FirstMessage, SecondMessage>(channel, [&]<MessageLike T>(MessageView<T> const& view) {
        callbacks += 1;
        CHECK(view.message->msg_hdr.msg_type == FirstMessage::MSG_TYPE);
    })));
    CHECK(callbacks == 1);
    CHECK(receiver.consumes == 1);
    REQUIRE(receiver.queued[channel].size() == 1);
    CHECK(receiver.peek(channel)->msg_hdr()->msg_type == SecondMessage::MSG_TYPE);
}

TEST_CASE("MessageReader polls only when no matching message is queued", "[message][reader]")
{
    constexpr std::uint8_t channel = 9;
    const MessageBuilder first{.payload = SecondMessage{42}};
    MessageBuilder<SecondMessage> second;
    second = first;
    second.seq = first.seq + 1;
    MockMessageReceiver receiver;
    receiver.arrivals[channel].push(first.build());
    receiver.arrivals[channel].push(second.build());
    MessageReader reader{receiver};
    const auto callback = [](MessageView<SecondMessage> const&) {};
    REQUIRE(reader.try_read<SecondMessage>(channel, callback));
    CHECK(receiver.polls == 1);
    REQUIRE(reader.try_read<SecondMessage>(channel, callback));
    CHECK(receiver.polls == 1);
}

TEST_CASE("MessageReader returns false after one poll when no messages are available", "[message][reader]")
{
    MockMessageReceiver receiver;
    MessageReader reader{receiver};
    CHECK_FALSE(reader.try_read<FirstMessage>(9, [](MessageView<FirstMessage> const&) {
        FAIL("No message should reach the callback");
    }));
    CHECK(receiver.polls == 1);
}

TEST_CASE("MessageReader returns false on poll errors", "[message][reader]")
{
    MockMessageReceiver receiver;
    receiver.poll_result = std::unexpected(GENERATE(
        ReceiveError::Disconnected, ReceiveError::SysPollError, ReceiveError::SysReadError));
    MessageReader reader{receiver};
    CHECK_FALSE(reader.try_read<FirstMessage>(9, [](MessageView<FirstMessage> const&) {
        FAIL("A failed poll should not invoke the callback");
    }));
}

TEST_CASE("MessageReader dispatches header-only messages", "[message][reader]")
{
    constexpr std::uint8_t channel = 255;
    const MessageBuilder expected{.payload = HeaderOnlyMessage{}};
    MockMessageReceiver receiver;
    receiver.queued[channel].push(expected.build());
    MessageReader reader{receiver};
    std::size_t callbacks = 0;
    REQUIRE(reader.try_read<HeaderOnlyMessage>(channel, [&](MessageView<HeaderOnlyMessage> const& view) {
        callbacks += 1;
        CHECK(view.message->msg_hdr.msg_type == HeaderOnlyMessage::MSG_TYPE);
        CHECK(view.message->msg_hdr.msg_size == sizeof(Message<HeaderOnlyMessage>));
    }));
    CHECK(callbacks == 1);
}

TEST_CASE("MessageReader leaves other channels untouched", "[message][reader]")
{
    constexpr std::uint8_t channel = 9;
    constexpr std::uint8_t other_channel = 255;
    const MessageBuilder other{.payload = FirstMessage{42}};
    MockMessageReceiver receiver;
    receiver.queued[other_channel].push(other.build());
    MessageReader reader{receiver};
    CHECK_FALSE(reader.try_read<FirstMessage>(channel, [](MessageView<FirstMessage> const&) {
        FAIL("Messages from other channels should not reach the callback");
    }));
    CHECK(receiver.consumes == 0);
    CHECK(receiver.queued[other_channel].size() == 1);
}

TEST_CASE("MessageReader try_read_for reads once with a zero duration", "[message][reader]")
{
    constexpr std::uint8_t channel = 9;
    const MessageBuilder arriving{.payload = FirstMessage{42}};
    MockMessageReceiver receiver;
    receiver.arrivals[channel].push(arriving.build());
    MessageReader reader{receiver};
    std::size_t callbacks = 0;
    REQUIRE(reader.try_read_for<FirstMessage>(channel, [&](MessageView<FirstMessage> const&) {
        callbacks += 1;
    }, std::chrono::seconds{0}));
    CHECK(callbacks == 1);
    CHECK(receiver.polls == 1);
}
