"""Load the existing uart_echo_bytes bitstream with Vivado."""

from pathlib import Path

import build_tools.common.program_fpga_template
import build_tools.fpga.basys3


if __name__ == "__main__":
    build_tools.common.program_fpga_template.ProgramFpgaTemplate(
        build_tools.fpga.basys3.Basys3ProgramTclGenerator(top_name="uart_echo_bytes"),
        project_root=Path(__file__).resolve().parent,
        description=__doc__,
    ).main()
