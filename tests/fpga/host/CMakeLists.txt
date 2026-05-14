add_catch_tests(test_fdk_channel SOURCES test_fdk_channel.cpp)
target_link_libraries(test_fdk_channel PRIVATE fdk::fpga)

add_catch_tests(test_fdk_message SOURCES test_fdk_message.cpp)
target_link_libraries(test_fdk_message PRIVATE fdk::fpga)

add_catch_tests(test_fdk_message_sender SOURCES test_fdk_message_sender.cpp)
target_link_libraries(test_fdk_message_sender PRIVATE fdk::fpga)

add_catch_tests(test_fdk_message_reader SOURCES test_fdk_message_reader.cpp)
target_link_libraries(test_fdk_message_reader PRIVATE fdk::fpga)
