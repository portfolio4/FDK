#include <catch2/catch_all.hpp>

#include <fdk/fpga/message/MessageReceiver.h>

#include <algorithm>
#include <array>
#include <cstddef>
#include <cstdint>
#include <expected>
#include <optional>
#include <queue>
#include <span>
#include <vector>

namespace {

using namespace fdk::fpga;

struct MockChannelReceiver {
    std::array<std::queue<std::vector<std::byte>>, 256> packets;
    std::expected<void, ReceiveError> poll_result;
    std::size_t polls = 0;
    std::size_t peeks = 0;
    std::size_t consumes = 0;
    std::uint8_t last_channel = 0;

    std::expected<void, ReceiveError> poll() {
        ++polls;
        return poll_result;
    }

    std::optional<ChannelPacketView> peek(std::uint8_t channel_id) {
        ++peeks;
        last_channel = channel_id;
        if (packets[channel_id].empty()) {
            return std::nullopt;
        }
        return ChannelPacketView{.metadata = {.channel_id = channel_id}, .payload = packets[channel_id].front()};
    }

    void consume(std::uint8_t channel_id) {
        ++consumes;
        last_channel = channel_id;
        if (!packets[channel_id].empty()) {
            packets[channel_id].pop();
        }
    }
};

static_assert(MessageReceiverLike<MessageReceiver<MockChannelReceiver>>);

struct PacketBuilder {
    // Compute the size from the body unless a test overrides it.
    std::optional<std::uint16_t> msg_size = std::nullopt;
    std::uint32_t seq = 7;
    std::uint32_t ack_seq = 0x90ABCDEF;
    std::uint16_t msg_type = 0xA5B6;
    std::span<const std::byte> body{};
    std::size_t padding = 0;

    std::vector<std::byte> build() const {
        const MsgHeader header{
            .msg_size = msg_size.value_or(static_cast<std::uint16_t>(sizeof(MsgHeader) + body.size())),
            .seq = seq,
            .ack_seq = ack_seq,
            .msg_type = msg_type,
        };
        const auto bytes = std::as_bytes(std::span{&header, 1});
        std::vector<std::byte> packet(bytes.begin(), bytes.end());
        packet.insert(packet.end(), body.begin(), body.end());
        packet.insert(packet.end(), padding, std::byte{0xAA});
        return packet;
    }
};

} // namespace

TEST_CASE("MessageReceiver poll delegates and returns channel errors", "[message][receiver]")
{
    MockChannelReceiver channel_receiver;
    MessageReceiver receiver{channel_receiver};
    SECTION("Success") {}
    SECTION("Failure") {
        channel_receiver.poll_result = std::unexpected(GENERATE(
            ReceiveError::Disconnected, ReceiveError::SysPollError, ReceiveError::SysReadError));
    }
    CHECK(receiver.poll() == channel_receiver.poll_result);
    CHECK(channel_receiver.polls == 1);
    CHECK(channel_receiver.peeks == 0);
    CHECK(channel_receiver.consumes == 0);
}

