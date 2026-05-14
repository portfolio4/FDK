find_package(Boost 1.87 QUIET CONFIG GLOBAL)
if(NOT Boost_FOUND)
    include(FetchContent)
    FetchContent_Declare(boost_headers
        URL https://archives.boost.io/release/1.87.0/source/boost_1_87_0.tar.bz2
        URL_HASH SHA256=af57be25cb4c4f4b413ed692fe378affb4352ea50fbe294a11ef548f4d527d89
        SOURCE_SUBDIR afk_headers_only)
    FetchContent_MakeAvailable(boost_headers)
    add_library(boost_headers INTERFACE)
    add_library(Boost::headers ALIAS boost_headers)
    target_include_directories(boost_headers SYSTEM INTERFACE "${boost_headers_SOURCE_DIR}")
endif()
