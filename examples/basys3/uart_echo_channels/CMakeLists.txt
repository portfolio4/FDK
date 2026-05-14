add_executable(basys3_uart_echo_channels host.cpp)
target_link_libraries(basys3_uart_echo_channels PRIVATE fdk::fpga)
