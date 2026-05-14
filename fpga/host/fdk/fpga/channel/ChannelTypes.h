#pragma once

#include <fdk/fpga/Errors.h>
#include <fdk/fpga/platform/platform.h>

#include <concepts>
#include <cstddef>
#include <cstdint>
#include <expected>
#include <optional>
#include <span>
#include <type_traits>

namespace fdk::fpga {

// Wire order: channel ID, descriptor, then all payload lanes. The application
// determines the meaningful payload length and ignores final-frame padding.
struct [[gnu::packed]] ChannelFrame {
    static constexpr std::uint8_t SOP = 1 << 0;
    static constexpr std::uint8_t EOP = 1 << 1;

    std::uint8_t channel_id = 0;
    std::uint8_t descriptor = 0;
    std::byte payload[fdk::fpga::platform::CHANNEL_PAYLOAD_BYTES]{};
};

static_assert(fdk::fpga::platform::CHANNEL_PAYLOAD_BYTES > 0);
static_assert(sizeof(ChannelFrame) == fdk::fpga::platform::CHANNEL_PAYLOAD_BYTES + 2);
static_assert(alignof(ChannelFrame) == 1);
static_assert(offsetof(ChannelFrame, channel_id) == 0);
static_assert(offsetof(ChannelFrame, descriptor) == 1);
static_assert(offsetof(ChannelFrame, payload) == 2);
static_assert(std::is_trivially_copyable_v<ChannelFrame>);
static_assert(std::is_standard_layout_v<ChannelFrame>);

// More packet metadata fields may be added in the future.
struct ChannelPacketMetadata {
    std::uint8_t channel_id;
};

// Borrows a complete received packet, including final-frame padding. Valid
// until its channel's front packet is consumed or its receiver is destroyed.
struct ChannelPacketView {
    ChannelPacketMetadata metadata;
    std::span<const std::byte> payload;
};

// Send a trivially copyable payload on a channel. A byte is used to check the
// signature; implementations must support the caller's payload types as well.
template <typename T>
concept ChannelSenderLike = requires(T& sender, std::uint8_t channel_id, std::byte const& payload) {
    { sender.send(channel_id, payload) } -> std::same_as<std::expected<void, SendError>>;
};

template <typename T>
concept ChannelReceiverLike = requires(T& receiver, std::uint8_t channel_id) {
    { receiver.poll() } -> std::same_as<std::expected<void, ReceiveError>>;
    { receiver.peek(channel_id) } -> std::same_as<std::optional<ChannelPacketView>>;
    { receiver.consume(channel_id) } -> std::same_as<void>;
};

} // namespace fdk::fpga
