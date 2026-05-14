#pragma once

#include <fdk/fpga/message/MessageTypes.h>

#include <chrono>
#include <functional>
#include <memory>
#include <utility>

namespace fdk::fpga {

template <MessageReceiverLike Receiver>
class MessageReader {
public:
    // Borrows the message receiver, which must outlive this reader.
    explicit MessageReader(Receiver& receiver) : receiver_(receiver) {}

    // Drain queued messages, poll once if none matched, then drain again.
    // Unrecognized types and incorrect typed message sizes are consumed.
    // Callback receives const MessageView<T>& before consumption; the view is
    // valid during the callback. Poll errors return false.
    template <MessageLike... Ts, typename CallbackFn>
    bool try_read(std::uint8_t channel_id, CallbackFn&& callback) {
        if (read_queued<Ts...>(channel_id, std::forward<CallbackFn>(callback))) {
            return true;
        }
        if (!receiver_.poll()) {
            return false;
        }
        return read_queued<Ts...>(channel_id, std::forward<CallbackFn>(callback));
    }

    // Always attempt one read, including for a zero or negative duration.
    template <MessageLike... Ts, typename CallbackFn, typename Clock = std::chrono::steady_clock>
    bool try_read_for(std::uint8_t channel_id, CallbackFn&& callback, std::chrono::nanoseconds duration) {
        const auto deadline = Clock::now() + duration;
        do {
            if (try_read<Ts...>(channel_id, std::forward<CallbackFn>(callback))) {
                return true;
            }
        } while (Clock::now() < deadline);
        return false;
    }

private:
    template <MessageLike... Ts, typename CallbackFn>
    bool read_queued(std::uint8_t channel_id, CallbackFn&& callback) {
        while (const auto view = receiver_.peek(channel_id)) {
            const bool matched = (dispatch<Ts>(*view, std::forward<CallbackFn>(callback)) || ...);
            receiver_.consume(channel_id);
            if (matched) {
                return true;
            }
        }
        return false;
    }

    template <MessageLike T, typename CallbackFn>
    static bool dispatch(const AnyMessageView& view, CallbackFn&& callback) {
        if (view.msg_bytes.size() != sizeof(Message<T>)) {
            return false;
        }
        const auto* header = view.msg_hdr();
        if (header->msg_type != T::MSG_TYPE || header->msg_size != sizeof(Message<T>)) {
            return false;
        }
        const MessageView<T> message_view{
            .metadata = view.metadata,
            .message = std::start_lifetime_as<Message<T>>(view.msg_bytes.data()),
        };
        std::invoke(std::forward<CallbackFn>(callback), message_view);
        return true;
    }

    Receiver& receiver_;
};

} // namespace fdk::fpga
