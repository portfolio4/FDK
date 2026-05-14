from pathlib import Path

import pytest

import fpga.rtl.fifo
import tests.fpga.rtl


@pytest.mark.parametrize("width, depth", [(1, 2), (8, 4), (13, 16), (32, 256)])
@pytest.mark.parametrize(
    "module, allow_full_transfer",
    [("fdk_fifo", False), ("fdk_fifo", True), ("fdk_registered_fifo", False)],
)
def test_fifo(
    sim_build_dir: Path,
    width: int,
    depth: int,
    module: str,
    allow_full_transfer: bool,
) -> None:
    parameters = {"DATA_WIDTH": width, "DEPTH": depth}
    if module == "fdk_fifo":
        parameters["ALLOW_ENQUEUE_DEQUEUE_WHEN_FULL"] = int(allow_full_transfer)
    tests.fpga.rtl.CocotbVerilatorRunner(
        libraries=[fpga.rtl.fifo.LIBRARY],
        hdl_toplevel=module,
        parameters=parameters,
        build_dir=sim_build_dir / f"{module}_{width}_{depth}_{int(allow_full_transfer)}",
        test_module="tests.fpga.rtl.fifo.test_fifo",
    ).run()
