#pragma once

#include <string>
#include <string_view>

namespace afk {

// Use the same ASCII alphabet for stimulus text and programmed trigger patterns.
inline std::string normalize_fpga_text(std::string_view text) {
    std::string result;
    result.reserve(text.size());
    for (unsigned char ch : text) {
        if (ch >= 'A' && ch <= 'Z') {
            result.push_back(static_cast<char>(ch + ('a' - 'A')));
        } else if ((ch >= 'a' && ch <= 'z') || (ch >= '0' && ch <= '9')) {
            result.push_back(static_cast<char>(ch));
        }
    }
    return result;
}

} // namespace afk
