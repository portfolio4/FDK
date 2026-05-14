"""Shared entry point for application FPGA build scripts."""

import argparse
from pathlib import Path

import build_tools.common
import build_tools.fpga.vivado


class BuildFpgaTemplate:
    """Generate Tcl in the selected build directory, then run Vivado."""

    def __init__(
        self,
        generator: build_tools.fpga.vivado.BuildTclGenerator,
        *,
        project_root: Path,
        description: str | None = None,
    ) -> None:
        self._generator = generator
        self._project_root = project_root.resolve()
        self._description = description

    def main(self, *, build_dir: Path | None = None) -> None:
        if build_dir is None:
            parser = argparse.ArgumentParser(description=self._description)
            parser.add_argument("--build-dir", type=Path)
            build_dir = parser.parse_args().build_dir
        output_dir = (
            build_dir.resolve() if build_dir is not None
            else build_tools.common.fpga_build_directory(self._project_root)
        )
        script = self._generator.generate(build_dir=output_dir)
        build_tools.fpga.vivado.build_with_vivado(script)

