"""Generate the afk_main bitstream with Vivado."""

from pathlib import Path

import build_tools.common.build_fpga_template
import build_tools.fpga.basys3
import fpga.rtl.channel
import fpga.rtl.arbiter
import fpga.rtl.fifo
import fpga.rtl.message
import fpga.rtl.string
import fpga.rtl.table
import fpga.rtl.uart


PROJECT_ROOT = Path(__file__).resolve().parent

LIBRARIES = [
    fpga.rtl.uart.LIBRARY,
    fpga.rtl.channel.LIBRARY,
    fpga.rtl.fifo.LIBRARY,
    fpga.rtl.message.LIBRARY,
    fpga.rtl.arbiter.LIBRARY,
    fpga.rtl.string.LIBRARY,
    fpga.rtl.table.LIBRARY,
]

RTL_FILES = [
    PROJECT_ROOT / "defines.sv",
    PROJECT_ROOT / "afk_admin_handler.sv",
    PROJECT_ROOT / "afk_condition_evaluator.sv",
    PROJECT_ROOT / "afk_stimulus_handler.sv",
    PROJECT_ROOT / "afk_reaction_table.sv",
    PROJECT_ROOT / "afk_program_actions_handler.sv",
    PROJECT_ROOT / "afk_main.sv",
]


if __name__ == "__main__":
    build_tools.common.build_fpga_template.BuildFpgaTemplate(
        build_tools.fpga.basys3.Basys3BuildTclGenerator(
            top_name="afk_main",
            constraints_file=PROJECT_ROOT / "afk_main.xdc",
            libraries=LIBRARIES,
            rtl_files=RTL_FILES,
        ),
        project_root=PROJECT_ROOT,
        description=__doc__,
    ).main()
