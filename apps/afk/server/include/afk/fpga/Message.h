#pragma once

#include <fdk/fpga/message/MessageTypes.h>

#include <cstddef>
#include <cstdint>

namespace afk {

// Payload capacity keeps the complete standalone reaction within 255 bytes.
inline constexpr std::size_t MAX_REACTION_PAYLOAD_SIZE = 237;
inline constexpr std::size_t MAX_CONDITION_MSG_SIZE = 32;

// Matches apps/afk/fpga/defines.sv. Integers are little-endian on the wire.
struct [[gnu::packed]] Heartbeat {
    static constexpr std::uint16_t MSG_TYPE = fdk::fpga::APP_SPECIFIC_MSG_TYPE_0;
    std::uint64_t cycle_count;
};

struct TestRequest {
    static constexpr std::uint16_t MSG_TYPE = fdk::fpga::APP_SPECIFIC_MSG_TYPE_1;
};

// Header-only acknowledgment; the acknowledged sequence is in msg_hdr.ack_seq.
struct Ack {
    static constexpr std::uint16_t MSG_TYPE = fdk::fpga::APP_SPECIFIC_MSG_TYPE_2;
};

// Standalone frame, without an FDK message header. Exactly reaction_len payload
// bytes follow this header, using the same framing as Stimulus.
__extension__ struct [[gnu::packed]] Reaction {
    std::byte preamble[7] = {
        std::byte{0xaa}, std::byte{0xaa}, std::byte{0xaa}, std::byte{0xaa},
        std::byte{0xaa}, std::byte{0xaa}, std::byte{0xaa}
    };
    std::byte start_frame_delimiter = std::byte{0xab};
    std::uint64_t request_id;
    std::uint8_t trigger_condition_id;
    std::uint8_t reaction_len;
    std::byte payload[];
};

// Always send the entire payload buffer, including the unused tail.
struct [[gnu::packed]] ProgramReaction {
    static constexpr std::uint16_t MSG_TYPE = fdk::fpga::APP_SPECIFIC_MSG_TYPE_4;
    std::uint8_t reaction_id;
    std::uint8_t reaction_len;
    std::byte payload[MAX_REACTION_PAYLOAD_SIZE]{};
};

struct [[gnu::packed]] ProgramCondition {
    static constexpr std::uint16_t MSG_TYPE = fdk::fpga::APP_SPECIFIC_MSG_TYPE_5;
    std::uint8_t condition_id;
    std::uint8_t reaction_id;
    std::uint8_t pattern_len;
    std::byte payload[MAX_CONDITION_MSG_SIZE]{};
};

struct [[gnu::packed]] DisableCondition {
    static constexpr std::uint16_t MSG_TYPE = fdk::fpga::APP_SPECIFIC_MSG_TYPE_6;
    std::uint8_t condition_id;
};

// Standalone frame with length trailing payload bytes, without a message header.
// All scalar fields, including length, use the new little-endian AFK protocol.
__extension__ struct [[gnu::packed]] Stimulus {
    std::byte preamble[7] = {
        std::byte{0xaa}, std::byte{0xaa}, std::byte{0xaa}, std::byte{0xaa},
        std::byte{0xaa}, std::byte{0xaa}, std::byte{0xaa}
    };
    std::byte start_frame_delimiter = std::byte{0xab};
    std::uint64_t request_id;
    std::uint16_t length;
    std::byte payload[];
};

template <typename T>
using Message = fdk::fpga::Message<T>;

} // namespace afk
