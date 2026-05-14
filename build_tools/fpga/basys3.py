"""Basys3 defaults for the shared Vivado build and programming generators."""

from pathlib import Path

import build_tools.common.library_dependency
import build_tools.fpga.vivado
import fpga.rtl.platforms.basys3


class Basys3ProgramTclGenerator(build_tools.fpga.vivado.ProgramTclGenerator):
    def __init__(self, *, top_name: str) -> None:
        super().__init__(device_name="xc7a35t_0", top_name=top_name)


class Basys3BuildTclGenerator(build_tools.fpga.vivado.BuildTclGenerator):
    def __init__(
        self,
        *,
        top_name: str,
        constraints_file: Path,
        libraries: list[build_tools.common.library_dependency.LibraryDependency],
        rtl_files: list[Path],
    ) -> None:
        super().__init__(
            part="xc7a35tcpg236-1",
            top_name=top_name,
            constraints_file=constraints_file,
            libraries=[fpga.rtl.platforms.basys3.LIBRARY] + libraries,
            rtl_files=rtl_files,
        )
