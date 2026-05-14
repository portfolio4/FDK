#include <catch2/catch_all.hpp>

#include <fdk/fpga/ByteTransport.h>
#include <fdk/fpga/channel/ChannelReceiver.h>
#include <fdk/fpga/channel/ChannelSender.h>
#include <fdk/fpga/channel/ChannelTypes.h>
#include <fdk/fpga/Errors.h>
#include <fdk/fpga/uart/UartReceiver.h>
#include <fdk/fpga/uart/UartSender.h>

#include <algorithm>
#include <array>
#include <cstddef>
#include <cstdint>
#include <optional>
#include <span>
#include <expected>
#include <type_traits>
#include <utility>
#include <vector>

namespace {

using namespace fdk::fpga;

static_assert(fdk::fpga::platform::CHANNEL_PAYLOAD_BYTES == 8);
static_assert(sizeof(ChannelFrame) == 10);
static_assert(std::is_aggregate_v<ChannelFrame>);
static_assert(BytesSender<UartSender>);
static_assert(BytesReceiver<UartReceiver>);

struct RecordingSender {
    std::vector<std::byte> bytes;
    std::size_t calls = 0;

    std::expected<void, SendError> send(std::span<const std::byte> frame) {
        CHECK(frame.size() == sizeof(ChannelFrame));
        bytes.insert(bytes.end(), frame.begin(), frame.end());
        ++calls;
        return {};
    }
};

struct BufferedReceiver {
    std::vector<std::byte> input;
    std::vector<std::byte> buffer;
    std::optional<ReceiveError> error;
    std::size_t poll_calls = 0;
    std::size_t peek_calls = 0;
    std::size_t consume_calls = 0;
    std::size_t bytes_consumed = 0;

    std::expected<void, ReceiveError> poll() {
        ++poll_calls;
        if (error) {
            return std::unexpected(*error);
        }
        buffer.insert(buffer.end(), input.begin(), input.end());
        input.clear();
        return {};
    }

    std::span<const std::byte> peek() {
        ++peek_calls;
        return buffer;
    }

    void consume(std::size_t count) {
        REQUIRE(count <= buffer.size());
        ++consume_calls;
        bytes_consumed += count;
        buffer.erase(buffer.begin(), buffer.begin() + count);
    }
};

static_assert(BytesSender<RecordingSender>);
static_assert(BytesReceiver<BufferedReceiver>);
static_assert(!BytesSender<BufferedReceiver>);
static_assert(!BytesReceiver<RecordingSender>);

struct MutableBytesSender {
    std::expected<void, SendError> send(std::span<std::byte>);
};

struct WrongSendError {
    std::expected<void, ReceiveError> send(std::span<const std::byte>);
};

struct MutablePeekReceiver : BufferedReceiver {
    std::span<std::byte> peek();
};

struct WrongPollError : BufferedReceiver {
    std::expected<void, SendError> poll();
};

struct NonVoidConsume : BufferedReceiver {
    std::size_t consume(std::size_t);
};

static_assert(!BytesSender<MutableBytesSender>);
static_assert(!BytesSender<WrongSendError>);
static_assert(!BytesReceiver<MutablePeekReceiver>);
static_assert(!BytesReceiver<WrongPollError>);
static_assert(!BytesReceiver<NonVoidConsume>);

} // namespace

TEST_CASE("ChannelSender emits the fixed wire format", "[channel][serializer]")
{
    const std::array payload{std::byte{1}, std::byte{2}, std::byte{3}};
    RecordingSender sender;
    const ChannelSender serializer{sender};
    const auto frames = serializer.serialize(7, payload);
    REQUIRE(frames.size() == 1);
    const std::array expected{
        std::byte{7}, std::byte{3}, std::byte{1}, std::byte{2}, std::byte{3},
        std::byte{0}, std::byte{0}, std::byte{0}, std::byte{0}, std::byte{0},
    };
    CHECK(std::ranges::equal(std::as_bytes(std::span{frames}), expected));
    CHECK(serializer.serialize(0, payload).front().channel_id == 0);
    CHECK(serializer.serialize(255, payload).front().channel_id == 255);
    REQUIRE(serializer.send(0, payload));
    REQUIRE(serializer.send(255, payload));
    CHECK(sender.calls == 2);
    CHECK(sender.bytes[0] == std::byte{0});
    CHECK(sender.bytes[sizeof(ChannelFrame)] == std::byte{255});
}

