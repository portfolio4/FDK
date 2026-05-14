#pragma once

#include <cstdint>

namespace afk::channels {

// Logical service channels shared with apps/afk/fpga/defines.sv.
inline constexpr std::uint8_t HEARTBEAT = 1;
inline constexpr std::uint8_t ADMIN = 2;
inline constexpr std::uint8_t PROGRAM_ACTIONS = 3;
inline constexpr std::uint8_t TRIGGER = 4;

} // namespace afk::channels
