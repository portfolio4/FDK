set(FPGA_PLATFORM basys3 CACHE STRING "FPGA platform for the host library")
configure_file(
    fdk/fpga/platform/platform.h
    fdk/fpga/platform/platform.h
    @ONLY
)

add_library(fdk_fpga INTERFACE)
add_library(fdk::fpga ALIAS fdk_fpga)
target_include_directories(fdk_fpga INTERFACE
    "${CMAKE_CURRENT_BINARY_DIR}"
    "${CMAKE_CURRENT_SOURCE_DIR}"
)