TEMPLATE_TEST_CASE(
    "ChannelSender fragments objects and zero pads the final frame", "[channel][serializer]",
    (std::array<std::byte, 1>),
    (std::array<std::byte, 7>),
    (std::array<std::byte, 8>),
    (std::array<std::byte, 9>),
    (std::array<std::byte, 16>),
    (std::array<std::byte, 25>),
    (std::array<std::byte, 65536>))
{
    TestType payload;
    for (std::size_t i = 0; i < payload.size(); ++i) {
        payload[i] = static_cast<std::byte>(i % 251 + 1);
    }
    const auto channel = static_cast<std::uint8_t>(GENERATE(0, 7, 255));
    RecordingSender sender;
    const ChannelSender serializer{sender};
    const auto frames = serializer.serialize(channel, payload);
    REQUIRE(frames.size() == (payload.size() + fdk::fpga::platform::CHANNEL_PAYLOAD_BYTES - 1) / fdk::fpga::platform::CHANNEL_PAYLOAD_BYTES);
    for (std::size_t i = 0; i < frames.size(); ++i) {
        const auto& frame = frames[i];
        CHECK(frame.channel_id == channel);
        CHECK(frame.descriptor == ((i == 0 ? ChannelFrame::SOP : 0) |
                                   (i + 1 == frames.size() ? ChannelFrame::EOP : 0)));
        for (std::size_t lane = 0; lane < fdk::fpga::platform::CHANNEL_PAYLOAD_BYTES; ++lane) {
            const auto offset = i * fdk::fpga::platform::CHANNEL_PAYLOAD_BYTES + lane;
            CHECK(frame.payload[lane] == (offset < payload.size() ? payload[offset] : std::byte{0}));
        }
    }

    REQUIRE(serializer.send(channel, payload));
    CHECK(sender.calls == frames.size());
    CHECK(std::ranges::equal(sender.bytes, std::as_bytes(std::span{frames})));
}

TEST_CASE("ChannelSender supports wire structs and synchronous sender failures", "[channel][serializer]")
{
    struct Message {
        std::array<std::byte, 3> header;
        std::array<std::byte, 14> body;
    };
    const Message message{{std::byte{1}, std::byte{2}, std::byte{3}}, {std::byte{4}}};
    RecordingSender sender;
    const ChannelSender serializer{sender};
    const auto frames = serializer.serialize(255, message);
    REQUIRE(frames.size() == 3);
    REQUIRE(serializer.send(255, message));
    CHECK(std::ranges::equal(sender.bytes, std::as_bytes(std::span{frames})));

    struct FailingSender {
        int fail_on;
        SendError error;
        int calls = 0;
        std::expected<void, SendError> send(std::span<const std::byte>) {
            if (++calls == fail_on) {
                return std::unexpected(error);
            }
            return {};
        }
    };
    const auto fail_on = GENERATE(1, 2, 3);
    const auto error = GENERATE(SendError::Disconnected, SendError::SysWriteError);
    FailingSender failing{fail_on, error};
    const auto result = ChannelSender{failing}.send(255, message);
    static_assert(std::is_same_v<decltype(result), const std::expected<void, SendError>>);
    REQUIRE_FALSE(result);
    CHECK(result.error() == error);
    CHECK(failing.calls == fail_on);
}

TEST_CASE("ChannelSender sends the contents of a byte span", "[channel][serializer]")
{
    const std::array payload{
        std::byte{1}, std::byte{2}, std::byte{3}, std::byte{4}, std::byte{5},
        std::byte{6}, std::byte{7}, std::byte{8}, std::byte{9},
    };
    RecordingSender sender;
    const ChannelSender serializer{sender};
    REQUIRE(serializer.send(4, std::span<const std::byte>{payload}));
    const auto expected = serializer.serialize(4, payload);
    CHECK(std::ranges::equal(sender.bytes, std::as_bytes(std::span{expected})));
    REQUIRE(serializer.send(4, std::span<const std::byte>{}));
    CHECK(sender.calls == expected.size());
}

