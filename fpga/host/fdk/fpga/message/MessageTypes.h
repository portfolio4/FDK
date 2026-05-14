#pragma once

#include <fdk/fpga/Errors.h>
#include <fdk/fpga/channel/ChannelTypes.h>

#include <cstddef>
#include <cstdint>
#include <concepts>
#include <expected>
#include <memory>
#include <optional>
#include <span>
#include <type_traits>

namespace fdk::fpga {

template <typename T>
concept MessageLike =
    std::is_trivially_copyable_v<T> &&
    requires {
        { T::MSG_TYPE } -> std::convertible_to<std::uint16_t>;
    };

struct [[gnu::packed]] MsgHeader {
    // Entire message in bytes, including this header, excluding channel padding.
    std::uint16_t msg_size;
    std::uint32_t seq;
    std::uint32_t ack_seq;
    std::uint16_t msg_type;
};

static_assert(sizeof(MsgHeader) == 12);
static_assert(offsetof(MsgHeader, msg_size) == 0);
static_assert(offsetof(MsgHeader, seq) == 2);
static_assert(offsetof(MsgHeader, ack_seq) == 6);
static_assert(offsetof(MsgHeader, msg_type) == 10);

struct EchoRequest {
    constexpr static std::uint16_t MSG_TYPE = 1;
    std::byte payload[128];
};

struct EchoResponse {
    constexpr static std::uint16_t MSG_TYPE = 2;
    std::byte payload[128];
};

// These msg types can be overloaded to have different meaning depending on the
// application. We'll reserve the range 2048-4096 for these, but only
// the first few are currently declared.
constexpr static std::uint16_t APP_SPECIFIC_MSG_TYPE_0 = 2048;
constexpr static std::uint16_t APP_SPECIFIC_MSG_TYPE_1 = 2049;
constexpr static std::uint16_t APP_SPECIFIC_MSG_TYPE_2 = 2050;
constexpr static std::uint16_t APP_SPECIFIC_MSG_TYPE_3 = 2051;
constexpr static std::uint16_t APP_SPECIFIC_MSG_TYPE_4 = 2052;
constexpr static std::uint16_t APP_SPECIFIC_MSG_TYPE_5 = 2053;
constexpr static std::uint16_t APP_SPECIFIC_MSG_TYPE_6 = 2054;

template <typename T>
struct [[gnu::packed]] Message {
    MsgHeader msg_hdr;
    // Empty message bodies occupy no bytes in the wire format.
    [[no_unique_address]] T msg;
};

struct AnyMessageView {
    ChannelPacketMetadata metadata;
    std::span<const std::byte> msg_bytes;

    // Convenience pointer to the header at the beginning of msg_bytes.
    const MsgHeader* msg_hdr() const {
        return std::start_lifetime_as<MsgHeader>(msg_bytes.data());
    }

    // Convenience pointer into msg_bytes immediately after its header;
    // one-past-end for header-only messages.
    const std::byte* msg_payload() const {
        return msg_bytes.data() + sizeof(MsgHeader);
    }
};

template <MessageLike T>
struct MessageView {
    ChannelPacketMetadata metadata;
    const Message<T>* message;
};

// EchoRequest is a representative payload; send() must also support the
// caller's other MessageLike payload types.
template <typename T>
concept MessageSenderLike = requires(T& sender, std::uint8_t channel_id,
                                 std::uint32_t seq, std::uint32_t ack_seq,
                                 EchoRequest const& payload) {
    { sender.send(channel_id, seq, ack_seq, payload) } -> std::same_as<std::expected<void, SendError>>;
};

template <typename T>
concept MessageReceiverLike = requires(T& receiver, std::uint8_t channel_id) {
    { receiver.poll() } -> std::same_as<std::expected<void, ReceiveError>>;
    { receiver.peek(channel_id) } -> std::same_as<std::optional<AnyMessageView>>;
    { receiver.consume(channel_id) } -> std::same_as<void>;
};

} // namespace fdk::fpga
