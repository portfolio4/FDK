import build_tools.common.library_dependency


# TODO Have a way for this library to indicate it depends on another library
# (the channel library)
LIBRARY = build_tools.common.library_dependency.LibraryDependency([
    "fpga/rtl/uart/uart_rx.sv",
    "fpga/rtl/uart/uart_tx.sv",
    "fpga/rtl/uart/uart_channel_endpoint.sv",
])
