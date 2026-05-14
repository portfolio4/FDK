"""Generate the uart_echo_bytes bitstream with Vivado."""

from pathlib import Path

import build_tools.common.build_fpga_template
import build_tools.fpga.basys3
import fpga.rtl.uart


if __name__ == "__main__":
    PROJECT_ROOT = Path(__file__).resolve().parent
    build_tools.common.build_fpga_template.BuildFpgaTemplate(
        build_tools.fpga.basys3.Basys3BuildTclGenerator(
            top_name="uart_echo_bytes",
            constraints_file=PROJECT_ROOT / "uart_echo_bytes.xdc",
            libraries=[fpga.rtl.uart.LIBRARY],
            rtl_files=[
                PROJECT_ROOT / "uart_echo_bytes.sv",
            ],
        ),
        project_root=PROJECT_ROOT,
        description=__doc__,
    ).main()
