#pragma once

#include <stdexcept>
#include <termios.h>

namespace fdk::fpga {

class UartConfig {
public:
    static speed_t baud_speed(int baud_rate) {
        switch (baud_rate) {
        case 1200: return B1200;
        case 2400: return B2400;
        case 4800: return B4800;
        case 9600: return B9600;
        case 19200: return B19200;
        case 38400: return B38400;
        case 57600: return B57600;
        case 115200: return B115200;
        case 230400: return B230400;
        case 460800: return B460800;
        case 921600: return B921600;
        case 1000000: return B1000000;
        default: throw std::invalid_argument("Unsupported UART baud rate");
        }
    }
};

} // namespace fdk::fpga
