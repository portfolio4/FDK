#pragma once

#include <fdk/fpga/ByteTransport.h>
#include <fdk/fpga/channel/ChannelTypes.h>
#include <fdk/fpga/Errors.h>

#include <array>
#include <cstring>
#include <expected>
#include <iterator>
#include <optional>
#include <queue>
#include <span>
#include <utility>
#include <vector>

namespace fdk::fpga {

template <BytesReceiver Receiver>
class ChannelReceiver {
public:
    explicit ChannelReceiver(Receiver& receiver) : receiver_(receiver) {}

    // Check underlying BytesReceiver for any new data and handle it
    std::expected<void, ReceiveError> poll() {
        const auto result = receiver_.poll();
        if (!result) {
            return std::unexpected(result.error());
        }
        auto bytes = receiver_.peek();
        const auto input_size = bytes.size();
        while (bytes.size() >= sizeof(ChannelFrame)) {
            ChannelFrame frame;
            std::memcpy(&frame, bytes.data(), sizeof(frame));
            auto& pending = channel_pending_packets_[frame.channel_id];
            if (frame.descriptor & ChannelFrame::SOP) {
                pending.payload.clear();
            }
            pending.payload.insert(pending.payload.end(), std::begin(frame.payload), std::end(frame.payload));
            if (frame.descriptor & ChannelFrame::EOP) {
                channel_packets_[frame.channel_id].push(std::move(pending));
                pending.payload.clear();
            }
            bytes = bytes.subspan(sizeof(frame));
        }
        receiver_.consume(input_size - bytes.size());
        return {};
    }

    // Returns view is valid until consume() called
    std::optional<ChannelPacketView> peek(std::uint8_t channel_id) const {
        const auto& queue = channel_packets_[channel_id];
        if (queue.empty()) {
            return std::nullopt;
        }
        return ChannelPacketView{.metadata = {.channel_id = channel_id}, .payload = queue.front().payload};
    }

    // Consume front packet for channel and move on to next one. No-op if
    // nothing has been received yet
    void consume(std::uint8_t channel_id) {
        auto& queue = channel_packets_[channel_id];
        if (!queue.empty()) {
            queue.pop();
        }
    }

private:
    Receiver& receiver_;

    struct ChannelPacketBuffer {
        std::vector<std::byte> payload;
    };

    // TODO the most optimal solution is a circular buffer of bytes
    // and a circular queue of descriptors identifying where each channel packet
    // ends. This would have no extra copies.
    // But we're starting with this naive implementation to keep things simpler.
    std::array<std::queue<ChannelPacketBuffer>, 256> channel_packets_;
    std::array<ChannelPacketBuffer, 256> channel_pending_packets_;
};

} // namespace fdk::fpga
