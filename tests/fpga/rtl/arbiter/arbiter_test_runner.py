from pathlib import Path

import pytest

import fpga.rtl.arbiter
import tests.fpga.rtl


@pytest.mark.parametrize("num_inputs, width", [(2, 1), (2, 8), (4, 13), (8, 32)])
def test_stream_rr_arbiter(sim_build_dir: Path, num_inputs: int, width: int) -> None:
    tests.fpga.rtl.CocotbVerilatorRunner(
        libraries=[fpga.rtl.arbiter.LIBRARY],
        hdl_toplevel="fdk_stream_rr_arbiter",
        parameters={"NUM_INPUTS": num_inputs, "DATA_WIDTH": width},
        build_dir=sim_build_dir / f"stream_rr_arbiter_{num_inputs}_{width}",
        test_module="tests.fpga.rtl.arbiter.test_stream_rr_arbiter",
    ).run()


@pytest.mark.parametrize("num_inputs, width", [(2, 1), (2, 8), (4, 13), (8, 32)])
def test_packet_rr_arbiter(sim_build_dir: Path, num_inputs: int, width: int) -> None:
    tests.fpga.rtl.CocotbVerilatorRunner(
        libraries=[fpga.rtl.arbiter.LIBRARY],
        hdl_toplevel="fdk_packet_rr_arbiter",
        parameters={"NUM_INPUTS": num_inputs, "DATA_WIDTH": width},
        build_dir=sim_build_dir / f"packet_rr_arbiter_{num_inputs}_{width}",
        test_module="tests.fpga.rtl.arbiter.test_packet_rr_arbiter",
    ).run()
