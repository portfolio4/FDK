add_executable(basys3_uart_echo_bytes host.cpp)
target_link_libraries(basys3_uart_echo_bytes PRIVATE fdk::fpga)