TEST_CASE("ChannelReceiver leaves every incomplete frame prefix unconsumed", "[channel][receiver]")
{
    const std::array wire{
        std::byte{255}, std::byte{3}, std::byte{1}, std::byte{2}, std::byte{3},
        std::byte{4}, std::byte{5}, std::byte{6}, std::byte{7}, std::byte{8},
    };
    const auto split = GENERATE(std::size_t{0}, 1u, 2u, 3u, 4u, 5u, 6u, 7u, 8u, 9u);
    CAPTURE(split);
    BufferedReceiver transport;
    ChannelReceiver receiver{transport};
    transport.input.assign(wire.begin(), wire.begin() + split);
    REQUIRE(receiver.poll());
    CHECK(transport.bytes_consumed == 0);
    CHECK(std::ranges::equal(transport.buffer, std::span{wire}.first(split)));
    CHECK_FALSE(receiver.peek(255));
    receiver.consume(255); // Consuming an empty channel is harmless.
    transport.input.assign(wire.begin() + split, wire.end());
    REQUIRE(receiver.poll());
    CHECK(transport.bytes_consumed == wire.size());
    CHECK(transport.buffer.empty());
    const auto packet = receiver.peek(255);
    REQUIRE(packet);
    CHECK(packet->metadata.channel_id == 255);
    CHECK(std::ranges::equal(packet->payload, std::span{wire}.subspan(2)));
    receiver.consume(255);
    CHECK_FALSE(receiver.peek(255));
    REQUIRE(receiver.poll());
    CHECK(transport.poll_calls == 3);
    CHECK(transport.peek_calls == 3);
    CHECK(transport.consume_calls == 3);
    CHECK(transport.bytes_consumed == wire.size());
}

TEST_CASE("ChannelReceiver assembles interleaved packets on all channels in order", "[channel][receiver]")
{
    std::vector<ChannelFrame> frames;
    for (std::uint8_t packet = 0; packet < 2; ++packet) {
        for (std::uint8_t part = 0; part < 3; ++part) {
            for (std::size_t channel = 0; channel < 256; ++channel) {
                frames.push_back(ChannelFrame{
                    .channel_id = static_cast<std::uint8_t>(channel),
                    .descriptor = static_cast<std::uint8_t>(
                        (part == 0 ? ChannelFrame::SOP : 0) | (part == 2 ? ChannelFrame::EOP : 0)),
                    .payload = {static_cast<std::byte>(channel), static_cast<std::byte>(packet),
                                static_cast<std::byte>(part)},
                });
            }
        }
    }
    const auto chunk_size = GENERATE(std::size_t{1}, 7u, 10u, 13u, 5120u);
    CAPTURE(chunk_size);
    BufferedReceiver transport;
    ChannelReceiver receiver{transport};
    const auto bytes = std::as_bytes(std::span{frames});
    std::size_t available = 0;
    while (available < bytes.size()) {
        const auto chunk = bytes.subspan(available, std::min(chunk_size, bytes.size() - available));
        transport.input.assign(chunk.begin(), chunk.end());
        available += chunk.size();
        REQUIRE(receiver.poll());
        REQUIRE(transport.bytes_consumed == available / sizeof(ChannelFrame) * sizeof(ChannelFrame));
        CHECK(std::ranges::equal(transport.buffer, bytes.subspan(transport.bytes_consumed,
                                                               available - transport.bytes_consumed)));
    }
    REQUIRE(transport.bytes_consumed == bytes.size());
    CHECK(transport.buffer.empty());
    // Packets own their storage independently of the input frame buffer.
    frames.clear();
    frames.shrink_to_fit();
    for (int channel = 255; channel >= 0; --channel) {
        for (std::uint8_t index = 0; index < 2; ++index) {
            const auto& view = receiver;
            const auto packet = view.peek(static_cast<std::uint8_t>(channel));
            const auto second_peek = view.peek(static_cast<std::uint8_t>(channel));
            REQUIRE(packet);
            REQUIRE(second_peek);
            CHECK(packet->metadata.channel_id == channel);
            CHECK(packet->payload.data() == second_peek->payload.data());
            REQUIRE(packet->payload.size() == 3 * platform::CHANNEL_PAYLOAD_BYTES);
            for (std::size_t part = 0; part < 3; ++part) {
                const auto payload = packet->payload.subspan(part * platform::CHANNEL_PAYLOAD_BYTES,
                                                            platform::CHANNEL_PAYLOAD_BYTES);
                CHECK(payload[0] == static_cast<std::byte>(channel));
                CHECK(payload[1] == static_cast<std::byte>(index));
                CHECK(payload[2] == static_cast<std::byte>(part));
                CHECK(std::ranges::all_of(payload.subspan(3), [](auto byte) { return byte == std::byte{0}; }));
            }
            receiver.consume(static_cast<std::uint8_t>(channel));
        }
        CHECK_FALSE(receiver.peek(static_cast<std::uint8_t>(channel)));
    }
}

