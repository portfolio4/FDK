#pragma once

#include <cstddef>
#include <iomanip>
#include <span>
#include <sstream>
#include <string>

namespace fdk {

// Format 16 bytes per row with a hexadecimal offset and printable ASCII.
inline std::string hexdump(std::span<const std::byte> bytes) {
    std::ostringstream output;
    output << std::hex << std::setfill('0');
    for (std::size_t offset = 0; offset < bytes.size(); offset += 16) {
        output << std::setw(8) << offset << "  ";
        for (std::size_t column = 0; column < 16; ++column) {
            if (offset + column < bytes.size()) {
                const auto byte = std::to_integer<unsigned int>(bytes[offset + column]);
                output << std::setw(2) << byte << ' ';
            } else {
                output << "   ";
            }
            if (column == 7) output << ' ';
        }
        output << " |";
        for (std::size_t column = 0; column < 16 && offset + column < bytes.size(); ++column) {
            const auto byte = std::to_integer<unsigned int>(bytes[offset + column]);
            output << (byte >= 32 && byte <= 126 ? static_cast<char>(byte) : '.');
        }
        output << "|\n";
    }
    return output.str();
}

} // namespace fdk
