#pragma once

#include <fdk/fpga/channel/ChannelTypes.h>
#include <fdk/fpga/message/MessageTypes.h>

#include <expected>
#include <limits>

namespace fdk::fpga {

template <ChannelSenderLike Sender>
class MessageSender {
public:
    // Borrows the channel sender, which must outlive this message sender.
    explicit MessageSender(Sender& sender) : sender_(sender) {}

    // Header fields and payload scalars use the native little-endian wire order.
    template <MessageLike T>
    std::expected<void, SendError> send(std::uint8_t channel_id, std::uint32_t seq,
                                      std::uint32_t ack_seq, const T& payload) const {
        static_assert(sizeof(Message<T>) <= std::numeric_limits<std::uint16_t>::max(),
                      "Message size must fit the 16-bit msg_size field");
        Message<T> message{
            .msg_hdr = {
                .msg_size = static_cast<std::uint16_t>(sizeof(Message<T>)),
                .seq = seq,
                .ack_seq = ack_seq,
                .msg_type = T::MSG_TYPE,
            },
            .msg = payload,
        };
        return sender_.send(channel_id, message);
    }

private:
    Sender& sender_;
};

} // namespace fdk::fpga