TEST_CASE("ChannelReceiver exposes packets only after accepting their complete EOP frame", "[channel][receiver]")
{
    const std::array frames{
        ChannelFrame{.channel_id = 7, .descriptor = ChannelFrame::SOP, .payload = {std::byte{1}}},
        ChannelFrame{.channel_id = 7, .descriptor = ChannelFrame::EOP, .payload = {std::byte{2}}},
    };
    const auto prefix = GENERATE(std::size_t{0}, 1u, 2u, 9u);
    const auto bytes = std::as_bytes(std::span{frames});
    BufferedReceiver transport;
    ChannelReceiver receiver{transport};
    transport.input.assign(bytes.begin(), bytes.begin() + sizeof(ChannelFrame) + prefix);
    REQUIRE(receiver.poll());
    CHECK(transport.bytes_consumed == sizeof(ChannelFrame));
    CHECK(transport.buffer.size() == prefix);
    CHECK_FALSE(receiver.peek(7));
    receiver.consume(7); // Pending bytes must survive consuming an empty queue.
    transport.input.assign(bytes.begin() + sizeof(ChannelFrame) + prefix, bytes.end());
    REQUIRE(receiver.poll());
    CHECK(transport.bytes_consumed == bytes.size());
    CHECK(transport.buffer.empty());
    const auto packet = receiver.peek(7);
    REQUIRE(packet);
    REQUIRE(packet->payload.size() == 2 * platform::CHANNEL_PAYLOAD_BYTES);
    CHECK(packet->payload.front() == std::byte{1});
    CHECK(packet->payload[platform::CHANNEL_PAYLOAD_BYTES] == std::byte{2});
    receiver.consume(7);
    CHECK_FALSE(receiver.peek(7));
}

TEST_CASE("ChannelReceiver SOP restarts only the unfinished packet on its channel", "[channel][receiver]")
{
    const std::array frames{
        ChannelFrame{.channel_id = 7, .descriptor = ChannelFrame::SOP, .payload = {std::byte{1}}},
        ChannelFrame{.channel_id = 9, .descriptor = ChannelFrame::SOP, .payload = {std::byte{2}}},
        ChannelFrame{.channel_id = 7, .descriptor = ChannelFrame::SOP | ChannelFrame::EOP,
                     .payload = {std::byte{3}}},
        ChannelFrame{.channel_id = 9, .descriptor = ChannelFrame::EOP, .payload = {std::byte{4}}},
    };
    BufferedReceiver transport;
    ChannelReceiver receiver{transport};
    const auto bytes = std::as_bytes(std::span{frames});
    transport.input.assign(bytes.begin(), bytes.end());
    REQUIRE(receiver.poll());
    CHECK(transport.bytes_consumed == bytes.size());
    const auto restarted = receiver.peek(7);
    REQUIRE(restarted);
    REQUIRE(restarted->payload.size() == platform::CHANNEL_PAYLOAD_BYTES);
    CHECK(restarted->payload.front() == std::byte{3});
    const auto other = receiver.peek(9);
    REQUIRE(other);
    REQUIRE(other->payload.size() == 2 * platform::CHANNEL_PAYLOAD_BYTES);
    CHECK(other->payload.front() == std::byte{2});
    CHECK(other->payload[platform::CHANNEL_PAYLOAD_BYTES] == std::byte{4});
}

TEST_CASE("ChannelReceiver views survive receiving and consuming other packets", "[channel][receiver]")
{
    const std::array first{
        ChannelFrame{.channel_id = 7, .descriptor = ChannelFrame::SOP | ChannelFrame::EOP,
                     .payload = {std::byte{1}}},
    };
    BufferedReceiver transport;
    ChannelReceiver receiver{transport};
    const auto first_bytes = std::as_bytes(std::span{first});
    transport.input.assign(first_bytes.begin(), first_bytes.end());
    REQUIRE(receiver.poll());
    const auto view = receiver.peek(7);
    REQUIRE(view);
    const auto* data = view->payload.data();
    // Grow both the completed queue and the pending buffer on the same channel.
    std::vector<ChannelFrame> more(1000, ChannelFrame{
        .channel_id = 7, .descriptor = ChannelFrame::SOP | ChannelFrame::EOP,
        .payload = {std::byte{2}},
    });
    more.push_back(ChannelFrame{.channel_id = 7, .descriptor = ChannelFrame::SOP});
    more.push_back(ChannelFrame{.channel_id = 9, .descriptor = ChannelFrame::SOP | ChannelFrame::EOP});
    const auto more_bytes = std::as_bytes(std::span{more});
    transport.input.assign(more_bytes.begin(), more_bytes.end());
    REQUIRE(receiver.poll());
    CHECK(transport.bytes_consumed == first_bytes.size() + more_bytes.size());
    receiver.consume(9);
    CHECK(receiver.peek(7)->payload.data() == data);
    CHECK(view->payload.front() == std::byte{1});
    receiver.consume(7);
    const auto next = receiver.peek(7);
    REQUIRE(next);
    CHECK(next->payload.front() == std::byte{2});
}