TEST_CASE("MessageReceiver peek borrows the body and excludes channel padding", "[message][receiver]")
{
    const auto channel = static_cast<std::uint8_t>(GENERATE(0, 9, 255));
    const auto padding = static_cast<std::size_t>(GENERATE(0, 1, 8, 20));
    const std::array body{std::byte{1}, std::byte{2}, std::byte{3}};
    const PacketBuilder builder{.seq = 0x12345678, .body = body, .padding = padding};
    MockChannelReceiver channel_receiver;
    channel_receiver.packets[channel].push(builder.build());
    const MessageReceiver receiver{channel_receiver};

    const auto view = receiver.peek(channel);
    REQUIRE(view);
    CHECK(view->metadata.channel_id == channel);
    CHECK(view->msg_bytes.data() == channel_receiver.packets[channel].front().data());
    CHECK(view->msg_bytes.size() == builder.msg_size.value_or(sizeof(MsgHeader) + builder.body.size()));
    CHECK(view->msg_hdr()->msg_size == builder.msg_size.value_or(sizeof(MsgHeader) + builder.body.size()));
    CHECK(view->msg_hdr()->seq == builder.seq);
    CHECK(view->msg_hdr()->ack_seq == builder.ack_seq);
    CHECK(view->msg_hdr()->msg_type == builder.msg_type); // Unknown application types need no registration.
    CHECK(std::ranges::equal(
        std::span{view->msg_payload(), view->msg_hdr()->msg_size - sizeof(MsgHeader)}, builder.body));
    CHECK(static_cast<const void*>(view->msg_hdr()) == channel_receiver.packets[channel].front().data());
    CHECK(view->msg_payload() == channel_receiver.packets[channel].front().data() + sizeof(MsgHeader));
    const auto second = receiver.peek(channel);
    REQUIRE(second);
    CHECK(second->msg_hdr() == view->msg_hdr());
    CHECK(second->msg_payload() == view->msg_payload());
    CHECK(channel_receiver.last_channel == channel);
    CHECK(channel_receiver.polls == 0);
    CHECK(channel_receiver.consumes == 0);
    CHECK(channel_receiver.packets[channel].size() == 1);
}

TEST_CASE("MessageReceiver supports header-only messages", "[message][receiver]")
{
    const PacketBuilder builder{.padding = 4};
    MockChannelReceiver channel_receiver;
    channel_receiver.packets[9].push(builder.build());
    MessageReceiver receiver{channel_receiver};
    const auto view = receiver.peek(9);
    REQUIRE(view);
    CHECK(view->msg_hdr()->msg_size == builder.msg_size.value_or(sizeof(MsgHeader) + builder.body.size()));
    CHECK(view->msg_payload() == channel_receiver.packets[9].front().data() + sizeof(MsgHeader));
}

TEST_CASE("MessageReceiver returns no view for empty channels or malformed messages", "[message][receiver]")
{
    MockChannelReceiver channel_receiver;
    MessageReceiver receiver{channel_receiver};
    CHECK_FALSE(receiver.peek(9));
    auto packet = PacketBuilder{}.build();
    SECTION("Truncated header") {
        packet.resize(GENERATE(0, 1, 11));
    }
    SECTION("Declared size smaller than the header") {
        packet = PacketBuilder{.msg_size = static_cast<std::uint16_t>(GENERATE(0, 1, 11))}.build();
    }
    SECTION("Declared size exceeds the packet") {
        packet = PacketBuilder{.msg_size = static_cast<std::uint16_t>(GENERATE(13, 65535))}.build();
    }
    channel_receiver.packets[9].push(packet);
    CHECK_FALSE(receiver.peek(9));
    CHECK(channel_receiver.consumes == 0);
    CHECK(channel_receiver.packets[9].front() == packet);
    receiver.consume(9);
    CHECK(channel_receiver.packets[9].empty());
}

TEST_CASE("MessageReceiver consume removes exactly one packet from the selected channel", "[message][receiver]")
{
    const PacketBuilder next_packet{.seq = 2};
    MockChannelReceiver channel_receiver;
    channel_receiver.packets[9].push(PacketBuilder{.seq = 1}.build());
    channel_receiver.packets[9].push(next_packet.build());
    channel_receiver.packets[255].push(PacketBuilder{.seq = 3}.build());
    MessageReceiver receiver{channel_receiver};
    receiver.consume(9);
    CHECK(channel_receiver.consumes == 1);
    CHECK(channel_receiver.last_channel == 9);
    REQUIRE(channel_receiver.packets[9].size() == 1);
    CHECK(channel_receiver.packets[255].size() == 1);
    const auto next = receiver.peek(9);
    REQUIRE(next);
    CHECK(next->msg_hdr()->seq == next_packet.seq);
    receiver.consume(9);
    CHECK_FALSE(receiver.peek(9));
    receiver.consume(9); // Empty channel consumption is delegated as well.
    CHECK(channel_receiver.consumes == 3);
    CHECK(channel_receiver.packets[255].size() == 1);
}
