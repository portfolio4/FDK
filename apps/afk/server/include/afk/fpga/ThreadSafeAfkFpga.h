#pragma once

#include <afk/fpga/AfkFpga.h>

#include <mutex>
#include <utility>

#define THREAD_SAFE_WRAPPER(func_name)                                      \
    template <typename... Args>                                                      \
    [[nodiscard]] decltype(auto) func_name(Args&&... args) {                          \
        std::lock_guard<std::mutex> lock(mutex_);                                     \
        return fpga_.func_name(std::forward<Args>(args)...);                          \
    }

namespace afk {

// Serializes complete FPGA operations, including ACK waits. Reaction callbacks
// run with the mutex held: copy borrowed data there and do not reenter the wrapper.
class ThreadSafeAfkFpga {
public:
    explicit ThreadSafeAfkFpga(const char* device_path, int baud_rate = fdk::fpga::platform::BAUD_RATE)
        : fpga_(device_path, baud_rate) {}

    ThreadSafeAfkFpga(const ThreadSafeAfkFpga&) = delete;
    ThreadSafeAfkFpga& operator=(const ThreadSafeAfkFpga&) = delete;

    THREAD_SAFE_WRAPPER(echo_request)
    THREAD_SAFE_WRAPPER(test_request)
    THREAD_SAFE_WRAPPER(program_reaction)
    THREAD_SAFE_WRAPPER(program_condition)
    THREAD_SAFE_WRAPPER(disable_condition)
    THREAD_SAFE_WRAPPER(send_stimulus)
    THREAD_SAFE_WRAPPER(try_read_reaction_for)

private:
    std::mutex mutex_;
    AfkFpga fpga_;
};

} // namespace afk

#undef THREAD_SAFE_WRAPPER
