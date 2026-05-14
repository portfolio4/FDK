#pragma once

namespace fdk::fpga {

enum class SendError { Disconnected, SysWriteError };
enum class ReceiveError { Disconnected, SysPollError, SysReadError };

} // namespace fdk::fpga
