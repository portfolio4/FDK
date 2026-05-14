"""Generate the uart_echo_channels bitstream with Vivado."""

from pathlib import Path

import build_tools.common.build_fpga_template
import build_tools.fpga.basys3
import fpga.rtl.channel
import fpga.rtl.fifo
import fpga.rtl.message
import fpga.rtl.uart


if __name__ == "__main__":
    PROJECT_ROOT = Path(__file__).resolve().parent
    build_tools.common.build_fpga_template.BuildFpgaTemplate(
        build_tools.fpga.basys3.Basys3BuildTclGenerator(
            top_name="uart_echo_channels",
            constraints_file=PROJECT_ROOT / "uart_echo_channels.xdc",
            libraries=[
                fpga.rtl.uart.LIBRARY,
                fpga.rtl.channel.LIBRARY,
                fpga.rtl.fifo.LIBRARY,
                fpga.rtl.message.LIBRARY,
            ],
            rtl_files=[
                PROJECT_ROOT / "request_handler.sv",
                PROJECT_ROOT / "uart_echo_channels.sv",
            ],
        ),
        project_root=PROJECT_ROOT,
        description=__doc__,
    ).main()
