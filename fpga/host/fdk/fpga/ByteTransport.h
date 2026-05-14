#pragma once

#include <fdk/fpga/Errors.h>

#include <concepts>
#include <cstddef>
#include <expected>
#include <span>

namespace fdk::fpga {

// send() sends the bytes over the transport
template <typename T>
concept BytesSender = requires(T& sender, std::span<const std::byte> bytes) {
    { sender.send(bytes) } -> std::same_as<std::expected<void, SendError>>;
};

// - poll() polls any bytes off the network and buffers them internally
// - peek() returns all bytes that are available for a consumer to consume
// - consume(count) pops off `count` bytes from the buffer. The consumer calls
//   consume(count) once it is done operating on the peek() data
template <typename T>
concept BytesReceiver = requires(T& receiver, std::size_t count) {
    { receiver.poll() } -> std::same_as<std::expected<void, ReceiveError>>;
    { receiver.peek() } -> std::same_as<std::span<const std::byte>>;
    { receiver.consume(count) } -> std::same_as<void>;
};

} // namespace fdk::fpga