TEMPLATE_TEST_CASE("ChannelSender packets reassemble with final-frame padding", "[channel][receiver]",
                   (std::array<std::byte, 1>), (std::array<std::byte, 8>),
                   (std::array<std::byte, 9>), (std::array<std::byte, 65536>))
{
    TestType payload;
    for (std::size_t i = 0; i < payload.size(); ++i) {
        payload[i] = static_cast<std::byte>(i % 251 + 1);
    }
    RecordingSender sender;
    const auto frames = ChannelSender{sender}.serialize(255, payload);
    BufferedReceiver transport;
    ChannelReceiver receiver{transport};
    const auto bytes = std::as_bytes(std::span{frames});
    transport.input.assign(bytes.begin(), bytes.end());
    REQUIRE(receiver.poll());
    CHECK(transport.bytes_consumed == bytes.size());
    const auto packet = receiver.peek(255);
    REQUIRE(packet);
    CHECK(packet->metadata.channel_id == 255);
    REQUIRE(packet->payload.size() == frames.size() * platform::CHANNEL_PAYLOAD_BYTES);
    CHECK(std::ranges::equal(packet->payload.first(payload.size()), payload));
    CHECK(std::ranges::all_of(packet->payload.subspan(payload.size()), [](auto byte) { return byte == std::byte{0}; }));
    receiver.consume(255);
    CHECK_FALSE(receiver.peek(255));
}

TEST_CASE("ChannelReceiver propagates poll errors without touching buffered data", "[channel][receiver]")
{
    BufferedReceiver transport;
    ChannelReceiver receiver{transport};
    const std::array initial{
        ChannelFrame{.channel_id = 7, .descriptor = ChannelFrame::SOP | ChannelFrame::EOP,
                     .payload = {std::byte{1}}},
        ChannelFrame{.channel_id = 7, .descriptor = ChannelFrame::SOP, .payload = {std::byte{2}}},
    };
    const auto bytes = std::as_bytes(std::span{initial});
    transport.input.assign(bytes.begin(), bytes.end());
    REQUIRE(receiver.poll());
    const auto queued = receiver.peek(7);
    REQUIRE(queued);

    const std::array last{
        ChannelFrame{.channel_id = 7, .descriptor = ChannelFrame::EOP, .payload = {std::byte{3}}},
    };
    const auto last_bytes = std::as_bytes(std::span{last});
    transport.buffer.assign(last_bytes.begin(), last_bytes.end());
    transport.error = GENERATE(ReceiveError::Disconnected, ReceiveError::SysPollError, ReceiveError::SysReadError);
    const auto result = receiver.poll();
    static_assert(std::is_same_v<decltype(result), const std::expected<void, ReceiveError>>);
    REQUIRE_FALSE(result);
    CHECK(result.error() == *transport.error);
    CHECK(transport.poll_calls == 2);
    CHECK(transport.peek_calls == 1);
    CHECK(transport.consume_calls == 1);
    CHECK(transport.bytes_consumed == bytes.size());
    CHECK(std::ranges::equal(transport.buffer, last_bytes));
    CHECK(receiver.peek(7)->payload.data() == queued->payload.data());
    CHECK(queued->payload.front() == std::byte{1});

    // A later successful poll completes the packet that was pending before failure.
    transport.error.reset();
    REQUIRE(receiver.poll());
    CHECK(transport.buffer.empty());
    receiver.consume(7);
    const auto completed = receiver.peek(7);
    REQUIRE(completed);
    REQUIRE(completed->payload.size() == 2 * platform::CHANNEL_PAYLOAD_BYTES);
    CHECK(completed->payload.front() == std::byte{2});
    CHECK(completed->payload[platform::CHANNEL_PAYLOAD_BYTES] == std::byte{3});
}
