find_package(Catch2 3 REQUIRED GLOBAL)
set(CMAKE_MODULE_PATH "${CMAKE_MODULE_PATH}" PARENT_SCOPE)

function(add_catch_tests target)
    cmake_parse_arguments(PARSE_ARGV 1 CATCH_TEST "" "" "SOURCES")
    add_executable(${target} ${CATCH_TEST_SOURCES})
    target_link_libraries(${target} PRIVATE Catch2::Catch2WithMain)
    catch_discover_tests(${target} PROPERTIES TIMEOUT 30)
endfunction()
