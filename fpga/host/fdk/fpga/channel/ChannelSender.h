#pragma once

#include <fdk/fpga/ByteTransport.h>
#include <fdk/fpga/channel/ChannelTypes.h>
#include <fdk/fpga/Errors.h>

#include <algorithm>
#include <cstring>
#include <expected>
#include <ranges>
#include <span>
#include <vector>

namespace fdk::fpga {

template <BytesSender Sender>
class ChannelSender {
public:
    // Borrows the transport, which must outlive this sender.
    explicit ChannelSender(Sender& sender) : sender_(sender) {}

    // T's fields must already use the intended wire byte order.
    template <typename T>
    std::vector<ChannelFrame> serialize(std::uint8_t channel_id, const T& t) const {
        static_assert(std::is_trivially_copyable_v<T>);
        std::vector<ChannelFrame> frames;
        frames.reserve((sizeof(T) + fdk::fpga::platform::CHANNEL_PAYLOAD_BYTES - 1) / fdk::fpga::platform::CHANNEL_PAYLOAD_BYTES);
        for_each_frame(channel_id, std::as_bytes(std::span{&t, 1}), [&frames](ChannelFrame& frame) {
            frames.push_back(frame);
        });
        return frames;
    }

    // Sender must consume/copy each span before returning. Only one stack frame
    // is needed; no intermediate vector or whole-message copy is allocated.
    template <typename T>
    std::expected<void, SendError> send(std::uint8_t channel_id, T const& t) const {
        static_assert(std::is_trivially_copyable_v<T>);
        return send(channel_id, std::as_bytes(std::span{&t, 1}));
    }

    // Sends the referenced bytes, including variable-length application frames.
    std::expected<void, SendError> send(std::uint8_t channel_id, std::span<const std::byte> bytes) const {
        std::expected<void, SendError> result;
        bool already_failed = false;
        for_each_frame(channel_id, bytes, [&](ChannelFrame& frame) {
            if (!already_failed) {
                result = sender_.send(std::as_bytes(std::span{&frame, 1}));
                already_failed = !result.has_value();
            }
        });
        return result;
    }

private:
    Sender& sender_;

    template <typename EmitFn>
    void for_each_frame(std::uint8_t channel_id, std::span<const std::byte> bytes, EmitFn&& emit) const {
        // If the chunk bytes are not evenly-divisible by fdk::fpga::platform::CHANNEL_PAYLOAD_BYTES,
        // the last chunk will be smaller than fdk::fpga::platform::CHANNEL_PAYLOAD_BYTES, which
        // we handle by zero-initializing the payload and only copying the
        // chunk size in
        std::ranges::for_each(bytes | std::views::chunk(fdk::fpga::platform::CHANNEL_PAYLOAD_BYTES), [&](auto chunk) {
            ChannelFrame frame{.channel_id = channel_id, .payload = {}};
            if (chunk.data() == bytes.data()) {
                frame.descriptor |= ChannelFrame::SOP;
            }
            if (chunk.data() + chunk.size() == bytes.data() + bytes.size()) {
                frame.descriptor |= ChannelFrame::EOP;
            }
            std::memcpy(frame.payload, chunk.data(), chunk.size());
            emit(frame);
        });
    }
};

} // namespace fdk::fpga
