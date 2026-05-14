add_catch_tests(test_fdk_core SOURCES test_error_text.cpp test_hexdump.cpp)
target_link_libraries(test_fdk_core PRIVATE fdk::core)
