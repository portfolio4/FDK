import build_tools.common.library_dependency


LIBRARY = build_tools.common.library_dependency.LibraryDependency([
    "fpga/rtl/message/defines.sv",
    "fpga/rtl/message/handlers.sv",
    "fpga/rtl/message/echo_request_handler.sv",
    "fpga/rtl/message/message_rx.sv",
    "fpga/rtl/message/message_tx.sv",
])
