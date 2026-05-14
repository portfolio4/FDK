#pragma once

#include <algorithm>
#include <array>
#include <cstddef>
#include <format>
#include <string_view>
#include <utility>

namespace fdk {

class ErrorText {
public:
    static constexpr std::size_t CAPACITY = 64;

    // Creates a message, retaining only the first 64 characters.
    template <typename... Args>
    static ErrorText format(std::format_string<Args...> fmt, Args&&... args) {
        ErrorText error;
        const auto result = std::format_to_n(
            error.buffer_.data(), CAPACITY, fmt, std::forward<Args>(args)...);
        error.size_ = std::min(static_cast<std::size_t>(result.size), CAPACITY);
        return error;
    }

    // The buffer is not null-terminated; use the view's length.
    std::string_view text() const noexcept {
        return {buffer_.data(), size_};
    }

private:
    std::array<char, CAPACITY> buffer_{};
    std::size_t size_ = 0;
};

} // namespace fdk
