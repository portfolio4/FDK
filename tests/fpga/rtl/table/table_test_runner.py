from pathlib import Path

import pytest

import fpga.rtl.table
import tests.fpga.rtl


@pytest.mark.parametrize(
    "depth, data_width, beat_width",
    [(2, 32, 32), (3, 72, 32), (3, 80, 24), (4, 128, 16), (4, 192, 64), (8, 2040, 64)],
)
def test_stream_array_table(
    sim_build_dir: Path, depth: int, data_width: int, beat_width: int,
) -> None:
    tests.fpga.rtl.CocotbVerilatorRunner(
        libraries=[fpga.rtl.table.LIBRARY],
        hdl_toplevel="fdk_stream_array_table",
        parameters={"DEPTH": depth, "DATA_WIDTH": data_width, "BEAT_WIDTH": beat_width},
        build_dir=sim_build_dir / f"stream_array_table_{depth}_{data_width}_{beat_width}",
        test_module="tests.fpga.rtl.table.test_stream_array_table",
    ).run()
