import build_tools.common.library_dependency


LIBRARY = build_tools.common.library_dependency.LibraryDependency([
    "fpga/rtl/channel/channel_rx.sv",
    "fpga/rtl/channel/channel_tx.sv",
    "fpga/rtl/channel/channel_frame_fifo.sv",
])
