"""Shared Verilator build and cocotb test runner."""

from pathlib import Path

import cocotb_tools.runner

import build_tools.common.library_dependency
import build_tools.common


class CocotbVerilatorRunner:
    def __init__(
        self,
        *,
        libraries: list[build_tools.common.library_dependency.LibraryDependency],
        rtl_files: list[Path] | None = None,
        build_dir: Path,
        hdl_toplevel: str,
        parameters: dict[str, object],
        test_module: str,
    ) -> None:
        self._libraries = list(libraries)
        self._rtl_files = list(rtl_files) if rtl_files is not None else []
        self._build_dir = build_dir.resolve()
        self._hdl_toplevel = hdl_toplevel
        self._parameters = dict(parameters)
        self._test_module = test_module

    def run(self) -> None:
        runner = cocotb_tools.runner.get_runner("verilator")
        runner.build(
            sources=[
                *(build_tools.common.REPO_ROOT / source
                  for library in self._libraries
                  for source in library.rtl_files()),
                *self._rtl_files,
            ],
            hdl_toplevel=self._hdl_toplevel,
            parameters=self._parameters,
            build_args=["--assert"],
            build_dir=self._build_dir,
            timescale=("1ns", "1ps"),
        )
        runner.test(
            hdl_toplevel=self._hdl_toplevel,
            test_module=self._test_module,
        )
