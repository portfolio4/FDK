#pragma once

#include <fdk/fpga/channel/ChannelTypes.h>
#include <fdk/fpga/message/MessageTypes.h>

#include <expected>
#include <memory>
#include <optional>

namespace fdk::fpga {

template <ChannelReceiverLike Receiver>
class MessageReceiver {
public:
    explicit MessageReceiver(Receiver& receiver) : receiver_(receiver) {}

    std::expected<void, ReceiveError> poll() {
        return receiver_.poll();
    }

    std::optional<AnyMessageView> peek(std::uint8_t channel_id) const {
        const auto packet = receiver_.peek(channel_id);
        if (!packet || packet->payload.size() < sizeof(MsgHeader)) {
            return std::nullopt;
        }
        const auto* header = std::start_lifetime_as<MsgHeader>(packet->payload.data());
        if (header->msg_size < sizeof(MsgHeader) || header->msg_size > packet->payload.size()) {
            return std::nullopt;
        }
        return AnyMessageView{
            .metadata = packet->metadata,
            .msg_bytes = packet->payload.first(header->msg_size),
        };
    }

    // Consume exactly one queued channel packet
    void consume(std::uint8_t channel_id) {
        receiver_.consume(channel_id);
    }

private:
    Receiver& receiver_;
};

} // namespace fdk::fpga
